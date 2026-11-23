using System.Globalization;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>模組版本展示模型</summary>
public sealed class ModVersionDisplayItem
{
    public string VersionId { get; init; } = string.Empty;

    public string VersionNumber { get; init; } = string.Empty;

    public string GameVersions { get; init; } = string.Empty;

    public string Loaders { get; init; } = string.Empty;

    public string DatePublished { get; init; } = string.Empty;

    public string FileName { get; init; } = string.Empty;

    public string DownloadUrl { get; init; } = string.Empty;

    public string? ExpectedHash { get; init; }

    public string HashAlgorithm { get; init; } = ModHelpers.PreferredHashAlgorithm;

    public IReadOnlyList<string> Dependencies { get; init; } = [];
}

/// <summary>線上模組版本選擇對話方塊 ViewModel</summary>
public sealed partial class ModVersionPickerViewModel : DialogViewModelBase
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ModVersionPickerViewModel));
    private readonly IModrinthClient _modrinthClient;
    private readonly string _projectId;
    private readonly LoaderKind? _loader;
    private readonly string? _minecraftVersion;

    public ModVersionPickerViewModel(
        IModrinthClient modrinthClient,
        string projectId,
        string projectTitle,
        LoaderKind? loader = null,
        string? minecraftVersion = null)
    {
        ArgumentNullException.ThrowIfNull(modrinthClient);
        ArgumentException.ThrowIfNullOrWhiteSpace(projectId);
        _modrinthClient = modrinthClient;
        _projectId = projectId;
        _loader = loader;
        _minecraftVersion = minecraftVersion;

        ProjectTitle = projectTitle;
        Versions = [];

        _ = RunSafeAsync(LoadVersionsAsync, "載入模組版本清單", Logger);
    }

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(InstallCommand), nameof(QueueCommand))]
    public partial ModVersionDisplayItem? SelectedVersion { get; set; }

    [ObservableProperty]
    public partial string StatusMessage { get; set; } = "正在讀取版本清單...";

    public string ProjectTitle { get; }

    public BulkObservableCollection<ModVersionDisplayItem> Versions { get; }

    /// <summary>使用者選擇「加入安裝清單」時所挑定的版本</summary>
    public ModVersionDisplayItem? QueuedVersion { get; private set; }

    /// <summary>使用者是否選擇立即安裝（false 代表僅加入安裝清單）</summary>
    public bool InstallImmediately { get; private set; }

    private bool CanCommit => SelectedVersion is { DownloadUrl.Length: > 0 };

    public async Task LoadVersionsAsync()
    {
        if (IsDisposed)
        {
            return;
        }

        CancellationToken token = LifetimeToken;
        try
        {
            var list = await _modrinthClient
                .GetProjectVersionsAsync(_projectId, loader: _loader, minecraftVersion: _minecraftVersion, cancellationToken: token);

            var versionItems = list.Select(version =>
            {
                var file = version.PrimaryFile;
                return new ModVersionDisplayItem
                {
                    VersionId = version.VersionId,
                    VersionNumber = string.IsNullOrWhiteSpace(version.VersionNumber) ? version.DisplayName : version.VersionNumber,
                    GameVersions = string.Join(", ", version.GameVersions),
                    Loaders = string.Join(", ", version.Loaders),
                    DatePublished = FormatPublishedDate(version.DatePublished),
                    FileName = file?.FileName ?? "-",
                    DownloadUrl = file?.Url ?? string.Empty,
                    ExpectedHash = ModHelpers.ResolveHash(file, out string algorithm),
                    HashAlgorithm = algorithm,
                    Dependencies = ModBatchOperations.GetRequiredDependencyIds(version)
                };
            });

            Versions.ReplaceAll(versionItems);

            if (Versions.Count > 0)
            {
                SelectedVersion = Versions[0];
                StatusMessage = $"共 {Versions.Count} 個相容版本，預設選取最新版本";
            }
            else
            {
                StatusMessage = "此模組在目前伺服器的 Minecraft 版本與載入器下無相容版本";
            }
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested)
        {
            Logger.Information("模組版本選擇視窗已關閉，取消讀取版本清單");
        }
        catch (Exception exception) when (exception is not OperationCanceledException)
        {
            Logger.Warning(exception, "讀取模組版本清單失敗");
            StatusMessage = $"讀取版本清單失敗：{exception.Message}";
        }
    }

    [RelayCommand(CanExecute = nameof(CanCommit))]
    public void Install()
    {
        if (!TryCommit())
        {
            return;
        }

        InstallImmediately = true;
        Close(true);
    }

    [RelayCommand(CanExecute = nameof(CanCommit))]
    public void Queue()
    {
        if (!TryCommit())
        {
            return;
        }

        InstallImmediately = false;
        Close(true);
    }

    [RelayCommand]
    public void Cancel() => Close(false);

    private bool TryCommit()
    {
        if (SelectedVersion is null)
        {
            StatusMessage = "請先選取一個版本";
            return false;
        }

        if (string.IsNullOrWhiteSpace(SelectedVersion.DownloadUrl))
        {
            StatusMessage = "此版本沒有可下載的檔案";
            return false;
        }

        QueuedVersion = SelectedVersion;
        return true;
    }

    private static string FormatPublishedDate(string raw)
    {
        if (string.IsNullOrWhiteSpace(raw))
        {
            return "-";
        }

        return DateTimeOffset.TryParse(raw, out var parsed)
            ? parsed.ToLocalTime().ToString("yyyy-MM-dd", CultureInfo.InvariantCulture)
            : raw;
    }
}
