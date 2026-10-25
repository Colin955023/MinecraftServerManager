using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Services;
using System.IO;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.App.ViewModels;

public sealed partial class JavaItemViewModel : ObservableObject
{
    [ObservableProperty]
    public partial string DisplayName { get; set; } = string.Empty;

    [ObservableProperty]
    public partial int MajorVersion { get; set; }

    [ObservableProperty]
    public partial string ExecutablePath { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string Vendor { get; set; } = "未知廠商";

    [ObservableProperty]
    public partial bool Is64Bit { get; set; } = true;

    [ObservableProperty]
    public partial bool IsRecommended { get; set; }

    [ObservableProperty]
    public partial string StatusText { get; set; } = string.Empty;
}

public sealed partial class ManageJavaViewModel : ViewModelBase
{
    private readonly IUiService _ui;

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("ManageJava");
    private readonly IJavaRuntimeDetector? _javaDetector;
    private readonly IMinecraftJavaRequirementService? _javaRequirementService;
    private readonly IJavaInstaller? _javaInstaller;

    [ObservableProperty]
    public partial string MinecraftVersionText { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string RequiredMajorText { get; set; } = string.Empty;

    [ObservableProperty]
    public partial int? RequiredMajor { get; set; }

    [ObservableProperty]
    public partial JavaItemViewModel? SelectedJava { get; set; }

    [ObservableProperty]
    public partial int SelectedInstallMajor { get; set; }

    [ObservableProperty]
    public partial bool IsBusy { get; set; }

    [ObservableProperty]
    public partial string StatusMessage { get; set; } = string.Empty;

    public BulkObservableCollection<JavaItemViewModel> InstalledJavas { get; } = [];
    public BulkObservableCollection<int> AvailableInstallMajors { get; } = [];

    public string? ResultJavaPath { get; private set; }

    public event Action? RequestClose;

    public ManageJavaViewModel(
        IJavaRuntimeDetector? javaDetector,
        IMinecraftJavaRequirementService? javaRequirementService,
        IJavaInstaller? javaInstaller,
        string currentJavaPath,
        string minecraftVersion,
        string loaderName,
        IUiService? uiService = null)
    {
        _ui = uiService ?? NoOpUiService.Instance;
        _javaDetector = javaDetector;
        _javaRequirementService = javaRequirementService;
        _javaInstaller = javaInstaller;

        MinecraftVersionText = minecraftVersion;
        var lk = Enum.TryParse<LoaderKind>(loaderName, ignoreCase: true, out var kind) ? kind : LoaderKind.Unknown;
        RequiredMajor = _javaRequirementService?.GetCachedJavaMajor(minecraftVersion, lk);

        RequiredMajorText = RequiredMajor.HasValue
            ? $"Java {RequiredMajor.Value}"
            : "未限定 (依需求選擇)";

        var majors = _javaRequirementService?.GetCachedAvailableJavaMajors() ?? [];
        AvailableInstallMajors.ReplaceAll(majors);

        SelectedInstallMajor = RequiredMajor.HasValue && AvailableInstallMajors.Contains(RequiredMajor.Value)
            ? RequiredMajor.Value
            : (AvailableInstallMajors.Count > 0 ? AvailableInstallMajors[^1] : 0);

        ResultJavaPath = currentJavaPath;
        _ = RunSafeAsync(() => LoadInstalledJavasAsync(currentJavaPath), "載入已安裝 Java 清單", Logger);
    }

    [RelayCommand]
    public async Task RefreshAsync() => await LoadInstalledJavasAsync(SelectedJava?.ExecutablePath ?? ResultJavaPath, forceRefresh: true).ConfigureAwait(true);

    [RelayCommand]
    public async Task AutoDetectAsync()
    {
        if (_javaDetector is null)
        {
            return;
        }

        IsBusy = true;
        StatusMessage = "正在自動尋找最符合的 Java...";
        try
        {
            JavaRuntimeInfo? matched = null;
            if (RequiredMajor.HasValue)
            {
                matched = await _javaDetector.FindBestMatchAsync(RequiredMajor.Value).ConfigureAwait(true);
            }

            if (matched is null)
            {
                var all = await _javaDetector.DetectAsync(forceRefresh: true).ConfigureAwait(true);
                matched = all.Count > 0 ? all[0] : null;
            }

            await LoadInstalledJavasAsync(matched?.ExecutablePath, forceRefresh: false).ConfigureAwait(true);

            if (matched is not null)
            {
                StatusMessage = $"已配對最佳版本：Java {matched.MajorVersion}";
            }
            else
            {
                StatusMessage = "本機尚未安裝符合需求的 Java 版本";
            }
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "自動偵測 Java 失敗: {Message}", ex.Message);
            StatusMessage = $"自動偵測失敗：{ex.Message}";
        }
        finally
        {
            IsBusy = false;
        }
    }

