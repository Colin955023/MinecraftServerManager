using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

public sealed class JavaItemViewModel
{
    public string DisplayName { get; init; } = string.Empty;

    public int MajorVersion { get; init; }

    public string ExecutablePath { get; init; } = string.Empty;

    public string Vendor { get; init; } = "未知廠商";

    public bool IsRecommended { get; init; }

    public string StatusText { get; init; } = string.Empty;
}

/// <summary>Java 主要版本選項</summary>
public sealed record JavaMajorOption(int Major, string DisplayName)
{
    public override string ToString() => DisplayName;
}

/// <summary>Java 管理對話視窗 ViewModel</summary>
public sealed partial class ManageJavaViewModel : DialogViewModelBase
{
    private const string UnlimitedMajorText = "未限定（依需求選擇）";

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ManageJavaViewModel));
    private readonly IUiService _ui;
    private readonly IJavaRuntimeDetector _javaDetector;
    private readonly IJavaInstaller _javaInstaller;
    private readonly ILocalFileSystem _fileSystem;
    private readonly SerialCancellation _listFetch = new();
    private int _busyDepth;

    public ManageJavaViewModel(
        IJavaRuntimeDetector javaDetector,
        IMinecraftJavaRequirementService javaRequirementService,
        IJavaInstaller javaInstaller,
        string currentJavaPath,
        string minecraftVersion,
        ILocalFileSystem fileSystem,
        IUiService uiService)
    {
        ArgumentNullException.ThrowIfNull(javaDetector);
        ArgumentNullException.ThrowIfNull(javaRequirementService);
        ArgumentNullException.ThrowIfNull(javaInstaller);
        ArgumentNullException.ThrowIfNull(fileSystem);
        ArgumentNullException.ThrowIfNull(uiService);
        _ui = uiService;
        _fileSystem = fileSystem;
        _javaDetector = javaDetector;
        _javaInstaller = javaInstaller;

        MinecraftVersionText = minecraftVersion ?? string.Empty;
        AvailableInstallOptions.ReplaceAll(javaRequirementService.GetCachedAvailableJavaMajors()
            .Select(static m => new JavaMajorOption(m, $"Java {m}")));
        RequiredMajor = javaRequirementService.GetCachedJavaMajor(MinecraftVersionText);
        if (SelectedInstallMajorOption is null && AvailableInstallOptions.Count > 0)
        {
            SelectedInstallMajorOption = AvailableInstallOptions[^1];
        }

        ResultJavaPath = currentJavaPath;
        _ = RunSafeAsync(() => LoadInstalledJavasAsync(currentJavaPath), "載入已安裝 Java 清單", Logger);

        if (!RequiredMajor.HasValue && !string.IsNullOrWhiteSpace(MinecraftVersionText))
        {
            _ = RunSafeAsync(() => ResolveRequiredMajorAsync(javaRequirementService), "補齊 Java 版本需求", Logger);
        }
    }

    public string MinecraftVersionText { get; }

    [ObservableProperty]
    public partial string RequiredMajorText { get; set; } = UnlimitedMajorText;

    [ObservableProperty]
    public partial int? RequiredMajor { get; set; }

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ApplyCommand))]
    public partial JavaItemViewModel? SelectedJava { get; set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(SelectedInstallMajor))]
    [NotifyCanExecuteChangedFor(nameof(InstallWithWingetCommand))]
    public partial JavaMajorOption? SelectedInstallMajorOption { get; set; }

    public int SelectedInstallMajor => SelectedInstallMajorOption?.Major ?? 0;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(RefreshCommand), nameof(AutoDetectCommand), nameof(InstallWithWingetCommand), nameof(BrowseFileCommand), nameof(ApplyCommand))]
    public partial bool IsBusy { get; private set; }

    [ObservableProperty]
    public partial string StatusMessage { get; set; } = string.Empty;

    public BulkObservableCollection<JavaItemViewModel> InstalledJavas { get; } = [];
    public BulkObservableCollection<JavaMajorOption> AvailableInstallOptions { get; } = [];

    public string? ResultJavaPath { get; private set; }

    private bool IsIdle => !IsBusy;

    private bool CanInstall => !IsBusy && SelectedInstallMajor > 0;

    private bool CanApply => !IsBusy && SelectedJava is not null;

    [RelayCommand]
    public void Cancel() => Close(false);

    private async Task ResolveRequiredMajorAsync(IMinecraftJavaRequirementService javaRequirementService)
    {
        CancellationToken token = LifetimeToken;
        try
        {
            RequiredMajor = await javaRequirementService.GetRequiredJavaMajorAsync(MinecraftVersionText, token);
            await LoadInstalledJavasAsync(ResultJavaPath);
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested)
        {
            Logger.Information("視窗已關閉，取消補齊 Java 版本需求");
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "非同步補齊 Minecraft 版本「{Version}」指定 Java 需求失敗", MinecraftVersionText);
        }
    }

    partial void OnRequiredMajorChanged(int? value)
    {
        RequiredMajorText = value.HasValue ? $"Java {value.Value}" : UnlimitedMajorText;
        if (value is int major && FindInstallOption(major) is { } option)
        {
            SelectedInstallMajorOption = option;
        }
    }

    private JavaMajorOption? FindInstallOption(int major) => AvailableInstallOptions.FirstOrDefault(o => o.Major == major);

    [RelayCommand(CanExecute = nameof(IsIdle))]
    public Task RefreshAsync() => LoadInstalledJavasAsync(SelectedJava?.ExecutablePath ?? ResultJavaPath, forceRefresh: true);

    [RelayCommand(CanExecute = nameof(IsIdle))]
    public async Task AutoDetectAsync()
    {
        CancellationToken token = LifetimeToken;
        BeginBusy();
        StatusMessage = "正在自動尋找最符合的 Java...";
        try
        {
            JavaRuntimeInfo? matched = null;
            if (RequiredMajor.HasValue)
            {
                matched = await _javaDetector.FindBestMatchAsync(RequiredMajor.Value, token);
            }

            if (matched is null)
            {
                var all = await _javaDetector.DetectAsync(forceRefresh: true, token);
                matched = all.Count > 0 ? all[0] : null;
            }

            await LoadInstalledJavasAsync(matched?.ExecutablePath);
            StatusMessage = matched is not null
                ? $"已配對最佳版本：Java {matched.MajorVersion}"
                : "本機尚未安裝符合需求的 Java 版本";
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested)
        {
            Logger.Information("視窗已關閉，取消自動偵測 Java");
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "自動偵測 Java 失敗");
            StatusMessage = $"自動偵測失敗：{ex.Message}";
        }
        finally
        {
            EndBusy();
        }
    }

    [RelayCommand(CanExecute = nameof(CanInstall))]
    public async Task InstallWithWingetAsync()
    {
        int targetMajor = SelectedInstallMajor;
        if (targetMajor <= 0)
        {
            StatusMessage = "請先選擇要安裝的 Java 版本";
            return;
        }

        CancellationToken token = LifetimeToken;
        BeginBusy();
        StatusMessage = "正在檢查本機 Java 候選版本...";
        try
        {
            await LoadInstalledJavasAsync(SelectedJava?.ExecutablePath ?? ResultJavaPath, forceRefresh: true);

            JavaItemViewModel? existing = null;
            foreach (var candidate in InstalledJavas.ToList())
            {
                if (candidate.MajorVersion == targetMajor
                    && await _fileSystem.FileExistsAsync(candidate.ExecutablePath, token))
                {
                    existing = candidate;
                    break;
                }
            }

            if (existing is not null)
            {
                SelectedJava = existing;
                StatusMessage = $"本機已有可使用的 Java {targetMajor}，已自動選取：{existing.ExecutablePath}";
                _ui.ShowNotification(
                    $"本機已偵測到可使用的 Java {targetMajor}！\n\n路徑：{existing.ExecutablePath}\n廠商：{existing.Vendor}\n\n系統已為您自動選取該版本，無需重複安裝。",
                    "本機已有可用版本",
                    NotificationType.Info);
                return;
            }

            StatusMessage = $"正在透過 winget 安裝 Java {targetMajor}，請在 UAC 提示時允許...";
            await _javaInstaller.InstallWithWingetAsync(targetMajor, token);
            StatusMessage = $"Java {targetMajor} 安裝完成，正在重新整理清單...";
            await LoadInstalledJavasAsync(null, forceRefresh: true);

            if (InstalledJavas.FirstOrDefault(j => j.MajorVersion == targetMajor) is { } justInstalled)
            {
                SelectedJava = justInstalled;
            }

            StatusMessage = $"成功安裝並選取 Java {targetMajor}";
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested)
        {
            Logger.Information("視窗已關閉，取消安裝 Java {Major}", targetMajor);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "winget 安裝 Java {Major} 失敗", targetMajor);
            StatusMessage = $"安裝失敗：{ex.Message}";
            await _ui.ShowErrorAsync($"安裝 Java {targetMajor} 失敗或被拒絕：\n{ex.Message}", "Java 安裝失敗");
        }
        finally
        {
            EndBusy();
        }
    }

    [RelayCommand(CanExecute = nameof(IsIdle))]
    public async Task BrowseFileAsync()
    {
        if (await _ui.PickFilesAsync("選取 Java 執行檔", FileTypeChoice.JavaExecutable) is not { Count: > 0 } picked)
        {
            return;
        }

        string path = picked[0];
        var existing = InstalledJavas.FirstOrDefault(j => string.Equals(j.ExecutablePath, path, StringComparison.OrdinalIgnoreCase));
        if (existing is null)
        {
            existing = new JavaItemViewModel
            {
                DisplayName = "自訂指定 Java",
                MajorVersion = 0,
                ExecutablePath = path,
                Vendor = "自訂路徑",
                StatusText = "使用者手動指定"
            };
            InstalledJavas.Insert(0, existing);
        }

        SelectedJava = existing;
        StatusMessage = $"已手動選取：{path}";
    }

    [RelayCommand(CanExecute = nameof(CanApply))]
    public void Apply()
    {
        if (SelectedJava is null)
        {
            StatusMessage = "請先從清單選取一個 Java 版本";
            return;
        }

        ResultJavaPath = SelectedJava.ExecutablePath;
        Close(true);
    }

    private void BeginBusy()
    {
        _busyDepth++;
        IsBusy = true;
    }

    private void EndBusy()
    {
        _busyDepth = Math.Max(0, _busyDepth - 1);
        IsBusy = _busyDepth > 0;
    }

    /// <summary>重新載入已安裝 Java 清單；新的載入會取消尚未完成的前一次</summary>
    private async Task LoadInstalledJavasAsync(string? preferredPath, bool forceRefresh = false)
    {
        if (IsDisposed)
        {
            return;
        }

        CancellationToken token = _listFetch.Next();
        BeginBusy();
        try
        {
            var detected = await _javaDetector.DetectAsync(forceRefresh, token);
            token.ThrowIfCancellationRequested();
            var items = new List<JavaItemViewModel>();
            JavaItemViewModel? toSelect = null;
            foreach (var j in detected)
            {
                if (string.IsNullOrWhiteSpace(j.ExecutablePath) || !Path.IsPathFullyQualified(j.ExecutablePath))
                {
                    continue;
                }

                bool isMatch = RequiredMajor.HasValue && j.MajorVersion == RequiredMajor.Value;
                var item = new JavaItemViewModel
                {
                    DisplayName = $"Java {j.MajorVersion}",
                    MajorVersion = j.MajorVersion,
                    ExecutablePath = j.ExecutablePath,
                    Vendor = string.IsNullOrWhiteSpace(j.Vendor) ? "OpenJDK / Oracle" : j.Vendor,
                    IsRecommended = isMatch,
                    StatusText = RequiredMajor.HasValue
                        ? (isMatch ? "符合需求" : $"不符需求（需要 Java {RequiredMajor.Value}）")
                        : "可用"
                };
                items.Add(item);

                if (!string.IsNullOrWhiteSpace(preferredPath) &&
                    string.Equals(j.ExecutablePath, preferredPath, StringComparison.OrdinalIgnoreCase))
                {
                    toSelect = item;
                }
                else if (toSelect is null && isMatch)
                {
                    toSelect = item;
                }
            }

            InstalledJavas.ReplaceAll(items);
            SelectedJava = toSelect ?? InstalledJavas.FirstOrDefault();
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested)
        {
            Logger.Information("Java 清單載入已由新的載入取代或視窗已關閉");
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "載入已安裝 Java 清單失敗");
            StatusMessage = $"載入 Java 清單失敗：{ex.Message}";
        }
        finally
        {
            EndBusy();
        }
    }

    protected override void OnDispose() => _listFetch.Dispose();
}
