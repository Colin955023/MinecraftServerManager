using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Services;
using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 建立伺服器頁面 ViewModel
/// </summary>
public sealed partial class CreateServerViewModel : PageViewModel
{
    private readonly IUiService _ui;

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("CreateServer");
    private readonly IJavaRuntimeDetector? _javaDetector;
    private readonly IMinecraftJavaRequirementService? _javaRequirementService;
    private readonly IJavaInstaller? _javaInstaller;
    private readonly IServerRuntime? _serverRuntime;
    private readonly IServerManager? _serverManager;
    private readonly ILoaderCatalogService? _loaderCatalog;
    private readonly Action<string, bool>? _notificationSink;
    private readonly IExternalLauncher? _launcher;
    private readonly Action<string, string?>? _navigateCallback;
    private readonly long _systemMemoryMb;
    private List<string>? _customJvmArgs;
    private bool _isServerNameManuallyEdited;
    private bool _isProgrammaticServerNameUpdate;
    private bool _isUserManuallySelectedVersion;
    private bool _isProgrammaticVersionUpdate;

    [ObservableProperty]
    public partial string ServerName { get; set; }

    [ObservableProperty]
    public partial string JavaPath { get; set; } = string.Empty;
    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsNotDetectingJava))]
    public partial bool IsDetectingJava { get; set; }

    public bool IsNotDetectingJava => !IsDetectingJava;

    [ObservableProperty]
    public partial string SelectedLoader { get; set; } = "Paper";

    [ObservableProperty]
    public partial string SelectedLoaderVersion { get; set; } = "最新穩定版 (Paper)";

    [ObservableProperty]
    public partial bool IsLoaderVersionEnabled { get; set; } = true;

    [ObservableProperty]
    public partial bool IsLoadingVersions { get; set; }

    [ObservableProperty]
    public partial string LoadingStatusText { get; set; } = string.Empty;

    [ObservableProperty]
    public partial bool IsMinecraftVersionReloadEnabled { get; set; }

    [ObservableProperty]
    public partial string SelectedMinecraftVersion { get; set; } = "1.21.4";

    [ObservableProperty]
    public partial string MinMemoryMb { get; set; } = "1024";

    [ObservableProperty]
    public partial string MaxMemoryMb { get; set; } = "2048";

    [ObservableProperty]
    public partial string MemoryWarningText { get; set; } = string.Empty;

    [ObservableProperty]
    public partial bool IsMemoryWarning { get; set; }

    [ObservableProperty]
    public partial bool IsMemoryError { get; set; }

    [ObservableProperty]
    public partial string JvmArgsSummary { get; set; } = "使用系統建議 JVM 參數 (G1GC)";

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(CreateServerCommand))]
    [NotifyCanExecuteChangedFor(nameof(ResetFormCommand))]
    public partial bool IsCreating { get; set; }

    private bool CanCreateServer => !IsCreating;
    private bool CanResetForm => !IsCreating;

    public CreateServerViewModel(
        IJavaRuntimeDetector? javaDetector = null,
        IServerManager? serverManager = null,
        ILoaderCatalogService? loaderCatalog = null,
        Action<string, bool>? notificationSink = null,
        long? systemMemoryMb = null,
        IExternalLauncher? launcher = null,
        Action<string, string?>? navigateCallback = null,
        IMinecraftJavaRequirementService? javaRequirementService = null,
        IJavaInstaller? javaInstaller = null,
        IServerRuntime? serverRuntime = null,
        IUiService? uiService = null)
        : base("create", "建立新伺服器", "設定名稱、版本、模組載入器與記憶體參數建立伺服器")
    {
        _ui = uiService ?? NoOpUiService.Instance;
        _javaDetector = javaDetector;
        _javaRequirementService = javaRequirementService;
        _javaInstaller = javaInstaller;
        _serverRuntime = serverRuntime;
        _serverManager = serverManager;
        _loaderCatalog = loaderCatalog;
        _notificationSink = notificationSink;
        _launcher = launcher;
        _navigateCallback = navigateCallback;
        _systemMemoryMb = systemMemoryMb ?? Core.Utilities.MemoryUtils.GetTotalSystemMemoryMb();

        AvailableLoaders = ["Paper", "Fabric", "Quilt", "Forge", "NeoForge"];
        AvailableMinecraftVersions =
        [
            "1.21.4",
            "1.21.3",
            "1.21.1",
            "1.20.6",
            "1.20.4",
            "1.20.1",
            "1.19.4",
            "1.18.2",
            "1.16.5",
            "1.12.2"
        ];
        ServerName = $"{SelectedLoader} {SelectedMinecraftVersion}";
        LoaderVersions = [SelectedLoaderVersion];

        int? cachedMajor = _javaRequirementService?.GetCachedJavaMajor(SelectedMinecraftVersion);
        JvmArgsSummary = (cachedMajor is null or >= 21) ? "使用系統建議 JVM 參數 (ZGC)" : "使用系統建議 JVM 參數 (G1GC)";
        IsMinecraftVersionReloadEnabled = !string.Equals(SelectedLoader, "Paper", StringComparison.OrdinalIgnoreCase);

        UpdateLoaderStateSync();
        UpdateMemoryWarning();

        if (_loaderCatalog is not null)
        {
            _ = InitializeVersionsAsync();
        }
    }

    public ObservableCollection<string> AvailableLoaders { get; }

    public BulkObservableCollection<string> AvailableMinecraftVersions { get; }

    public BulkObservableCollection<string> LoaderVersions { get; }

    public static string EulaNoticeText =>
        "請務必閱讀並同意 Minecraft EULA 條款 (點我閱讀)\n點選建立即表示你同意 Minecraft 條款，任何違法行為本軟體不負責任";

    public static string EulaUrl => "https://aka.ms/MinecraftEULA";

    partial void OnServerNameChanged(string value)
    {
        if (_isProgrammaticServerNameUpdate)
        {
            return;
        }

        string expectedDefault = $"{SelectedLoader} {SelectedMinecraftVersion}";
        _isServerNameManuallyEdited = !string.Equals(value.Trim(), expectedDefault, StringComparison.OrdinalIgnoreCase);
    }

    partial void OnSelectedLoaderChanged(string value)
    {
        IsMinecraftVersionReloadEnabled = !string.Equals(value, "Paper", StringComparison.OrdinalIgnoreCase);
        UpdateSynchronizedServerName();
        _ = HandleLoaderChangedAsync(value);
    }

    private async Task HandleLoaderChangedAsync(string loaderName)
    {
        try
        {
            if (Enum.TryParse<LoaderKind>(loaderName, ignoreCase: true, out var lk))
            {
                await UpdateMinecraftVersionsForLoaderAsync(lk).ConfigureAwait(true);
            }
            await RefreshLoaderVersionsAsync().ConfigureAwait(true);
        }
        catch (Exception ex)
        {
            Logger.Warning("切換載入器 {Loader} 更新版本清單失敗: {Message}", loaderName, ex.Message);
        }
    }

    private void SetMinecraftVersionProgrammatically(string version)
    {
        _isProgrammaticVersionUpdate = true;
        try
        {
            SelectedMinecraftVersion = version;
        }
        finally
        {
            _isProgrammaticVersionUpdate = false;
        }
    }

    private async Task UpdateMinecraftVersionsForLoaderAsync(LoaderKind loaderKind)
    {
        if (_loaderCatalog is null)
        {
            return;
        }

        try
        {
            var versions = await _loaderCatalog.GetMinecraftVersionsForLoaderAsync(loaderKind).ConfigureAwait(true);
            if (versions.Count > 0)
            {
                AvailableMinecraftVersions.ReplaceAll(versions.Select(static v => v.Version));

                if (!_isUserManuallySelectedVersion || !AvailableMinecraftVersions.Contains(SelectedMinecraftVersion))
                {
                    SetMinecraftVersionProgrammatically(AvailableMinecraftVersions[0]);
                }
            }
        }
        catch
        {
        }
    }

    partial void OnSelectedMinecraftVersionChanged(string value)
    {
        if (!_isProgrammaticVersionUpdate)
        {
            _isUserManuallySelectedVersion = true;
        }
        UpdateSynchronizedServerName();
        if (_customJvmArgs == null)
        {
            if (_javaRequirementService is not null)
            {
                _ = UpdateJvmArgsSummaryAsync(value);
            }
        }
        _ = RefreshLoaderVersionsAsync();
    }

    private async Task UpdateJvmArgsSummaryAsync(string version)
    {
        if (string.IsNullOrWhiteSpace(version))
        {
            return;
        }

        try
        {
            var lk = Enum.TryParse<LoaderKind>(SelectedLoader, ignoreCase: true, out var kind) ? kind : LoaderKind.Unknown;
            int major = await _javaRequirementService!.GetRequiredJavaMajorAsync(version, lk).ConfigureAwait(true);
            if (_customJvmArgs == null && string.Equals(SelectedMinecraftVersion, version, StringComparison.OrdinalIgnoreCase))
            {
                JvmArgsSummary = major >= 21 ? "使用系統建議 JVM 參數 (ZGC)" : "使用系統建議 JVM 參數 (G1GC)";
            }
        }
        catch
        {
            // 無法從官方取得時保持預設，嚴禁版本號碼硬推算猜測
        }
    }

    partial void OnMinMemoryMbChanged(string value) => UpdateMemoryWarning();

    partial void OnMaxMemoryMbChanged(string value) => UpdateMemoryWarning();

    private void SetServerNameProgrammatically(string name)
    {
        _isProgrammaticServerNameUpdate = true;
        try
        {
            ServerName = name;
        }
        finally
        {
            _isProgrammaticServerNameUpdate = false;
        }
    }

    private void UpdateSynchronizedServerName()
    {
        if (!_isServerNameManuallyEdited)
        {
            SetServerNameProgrammatically($"{SelectedLoader} {SelectedMinecraftVersion}");
            return;
        }

        string currentName = ServerName;
        string mcVersion = SelectedMinecraftVersion;
        foreach (string loader in AvailableLoaders)
        {
            string prefix = $"{loader} {mcVersion}";
            if (currentName.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            {
                string suffix = currentName[prefix.Length..];
                SetServerNameProgrammatically($"{SelectedLoader} {mcVersion}{suffix}");
                return;
            }
        }
    }

    private async Task InitializeVersionsAsync()
    {
        if (_loaderCatalog is null)
        {
            return;
        }

        IsLoadingVersions = true;
        LoadingStatusText = "正在載入可用版本清單...";
        try
        {
            var loaderKind = Enum.TryParse<LoaderKind>(SelectedLoader, ignoreCase: true, out var lk) ? lk : LoaderKind.Paper;
            var versions = await _loaderCatalog.GetMinecraftVersionsForLoaderAsync(loaderKind).ConfigureAwait(true);
            if (versions.Count > 0)
            {
                AvailableMinecraftVersions.ReplaceAll(versions.Select(static v => v.Version));

                if (!_isUserManuallySelectedVersion || !AvailableMinecraftVersions.Contains(SelectedMinecraftVersion))
                {
                    SetMinecraftVersionProgrammatically(AvailableMinecraftVersions[0]);
                }
            }
        }
        catch
        {
            // 忽略預載入失敗，維持既有預設版本清單
        }

        await RefreshLoaderVersionsAsync().ConfigureAwait(true);
        if (_javaRequirementService is not null)
        {
            _ = Task.Run(async () =>
            {
                try
                {
                    await _javaRequirementService.PreloadAllJavaRequirementsAsync().ConfigureAwait(false);
                }
                catch (Exception ex)
                {
                    Logger.Warning("背景預載 Java 需求失敗，沿用既有快取: {Message}", ex.Message);
                }
            });
        }
        IsLoadingVersions = false;
        LoadingStatusText = string.Empty;
    }

    private async Task RefreshLoaderVersionsAsync()
    {
        if (_loaderCatalog is null || !Enum.TryParse<LoaderKind>(SelectedLoader, ignoreCase: true, out var loaderKind))
        {
            UpdateLoaderStateSync();
            return;
        }

        try
        {
            var versions = await _loaderCatalog.GetLoaderVersionsAsync(loaderKind, SelectedMinecraftVersion).ConfigureAwait(true);
            if (versions.Count > 0)
            {
                LoaderVersions.ReplaceAll(versions.Select(static v => v.Version));
                SelectedLoaderVersion = LoaderVersions[0];
                IsLoaderVersionEnabled = loaderKind is LoaderKind.Forge or LoaderKind.NeoForge;
            }
            else
            {
                LoaderVersions.ReplaceAll(["無可用版本"]);
                SelectedLoaderVersion = "無可用版本";
                IsLoaderVersionEnabled = false;
            }
        }
        catch
        {
            UpdateLoaderStateSync();
        }
    }

    private void UpdateLoaderStateSync()
    {
        LoaderVersions.ReplaceAll([$"最新穩定版 ({SelectedLoader})"]);
        SelectedLoaderVersion = LoaderVersions[0];
        IsLoaderVersionEnabled = Enum.TryParse<LoaderKind>(SelectedLoader, ignoreCase: true, out var lk) &&
                                 lk is LoaderKind.Forge or LoaderKind.NeoForge;
    }

    [RelayCommand]
    public void OpenEula() => _launcher?.OpenUrl(EulaUrl, isTrusted: true);

    [RelayCommand]
    public void OpenManageJava()
    {
        var vm = new ManageJavaViewModel(
            _javaDetector,
            _javaRequirementService,
            _javaInstaller,
            JavaPath,
            SelectedMinecraftVersion,
            SelectedLoader,
            uiService: _ui);

        if (_ui.ShowManageJava(vm) == true && !string.IsNullOrWhiteSpace(vm.ResultJavaPath))
        {
            JavaPath = vm.ResultJavaPath;
        }
    }

    [RelayCommand]
    public async Task AutoDetectJavaAsync() => await AutoDetectJavaInternalAsync(silent: false).ConfigureAwait(true);

    private async Task<bool> AutoDetectJavaInternalAsync(bool silent)
    {
        if (_javaDetector is null)
        {
            if (!silent)
            {
                _notificationSink?.Invoke("未設定 Java 偵測器", true);
            }
            return false;
        }

        IsDetectingJava = true;
        try
        {
            int? targetMajor = null;
            if (_javaRequirementService is not null && !string.IsNullOrWhiteSpace(SelectedMinecraftVersion))
            {
                try
                {
                    var lk = Enum.TryParse<LoaderKind>(SelectedLoader, ignoreCase: true, out var kind) ? kind : LoaderKind.Unknown;
                    targetMajor = await _javaRequirementService.GetRequiredJavaMajorAsync(SelectedMinecraftVersion, lk).ConfigureAwait(true);
                }
                catch (Exception ex)
                {
                    Logger.Warning("向官方或載入器取得 Minecraft {Version} 之 Java major 失敗: {Error}", SelectedMinecraftVersion, ex.Message);
                }
            }

            JavaRuntimeInfo? matched = targetMajor.HasValue
                ? await _javaDetector.FindBestMatchAsync(targetMajor.Value).ConfigureAwait(true)
                : null;

            if (matched is not null)
            {
                JavaPath = matched.ExecutablePath;
                Logger.Information("依據 Minecraft {McVersion} (官方指定需求 Java {TargetMajor}) 配對到最佳 Java {FoundMajor}：{Path}",
                    SelectedMinecraftVersion, targetMajor, matched.MajorVersion, JavaPath);
                return true;
            }

            if (!silent && targetMajor.HasValue)
            {
                Logger.Warning("本機未偵測到 Minecraft {Version} 所需之 Java {Major}", SelectedMinecraftVersion, targetMajor.Value);
                string pkgDesc = targetMajor.Value == 8 ? "Oracle JRE 8" : $"Microsoft OpenJDK {targetMajor.Value}";
                bool installAgreed = _ui.Confirm(
                    $"本機未偵測到 Minecraft {SelectedMinecraftVersion} 所需的 Java {targetMajor.Value}。\n\n是否要使用 Windows 套件管理工具 (winget) 自動下載並安裝 {pkgDesc}？",
                    "缺少必要的 Java 版本");

                if (installAgreed)
                {
                    if (_javaInstaller is not null)
                    {
                        _notificationSink?.Invoke($"正在透過 winget 安裝 Java {targetMajor.Value}，請在命令提示字元視窗與 UAC 提示時允許...", false);
                        try
                        {
                            await _javaInstaller.InstallWithWingetAsync(targetMajor.Value).ConfigureAwait(true);
                            _notificationSink?.Invoke($"Java {targetMajor.Value} 安裝完成，正在重新偵測...", false);

                            await _javaDetector.DetectAsync(forceRefresh: true).ConfigureAwait(true);

                            var recheck = await _javaDetector.FindBestMatchAsync(targetMajor.Value).ConfigureAwait(true);
                            if (recheck is not null)
                            {
                                JavaPath = recheck.ExecutablePath;
                                _notificationSink?.Invoke($"成功設定 Java {recheck.MajorVersion}：{JavaPath}", false);
                                return true;
                            }
                            else
                            {
                                _notificationSink?.Invoke("安裝已完成，但尚未能在預設路徑偵測到執行檔，請嘗試手動瀏覽選取", true);
                            }
                        }
                        catch (Exception ex)
                        {
                            Logger.Error(ex, "透過 winget 安裝 Java 失敗: {Message}", ex.Message);
                            _ui.ShowError($"透過 winget 安裝 Java {targetMajor.Value} 失敗：\n{ex.Message}\n\n請手動前往官網下載並安裝對應版本。", "安裝失敗");
                        }
                    }
                    else
                    {
                        _notificationSink?.Invoke("尚未設定 winget 自動安裝器，請手動安裝 Java", true);
                    }
                }
                else
                {
                    _notificationSink?.Invoke($"未安裝 Minecraft {SelectedMinecraftVersion} 所需之 Java {targetMajor.Value}，請手動指定正確版本", true);
                }
            }
            else if (!silent)
            {
                _notificationSink?.Invoke("無法判定目前 Minecraft 版本所需之 Java 版本，請手動指定路徑", true);
            }

            return false;
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "自動偵測 Java 失敗: {Message}", ex.Message);
            if (!silent)
            {
                _notificationSink?.Invoke($"自動偵測 Java 失敗：{ex.Message}", true);
            }
            return false;
        }
        finally
        {
            IsDetectingJava = false;
        }
    }

    [RelayCommand]
    public async Task ReloadMinecraftVersions()
    {
        if (string.Equals(SelectedLoader, "Paper", StringComparison.OrdinalIgnoreCase))
        {
            return;
        }

        IsLoadingVersions = true;
        LoadingStatusText = "正在向網路重新整理 Minecraft 版本清單...";
        try
        {
            if (_loaderCatalog is not null)
            {
                try
                {
                    var lk = Enum.TryParse<LoaderKind>(SelectedLoader, ignoreCase: true, out var kind) ? kind : LoaderKind.Unknown;
                    var versions = await _loaderCatalog.GetMinecraftVersionsForLoaderAsync(lk, forceReload: true).ConfigureAwait(true);
                    if (versions.Count > 0)
                    {
                        AvailableMinecraftVersions.ReplaceAll(versions.Select(static v => v.Version));
                        if (!AvailableMinecraftVersions.Contains(SelectedMinecraftVersion))
                        {
                            SelectedMinecraftVersion = AvailableMinecraftVersions[0];
                        }
                        _javaRequirementService?.ReloadCache();
                        await UpdateJvmArgsSummaryAsync(SelectedMinecraftVersion).ConfigureAwait(true);
                        Logger.Information("已手動向網路重新整理 {Loader} 的 Minecraft 版本清單，共 {Count} 個版本", SelectedLoader, versions.Count);
                        await RefreshLoaderVersionsAsync().ConfigureAwait(true);
                        return;
                    }
                }
                catch (Exception ex)
                {
                    Logger.Error(ex, "重新整理版本清單失敗: {Message}", ex.Message);
                    return;
                }
            }
        }
        finally
        {
            IsLoadingVersions = false;
            LoadingStatusText = string.Empty;
        }
    }

    [RelayCommand]
    public async Task ReloadLoaderVersions()
    {
        IsLoadingVersions = true;
        LoadingStatusText = "正在向網路重新整理載入器版本清單...";
        try
        {
            if (_loaderCatalog is not null)
            {
                if (string.Equals(SelectedLoader, "Paper", StringComparison.OrdinalIgnoreCase))
                {
                    try
                    {
                        var versions = await _loaderCatalog.GetPaperMinecraftVersionsAsync(forceReload: true).ConfigureAwait(true);
                        if (versions.Count > 0)
                        {
                            AvailableMinecraftVersions.ReplaceAll(versions.Select(static v => v.Version));
                            if (!AvailableMinecraftVersions.Contains(SelectedMinecraftVersion))
                            {
                                SelectedMinecraftVersion = AvailableMinecraftVersions[0];
                            }
                        }
                        _javaRequirementService?.ReloadCache();
                        await UpdateJvmArgsSummaryAsync(SelectedMinecraftVersion).ConfigureAwait(true);
                        Logger.Information("已手動向網路重新整理 PaperMC 版本清單，共 {Count} 個版本", versions.Count);
                    }
                    catch (Exception ex)
                    {
                        Logger.Error(ex, "重新整理 PaperMC 版本清單失敗: {Message}", ex.Message);
                    }
                }
                else
                {
                    await _loaderCatalog.ForceReloadAllLoadersAsync().ConfigureAwait(true);
                    Logger.Information("已強制向網路重新載入所有載入器版本清單");
                }
            }
            await RefreshLoaderVersionsAsync().ConfigureAwait(true);
        }
        finally
        {
            IsLoadingVersions = false;
            LoadingStatusText = string.Empty;
        }
    }

    [RelayCommand]
    public void ConfigureJvmArgs()
    {
        int maxMem = int.TryParse(MaxMemoryMb.Trim(), out int m) ? m : 2048;
        int? javaMajor = _javaRequirementService?.GetCachedJavaMajor(SelectedMinecraftVersion);
        var vm = new JvmArgsViewModel(javaMajor, maxMem, SelectedLoader, _customJvmArgs);
        if (_ui.ShowJvmArgs(vm) == true)
        {
            var finalArgs = vm.GetFinalJvmArgs();
            _customJvmArgs = [.. finalArgs];
            JvmArgsSummary = finalArgs.Count > 0
                ? $"已套用 {finalArgs.Count} 個 JVM 參數"
                : "無使用自訂 JVM 參數";
            Logger.Information("JVM 參數已設定，共 {Count} 個參數", finalArgs.Count);
        }
    }

    [RelayCommand(CanExecute = nameof(CanResetForm))]
    public void ResetForm()
    {
        if (!_ui.Confirm("確定要重設建立伺服器表單的所有欄位內容嗎？", "確認重設表單"))
        {
            return;
        }

        SelectedLoader = "Paper";
        IsMinecraftVersionReloadEnabled = false;
        SelectedMinecraftVersion = AvailableMinecraftVersions.Count > 0 ? AvailableMinecraftVersions[0] : "1.21.4";
        SelectedLoaderVersion = $"最新穩定版 ({SelectedLoader})";
        ServerName = $"Paper {SelectedMinecraftVersion}";
        MinMemoryMb = "1024";
        MaxMemoryMb = "2048";
        JavaPath = string.Empty;
        _customJvmArgs = null;
        int? javaMajor = _javaRequirementService?.GetCachedJavaMajor(SelectedMinecraftVersion);
        JvmArgsSummary = (javaMajor is null or >= 21)
            ? "使用系統建議 JVM 參數 (ZGC)"
            : "使用系統建議 JVM 參數 (G1GC)";
        UpdateLoaderStateSync();
        UpdateMemoryWarning();
        Logger.Information("建立伺服器表單已重設為預設值 (Paper {Version})", SelectedMinecraftVersion);
    }

    [RelayCommand(CanExecute = nameof(CanCreateServer))]
    public async Task CreateServer()
    {
        if (IsCreating)
        {
            return;
        }

        if (string.IsNullOrWhiteSpace(ServerName))
        {
            _notificationSink?.Invoke("伺服器名稱不能為空", true);
            return;
        }

        if (IsMemoryError)
        {
            _notificationSink?.Invoke($"記憶體設定無效：{MemoryWarningText}", true);
            return;
        }

        if (_serverManager is not null)
        {
            IsCreating = true;
            try
            {
                var lk = Enum.TryParse<LoaderKind>(SelectedLoader, ignoreCase: true, out var loaderKind) ? loaderKind : LoaderKind.Unknown;
                int? targetMajor = _javaRequirementService?.GetCachedJavaMajor(SelectedMinecraftVersion, lk);

                string effectiveJavaPath = JavaPath?.Trim() ?? string.Empty;
                if (targetMajor.HasValue && _javaDetector is not null)
                {
                    bool currentMatches = false;
                    if (!string.IsNullOrWhiteSpace(effectiveJavaPath))
                    {
                        var detected = await _javaDetector.DetectAsync(forceRefresh: false).ConfigureAwait(true);
                        var currentInfo = detected.FirstOrDefault(j => string.Equals(j.ExecutablePath, effectiveJavaPath, StringComparison.OrdinalIgnoreCase));
                        if (currentInfo is not null && currentInfo.MajorVersion == targetMajor.Value)
                        {
                            currentMatches = true;
                        }
                    }

                    if (!currentMatches)
                    {
                        var matched = await _javaDetector.FindBestMatchAsync(targetMajor.Value).ConfigureAwait(true);
                        if (matched is not null)
                        {
                            effectiveJavaPath = matched.ExecutablePath;
                            Logger.Information("建立伺服器已自動切換使用符合之 Java {Major}：{Path}（不覆寫表單欄位）", matched.MajorVersion, effectiveJavaPath);
                        }
                        else
                        {
                            Logger.Warning("建立伺服器已終止：本機未安裝符合 Minecraft {Version} 所需之 Java {Major}", SelectedMinecraftVersion, targetMajor.Value);
                            _ui.ShowError(
                                $"建立伺服器已終止！\n\nMinecraft {SelectedMinecraftVersion} 強制需要 Java {targetMajor.Value}，但系統偵測不到相容的 Java 執行檔。\n請點選「管理 Java」安裝或設定 Java {targetMajor.Value} 後再進行建立。",
                                "Java 版本不相符");
                            return;
                        }
                    }
                }

                if (string.IsNullOrWhiteSpace(effectiveJavaPath))
                {
                    _notificationSink?.Invoke("未設定合適的 Java 執行檔路徑，請點選「管理 Java」指定或安裝", true);
                    return;
                }

                int minMem = int.TryParse(MinMemoryMb.Trim(), out int min) ? min : 1024;
                int maxMem = int.TryParse(MaxMemoryMb.Trim(), out int max) ? max : 2048;

                string loaderVer = SelectedLoaderVersion;
                if (loaderVer is "無" or "無可用版本")
                {
                    loaderVer = string.Empty;
                }

                var plan = ServerCreationPlan.Create(
                    name: Domain.ValueObjects.ServerName.Parse(ServerName.Trim()),
                    minecraftVersion: Domain.ValueObjects.MinecraftVersion.Parse(SelectedMinecraftVersion),
                    loaderType: loaderKind,
                    loaderVersion: loaderVer,
                    memoryMaxMb: maxMem,
                    memoryMinMb: minMem,
                    jvmArgs: _customJvmArgs,
                    userJavaPath: effectiveJavaPath);

                Logger.Information("開始建立伺服器: {Name}, 版本: {Version}, 載入器: {Loader}, 記憶體: {Min}M-{Max}M, Java: {Java}",
                    plan.Name.Value, plan.MinecraftVersion.Value, plan.LoaderType, plan.MemoryMinMb, plan.MemoryMaxMb, effectiveJavaPath);

                var progressDialog = _ui.ShowServerCreationProgress(plan.Name.Value);

                ServerCreationResult created;
                try
                {
                    created = await _serverManager.CreateServerAsync(plan, progressDialog.Progress);
                }
                finally
                {
                    progressDialog.Complete();
                }

                if (created.Completed && created.Config is not null)
                {
                    Logger.Information("伺服器檔案與腳本已建立完成: {Name}，路徑: {Path}，即將執行初次啟動初始化", created.Config.Name.Value, created.Config.Path);

                    bool initSuccess = true;
                    if (_serverRuntime is not null)
                    {
                        initSuccess = _ui.ShowServerInitialization(created.Config, effectiveJavaPath, _serverRuntime);
                    }

                    _ui.ActivateMainWindow();

                    if (initSuccess)
                    {
                        Logger.Information("伺服器建立成功: {Name}，路徑: {Path}", created.Config.Name.Value, created.Config.Path);
                        _notificationSink?.Invoke($"伺服器「{created.Config.Name.Value}」已成功建立並完成初始化！", false);
                        _navigateCallback?.Invoke("manage", created.Config.Name.Value);
                    }
                    else
                    {
                        Logger.Warning("伺服器「{Name}」初次初始化未完成或已被中斷", created.Config.Name.Value);
                        _ui.ShowWarning(
                            $"伺服器「{created.Config.Name.Value}」初次啟動初始化已被強制中斷。\n\n伺服器檔案已完整保留，您稍後可於「管理伺服器」頁面手動啟動伺服器繼續完成世界生成與設定。",
                            "伺服器初始化已中斷");
                        _navigateCallback?.Invoke("manage", created.Config.Name.Value);
                    }
                }
                else
                {
                    Logger.Warning("伺服器建立失敗: {Message}", created.Message);
                    _notificationSink?.Invoke($"建立伺服器失敗：{created.Message}", true);
                    _ui.ShowWarning($"建立伺服器失敗：\n{created.Message}", "建立伺服器被拒絕");
                }
                return;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "建立伺服器時發生例外: {Message}", ex.Message);
                _notificationSink?.Invoke($"建立伺服器失敗：{ex.Message}", true);
                _ui.ShowError($"建立伺服器時發生錯誤：\n{ex.Message}", "建立伺服器失敗");
                return;
            }
            finally
            {
                IsCreating = false;
            }
        }

        _notificationSink?.Invoke($"準備建立伺服器「{ServerName}」({SelectedMinecraftVersion} / {SelectedLoader})", false);
    }

    private void UpdateMemoryWarning()
    {
        bool hasMin = int.TryParse(MinMemoryMb.Trim(), out int minMem);
        bool hasMax = int.TryParse(MaxMemoryMb.Trim(), out int maxMem);

        if (!hasMax)
        {
            MemoryWarningText = "⚠️ 警告：最大記憶體必須為有效的正整數";
            IsMemoryError = true;
            IsMemoryWarning = false;
            return;
        }

        if (hasMin && minMem > maxMem)
        {
            MemoryWarningText = "⚠️ 警告：最小記憶體必須小於最大記憶體";
            IsMemoryError = true;
            IsMemoryWarning = false;
            return;
        }

        if (_systemMemoryMb > 0)
        {
            if (maxMem > _systemMemoryMb || (hasMin && minMem > _systemMemoryMb))
            {
                MemoryWarningText = $"⚠️ 警告：設定記憶體超過系統總記憶體 ({_systemMemoryMb}MB)";
                IsMemoryError = true;
                IsMemoryWarning = false;
                return;
            }

            long halfSystem = _systemMemoryMb / 2;
            if (maxMem > halfSystem || (hasMin && minMem > halfSystem))
            {
                MemoryWarningText = $"⚠️ 警告：設定記憶體超過系統記憶體的一半 ({halfSystem}MB)";
                IsMemoryError = false;
                IsMemoryWarning = true;
                return;
            }
        }

        MemoryWarningText = string.Empty;
        IsMemoryError = false;
        IsMemoryWarning = false;
    }
}