    [RelayCommand]
    public async Task InstallWithWingetAsync()
    {
        if (_javaInstaller is null)
        {
            StatusMessage = "未提供自動安裝器";
            return;
        }

        int targetMajor = SelectedInstallMajor;
        IsBusy = true;
        StatusMessage = "正在檢查本機 Java 候選版本...";
        try
        {
            // 點選之後先觸發重新整理本機候選
            await LoadInstalledJavasAsync(SelectedJava?.ExecutablePath ?? ResultJavaPath, forceRefresh: true).ConfigureAwait(true);

            // 比對目標 Java 主要版本在本機候選中是否有可用的
            var javaSnapshot = InstalledJavas.ToList();
            var existing = await Task.Run(() => javaSnapshot.FirstOrDefault(j =>
                j.MajorVersion == targetMajor &&
                !string.IsNullOrWhiteSpace(j.ExecutablePath) &&
                SafeFileSystem.FileExists(j.ExecutablePath))).ConfigureAwait(true);

            if (existing is not null)
            {
                SelectedJava = existing;
                StatusMessage = $"本機已有可使用的 Java {targetMajor}，已自動選取：{existing.ExecutablePath}";
                _ui.ShowToast(
                    $"本機已偵測到可使用的 Java {targetMajor}！\n\n路徑：{existing.ExecutablePath}\n廠商：{existing.Vendor}\n\n系統已為您自動選取該版本，無需重複安裝。",
                    "本機已有可用版本",
                    ToastType.Info);
                return;
            }

            StatusMessage = $"正在透過 winget 安裝 Java {targetMajor}，請在 UAC 提示時允許...";
            await _javaInstaller.InstallWithWingetAsync(targetMajor).ConfigureAwait(true);
            StatusMessage = $"Java {targetMajor} 安裝完成，正在重新整理清單...";
            await LoadInstalledJavasAsync(null, forceRefresh: true).ConfigureAwait(true);

            // 自動選取剛安裝的版本
            var justInstalled = InstalledJavas.FirstOrDefault(j => j.MajorVersion == targetMajor);
            if (justInstalled is not null)
            {
                SelectedJava = justInstalled;
            }
            StatusMessage = $"成功安裝並選取 Java {targetMajor}";
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "winget 安裝 Java {Major} 失敗: {Message}", targetMajor, ex.Message);
            StatusMessage = $"安裝失敗：{ex.Message}";
            _ui.ShowError($"安裝 Java {targetMajor} 失敗或被拒絕：\n{ex.Message}", "Java 安裝失敗");
        }
        finally
        {
            IsBusy = false;
        }
    }

    [RelayCommand]
    public void BrowseFile()
    {
        if (_ui.PickFiles("選取 Java 執行檔", "Java 執行檔 (javaw.exe;java.exe)|javaw.exe;java.exe|所有檔案 (*.*)|*.*") is { Count: > 0 } picked)
        {
            string path = picked[0];
            var existing = InstalledJavas.FirstOrDefault(j => string.Equals(j.ExecutablePath, path, StringComparison.OrdinalIgnoreCase));
            if (existing is not null)
            {
                SelectedJava = existing;
            }
            else
            {
                var customItem = new JavaItemViewModel
                {
                    DisplayName = "自訂指定 Java",
                    MajorVersion = 0,
                    ExecutablePath = path,
                    Vendor = "自訂路徑",
                    Is64Bit = true,
                    StatusText = "使用者手動指定"
                };
                InstalledJavas.Insert(0, customItem);
                SelectedJava = customItem;
            }
            StatusMessage = $"已手動選取：{path}";
        }
    }

    [RelayCommand]
    public void Apply()
    {
        if (SelectedJava is null)
        {
            StatusMessage = "請先從清單選取一個 Java 版本";
            return;
        }

        ResultJavaPath = SelectedJava.ExecutablePath;
        RequestClose?.Invoke();
    }

    private async Task LoadInstalledJavasAsync(string? preferredPath, bool forceRefresh = false)
    {
        if (_javaDetector is null)
        {
            return;
        }

        IsBusy = true;
        try
        {
            var detected = await _javaDetector.DetectAsync(forceRefresh).ConfigureAwait(true);
            var items = new List<JavaItemViewModel>();
            JavaItemViewModel? toSelect = null;
            foreach (var j in detected)
            {
                if (string.IsNullOrWhiteSpace(j.ExecutablePath) ||
                    !Path.IsPathRooted(j.ExecutablePath) ||
                    string.Equals(Path.GetFileName(j.ExecutablePath), j.ExecutablePath, StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                bool isMatch = RequiredMajor.HasValue && j.MajorVersion == RequiredMajor.Value;
                string status = RequiredMajor.HasValue
                    ? (isMatch ? "符合需求" : $"不符需求 (需要 Java {RequiredMajor.Value})")
                    : "可用";

                var item = new JavaItemViewModel
                {
                    DisplayName = $"Java {j.MajorVersion} ({j.MajorVersion})",
                    MajorVersion = j.MajorVersion,
                    ExecutablePath = j.ExecutablePath,
                    Vendor = string.IsNullOrWhiteSpace(j.Vendor) ? "OpenJDK / Oracle" : j.Vendor,
                    Is64Bit = j.Is64Bit,
                    IsRecommended = isMatch,
                    StatusText = status
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
        catch (Exception ex)
        {
            Logger.Error(ex, "載入已安裝 Java 清單失敗: {Message}", ex.Message);
            StatusMessage = $"載入 Java 清單失敗：{ex.Message}";
        }
        finally
        {
            IsBusy = false;
        }
    }
}
