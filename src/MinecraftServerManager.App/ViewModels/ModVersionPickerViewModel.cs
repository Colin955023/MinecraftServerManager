using System.Collections.ObjectModel;
using System.Globalization;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 模組版本展示模型
/// </summary>
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

    public string HashAlgorithm { get; init; } = "sha512";

    public IReadOnlyList<string> Dependencies { get; init; } = [];
}

/// <summary>
/// 線上模組版本選擇對話框 ViewModel
/// </summary>
public sealed partial class ModVersionPickerViewModel : ObservableObject
{
    private readonly IModrinthClient _modrinthClient;
    private readonly string _projectId;
    private readonly string? _loader;
    private readonly string? _minecraftVersion;

    [ObservableProperty]
    private ModVersionDisplayItem? _selectedVersion;

    [ObservableProperty]
    private string _statusMessage = "正在讀取版本清單…";

    [ObservableProperty]
    private bool _isBusy;

    public ModVersionPickerViewModel(
        IModrinthClient modrinthClient,
        string projectId,
        string projectTitle,
        string? loader = null,
        string? minecraftVersion = null)
    {
        _modrinthClient = modrinthClient;
        _projectId = projectId;
        _loader = loader;
        _minecraftVersion = minecraftVersion;

        ProjectTitle = projectTitle;
        WindowTitle = $"選擇模組版本 — {projectTitle}";
        Versions = [];

        _ = LoadVersionsAsync();
    }

    public string WindowTitle { get; }

    public string ProjectTitle { get; }

    public ObservableCollection<ModVersionDisplayItem> Versions { get; }

    /// <summary>
    /// 使用者選擇「加入安裝清單」時所挑定的版本。
    /// </summary>
    public ModVersionDisplayItem? QueuedVersion { get; private set; }

    /// <summary>
    /// 使用者是否選擇立即安裝（false 代表僅加入安裝清單）。
    /// </summary>
    public bool InstallImmediately { get; private set; }

    public event Action<bool>? RequestClose;

    [RelayCommand]
    public async Task LoadVersionsAsync()
    {
        IsBusy = true;
        try
        {
            var list = await _modrinthClient
                .GetProjectVersionsAsync(_projectId, loader: _loader, minecraftVersion: _minecraftVersion)
                .ConfigureAwait(true);

            Versions.Clear();
            foreach (var version in list)
            {
                var file = version.PrimaryFile;
                Versions.Add(new ModVersionDisplayItem
                {
                    VersionId = version.VersionId,
                    VersionNumber = string.IsNullOrWhiteSpace(version.VersionNumber) ? version.DisplayName : version.VersionNumber,
                    GameVersions = string.Join(", ", version.GameVersions),
                    Loaders = string.Join(", ", version.Loaders),
                    DatePublished = FormatPublishedDate(version.DatePublished),
                    FileName = file?.Filename ?? "-",
                    DownloadUrl = file?.Url ?? string.Empty,
                    ExpectedHash = ResolveHash(file, out string algorithm),
                    HashAlgorithm = algorithm,
                    Dependencies = [.. version.Dependencies
                        .Select(d => d.ProjectId ?? string.Empty)
                        .Where(id => id.Length > 0)]
                });
            }

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
        catch (Exception exception)
        {
            StatusMessage = $"讀取版本清單失敗：{exception.Message}";
        }
        finally
        {
            IsBusy = false;
        }
    }

    [RelayCommand]
    public void Install()
    {
        if (!TryCommit())
        {
            return;
        }

        InstallImmediately = true;
        RequestClose?.Invoke(true);
    }

    [RelayCommand]
    public void Queue()
    {
        if (!TryCommit())
        {
            return;
        }

        InstallImmediately = false;
        RequestClose?.Invoke(true);
    }

    [RelayCommand]
    public void Cancel() => RequestClose?.Invoke(false);

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

    private static string? ResolveHash(ModFile? file, out string algorithm)
    {
        algorithm = "sha512";
        if (file?.Hashes is null)
        {
            return null;
        }

        if (file.Hashes.TryGetValue("sha512", out string? sha512) && !string.IsNullOrWhiteSpace(sha512))
        {
            algorithm = "sha512";
            return sha512;
        }

        if (file.Hashes.TryGetValue("sha1", out string? sha1) && !string.IsNullOrWhiteSpace(sha1))
        {
            algorithm = "sha1";
            return sha1;
        }

        return null;
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
