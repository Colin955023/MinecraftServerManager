using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Services;
using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 建立伺服器頁面 ViewModel
/// </summary>
public sealed partial class CreateServerViewModel : PageViewModel
{
    private readonly IUiService _ui;

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(CreateServerViewModel));
    private static readonly string[] NoAvailableVersions = ["無可用版本"];
    private readonly IJavaRuntimeDetector _javaDetector;
    private readonly IMinecraftJavaRequirementService _javaRequirementService;
    private readonly IJavaInstaller _javaInstaller;
    private readonly IServerRuntime _serverRuntime;
    private readonly IServerLaunchPlanner _launchPlanner;
    private readonly ILocalFileSystem _fileSystem;
    private readonly IServerManager _serverManager;
    private readonly ILoaderCatalogService _loaderCatalog;
    private readonly IExternalLauncher _launcher;
    private readonly Action<string, string?> _navigateCallback;
    private readonly long _systemMemoryMb;
    private List<string>? _customJvmArgs;
    private bool _isServerNameManuallyEdited;
    private bool _isProgrammaticServerNameUpdate;
    private bool _isUserManuallySelectedVersion;
    private bool _isProgrammaticVersionUpdate;

    [ObservableProperty]
    public partial string ServerName { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string JavaPath { get; set; } = string.Empty;

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
    public partial string SelectedMinecraftVersion { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string MinMemoryMb { get; set; } = ServerDefaults.DefaultMemoryMinMb.ToString(System.Globalization.CultureInfo.InvariantCulture);

    [ObservableProperty]
    public partial string MaxMemoryMb { get; set; } = ServerDefaults.DefaultMemoryMaxMb.ToString(System.Globalization.CultureInfo.InvariantCulture);

    [ObservableProperty]
    public partial string MemoryWarningText { get; set; } = string.Empty;

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
        ILocalFileSystem fileSystem,
        IUiService uiService,
        IJavaRuntimeDetector javaDetector,
        IServerManager serverManager,
        ILoaderCatalogService loaderCatalog,
        long systemMemoryMb,
        IExternalLauncher launcher,
        Action<string, string?> navigateCallback,
        IMinecraftJavaRequirementService javaRequirementService,
        IJavaInstaller javaInstaller,
        IServerRuntime serverRuntime,
        IServerLaunchPlanner launchPlanner)
        : base("建立新伺服器")
    {
        ArgumentNullException.ThrowIfNull(fileSystem);
        ArgumentNullException.ThrowIfNull(uiService);
        ArgumentNullException.ThrowIfNull(javaDetector);
        ArgumentNullException.ThrowIfNull(serverManager);
        ArgumentNullException.ThrowIfNull(loaderCatalog);
        ArgumentNullException.ThrowIfNull(launcher);
        ArgumentNullException.ThrowIfNull(navigateCallback);
        ArgumentNullException.ThrowIfNull(javaRequirementService);
        ArgumentNullException.ThrowIfNull(javaInstaller);
        ArgumentNullException.ThrowIfNull(serverRuntime);
        ArgumentNullException.ThrowIfNull(launchPlanner);

        _ui = uiService;
        _javaDetector = javaDetector;
        _javaRequirementService = javaRequirementService;
        _javaInstaller = javaInstaller;
        _serverRuntime = serverRuntime;
        _launchPlanner = launchPlanner;
        _fileSystem = fileSystem;
        _serverManager = serverManager;
        _loaderCatalog = loaderCatalog;
        _launcher = launcher;
        _navigateCallback = navigateCallback;
        _systemMemoryMb = systemMemoryMb;

        AvailableLoaders = ["Paper", "Fabric", "Quilt", "Forge", "NeoForge"];
        AvailableMinecraftVersions = [];
        SetServerNameProgrammatically(DefaultServerName);
        LoaderVersions = [SelectedLoaderVersion];

        int? cachedMajor = _javaRequirementService.GetCachedJavaMajor(SelectedMinecraftVersion);
        JvmArgsSummary = RecommendedJvmSummary(cachedMajor);
        IsMinecraftVersionReloadEnabled = !IsPaperSelected;

        UpdateLoaderStateSync();
        UpdateMemoryWarning();

        _ = RunSafeAsync(InitializeVersionsAsync, "初始化 Minecraft 版本清單", Logger);
    }

    public ObservableCollection<string> AvailableLoaders { get; }

    public BulkObservableCollection<string> AvailableMinecraftVersions { get; }

    public BulkObservableCollection<string> LoaderVersions { get; }


    private const string EulaUrl = "https://aka.ms/MinecraftEULA";

    partial void OnServerNameChanged(string value)
    {
        if (_isProgrammaticServerNameUpdate)
        {
            return;
        }

        _isServerNameManuallyEdited = !string.Equals(value.Trim(), DefaultServerName, StringComparison.OrdinalIgnoreCase);
    }

    partial void OnSelectedLoaderChanged(string value)
    {
        IsMinecraftVersionReloadEnabled = !IsPaperSelected;
        UpdateSynchronizedServerName();
        _ = RunSafeAsync(() => HandleLoaderChangedAsync(value), "切換模組載入器", Logger);
    }

    private async Task HandleLoaderChangedAsync(string loaderName)
    {
        try
        {
            if (LoaderKinds.TryParse(loaderName, out var lk))
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

    /// <summary>
    /// 套用 Minecraft 版本清單；<paramref name="keepUserSelection"/> 為 true 時，使用者手動選取且仍在清單內的版本會被保留
    /// </summary>
    private void ApplyMinecraftVersions(IEnumerable<string> versions, bool keepUserSelection)
    {
        AvailableMinecraftVersions.ReplaceAll(versions);
        if (AvailableMinecraftVersions.Contains(SelectedMinecraftVersion) && (!keepUserSelection || _isUserManuallySelectedVersion))
        {
            return;
        }

        if (keepUserSelection)
        {
            SetMinecraftVersionProgrammatically(AvailableMinecraftVersions[0]);
        }
        else
        {
            SelectedMinecraftVersion = AvailableMinecraftVersions[0];
        }
    }

    private async Task UpdateMinecraftVersionsForLoaderAsync(LoaderKind loaderKind)
    {
        try
        {
            var versions = await _loaderCatalog.GetMinecraftVersionsForLoaderAsync(loaderKind).ConfigureAwait(false);
            _ui.RunOnUi(() =>
            {
                if (versions.Count > 0)
                {
                    ApplyMinecraftVersions(versions.Select(static v => v.Version), keepUserSelection: true);
                }
            });
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "載入可用 Minecraft 版本失敗");
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
            _ = RunSafeAsync(() => UpdateJvmArgsSummaryAsync(value), "更新 JVM 參數摘要", Logger);
        }
        _ = RunSafeAsync(RefreshLoaderVersionsAsync, "重新整理載入器版本", Logger);
    }

    private async Task UpdateJvmArgsSummaryAsync(string version)
    {
        if (string.IsNullOrWhiteSpace(version))
        {
            return;
        }

        try
        {
            var lk = LoaderKinds.ParseOrDefault(SelectedLoader);
            int major = await _javaRequirementService.GetRequiredJavaMajorAsync(version, lk).ConfigureAwait(true);
            if (_customJvmArgs == null && string.Equals(SelectedMinecraftVersion, version, StringComparison.OrdinalIgnoreCase))
            {
                JvmArgsSummary = RecommendedJvmSummary(major);
            }
        }
        catch (OperationCanceledException)
        {
            Logger.Information("版本與參數設定操作已取消");
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "更新建議 JVM 參數摘要失敗: {Message}", ex.Message);
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
        string expectedName = DefaultServerName;

        if (!_isServerNameManuallyEdited)
        {
            SetServerNameProgrammatically(expectedName);
            return;
        }

        string currentName = ServerName;
        string mcVersion = SelectedMinecraftVersion;
        foreach (string loader in AvailableLoaders)
        {
            string prefix = !string.IsNullOrWhiteSpace(mcVersion) ? $"{loader} {mcVersion}" : loader;
            if (currentName.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            {
                string suffix = currentName[prefix.Length..];
                SetServerNameProgrammatically($"{SelectedLoader}{(string.IsNullOrWhiteSpace(mcVersion) ? "" : " " + mcVersion)}{suffix}");
                return;
            }
        }
    }

    private async Task InitializeVersionsAsync()
    {
        _ui.RunOnUi(() =>
        {
            IsLoadingVersions = true;
            LoadingStatusText = "正在載入可用版本清單...";
        });
        try
        {
            var loaderKind = LoaderKinds.ParseOrDefault(SelectedLoader, LoaderKind.Paper);
            var versions = await _loaderCatalog.GetMinecraftVersionsForLoaderAsync(loaderKind).ConfigureAwait(false);
            _ui.RunOnUi(() =>
            {
                if (versions.Count > 0)
                {
                    ApplyMinecraftVersions(versions.Select(static v => v.Version), keepUserSelection: true);
                }
            });
        }
        catch (OperationCanceledException)
        {
            Logger.Information("版本與參數設定操作已取消");
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "載入已安裝版本清單失敗: {Message}", ex.Message);
        }

        await RefreshLoaderVersionsAsync().ConfigureAwait(true);
        _ = RunSafeAsync(() => Task.Run(async () =>
        {
            try
            {
                await _javaRequirementService.PreloadAllJavaRequirementsAsync().ConfigureAwait(false);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Warning("背景預載 Java 需求失敗，沿用既有快取: {Message}", ex.Message);
            }
        }), "背景預載 Java 需求", Logger);
        _ui.RunOnUi(() =>
        {
            IsLoadingVersions = false;
            LoadingStatusText = string.Empty;
        });
    }

    private async Task RefreshLoaderVersionsAsync()
    {
        if (!LoaderKinds.TryParse(SelectedLoader, out var loaderKind))
        {
            _ui.RunOnUi(UpdateLoaderStateSync);
            return;
        }

        if (string.IsNullOrWhiteSpace(SelectedMinecraftVersion))
        {
            _ui.RunOnUi(UpdateLoaderStateSync);
            return;
        }

        try
        {
            var versions = await _loaderCatalog.GetLoaderVersionsAsync(loaderKind, SelectedMinecraftVersion).ConfigureAwait(false);
            _ui.RunOnUi(() =>
            {
                if (versions.Count > 0)
                {
                    LoaderVersions.ReplaceAll(versions.Select(static v => v.Version));
                    SelectedLoaderVersion = LoaderVersions[0];
                    IsLoaderVersionEnabled = loaderKind is LoaderKind.Forge or LoaderKind.NeoForge;
                }
                else
                {
                    LoaderVersions.ReplaceAll(NoAvailableVersions);
                    SelectedLoaderVersion = "無可用版本";
                    IsLoaderVersionEnabled = false;
                }
            });
        }
        catch (OperationCanceledException)
        {
            _ui.RunOnUi(UpdateLoaderStateSync);
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "重新整理模組載入器版本失敗: {Message}", ex.Message);
            _ui.RunOnUi(UpdateLoaderStateSync);
        }
    }

    private void UpdateLoaderStateSync()
    {
        LoaderVersions.ReplaceAll((string[])[$"最新穩定版 ({SelectedLoader})"]);
        SelectedLoaderVersion = LoaderVersions[0];
        IsLoaderVersionEnabled = LoaderKinds.TryParse(SelectedLoader, out var lk) &&
                                 lk is LoaderKind.Forge or LoaderKind.NeoForge;
    }

    [RelayCommand]
    public void OpenEula() => _launcher.OpenUrl(EulaUrl, isTrusted: true);

    [RelayCommand]
    public async Task OpenManageJavaAsync()
    {
        var vm = new ManageJavaViewModel(
            _javaDetector,
            _javaRequirementService,
            _javaInstaller,
            JavaPath,
            SelectedMinecraftVersion,
            SelectedLoader,
            _fileSystem,
            _ui);

        if (await _ui.ShowManageJavaAsync(vm) == true && !string.IsNullOrWhiteSpace(vm.ResultJavaPath))
        {
            JavaPath = vm.ResultJavaPath;
        }
    }

    [RelayCommand]
    public async Task ReloadMinecraftVersions()
    {
        if (IsPaperSelected)
        {
            return;
        }

        IsLoadingVersions = true;
        LoadingStatusText = "正在向網路重新整理 Minecraft 版本清單...";
        try
        {
            var lk = LoaderKinds.ParseOrDefault(SelectedLoader);
            // 命令由 UI 執行緒觸發，續延維持於 UI 執行緒以安全更新繫結屬性
            var versions = await _loaderCatalog.GetMinecraftVersionsForLoaderAsync(lk, forceReload: true).ConfigureAwait(true);
            if (versions.Count > 0)
            {
                ApplyMinecraftVersions(versions.Select(static v => v.Version), keepUserSelection: false);

                _javaRequirementService.ReloadCache();
                await UpdateJvmArgsSummaryAsync(SelectedMinecraftVersion).ConfigureAwait(true);
                Logger.Information("已手動向網路重新整理 {Loader} 的 Minecraft 版本清單，共 {Count} 個版本", SelectedLoader, versions.Count);
                await RefreshLoaderVersionsAsync().ConfigureAwait(true);
            }
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "重新整理版本清單失敗: {Message}", ex.Message);
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
            if (IsPaperSelected)
            {
                try
                {
                    var versions = await _loaderCatalog.GetPaperMinecraftVersionsAsync(forceReload: true).ConfigureAwait(false);
                    if (versions.Count > 0)
                    {
                        _ui.RunOnUi(() => ApplyMinecraftVersions(versions.Select(static v => v.Version), keepUserSelection: false));
                    }
                    _javaRequirementService.ReloadCache();
                    await UpdateJvmArgsSummaryAsync(SelectedMinecraftVersion).ConfigureAwait(true);
                    Logger.Information("已手動向網路重新整理 PaperMC 版本清單，共 {Count} 個版本", versions.Count);
                }
                catch (Exception ex)
                {
                    Logger.Warning(ex, "重新整理 PaperMC 版本清單失敗: {Message}", ex.Message);
                }
            }
            else
            {
                await _loaderCatalog.ForceReloadAllLoadersAsync().ConfigureAwait(true);
                Logger.Information("已強制向網路重新載入所有載入器版本清單");
            }
            await RefreshLoaderVersionsAsync().ConfigureAwait(true);
        }
        finally
        {
            _ui.RunOnUi(() =>
            {
                IsLoadingVersions = false;
                LoadingStatusText = string.Empty;
            });
        }
    }

    [RelayCommand]
    public async Task ConfigureJvmArgsAsync()
    {
        int maxMem = int.TryParse(MaxMemoryMb.Trim(), out int m) ? m : ServerDefaults.DefaultMemoryMaxMb;
        int? javaMajor = _javaRequirementService.GetCachedJavaMajor(SelectedMinecraftVersion);
        var vm = new JvmArgsViewModel(javaMajor, maxMem, SelectedLoader, _customJvmArgs);
        if (await _ui.ShowJvmArgsAsync(vm) == true)
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
    public async Task ResetFormAsync()
    {
        if (!await _ui.ConfirmAsync("確定要重設建立伺服器表單的所有欄位內容嗎？", "確認重設表單"))
        {
            return;
        }

        SelectedLoader = "Paper";
        IsMinecraftVersionReloadEnabled = false;
        SelectedMinecraftVersion = AvailableMinecraftVersions.Count > 0 ? AvailableMinecraftVersions[0] : string.Empty;
        SelectedLoaderVersion = $"最新穩定版 ({SelectedLoader})";
        ServerName = DefaultServerName;
        MinMemoryMb = ServerDefaults.DefaultMemoryMinMb.ToString(System.Globalization.CultureInfo.InvariantCulture);
        MaxMemoryMb = ServerDefaults.DefaultMemoryMaxMb.ToString(System.Globalization.CultureInfo.InvariantCulture);
        JavaPath = string.Empty;
        _customJvmArgs = null;
        int? javaMajor = _javaRequirementService.GetCachedJavaMajor(SelectedMinecraftVersion);
        JvmArgsSummary = RecommendedJvmSummary(javaMajor);
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
            _ui.Notify("伺服器名稱不能為空", NotificationType.Warning);
            return;
        }

        if (IsMemoryError)
        {
            _ui.Notify($"記憶體設定無效：{MemoryWarningText}", NotificationType.Warning);
            return;
        }

        IsCreating = true;
        try
        {
            var lk = LoaderKinds.ParseOrDefault(SelectedLoader);
            int? targetMajor = _javaRequirementService.GetCachedJavaMajor(SelectedMinecraftVersion, lk);

            string effectiveJavaPath = JavaPath?.Trim() ?? string.Empty;
            if (targetMajor.HasValue)
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
                        await _ui.ShowErrorAsync($"建立伺服器已終止！\n\nMinecraft {SelectedMinecraftVersion} 強制需要 Java {targetMajor.Value}，但系統偵測不到相容的 Java 執行檔。\n請點選「管理 Java」安裝或設定 Java {targetMajor.Value} 後再建立伺服器。",
                            "Java 版本不相符");
                        return;
                    }
                }
            }

            if (string.IsNullOrWhiteSpace(effectiveJavaPath))
            {
                _ui.Notify("未設定合適的 Java 執行檔路徑，請點選「管理 Java」指定或安裝", NotificationType.Warning);
                return;
            }

            int minMem = int.TryParse(MinMemoryMb.Trim(), out int min) ? min : ServerDefaults.DefaultMemoryMinMb;
            int maxMem = int.TryParse(MaxMemoryMb.Trim(), out int max) ? max : ServerDefaults.DefaultMemoryMaxMb;

            string loaderVer = SelectedLoaderVersion;
            if (loaderVer is "無" or "無可用版本")
            {
                loaderVer = string.Empty;
            }

            var plan = ServerCreationPlan.Create(
                name: Domain.ValueObjects.ServerName.Parse(ServerName.Trim()),
                minecraftVersion: Domain.ValueObjects.MinecraftVersion.Parse(SelectedMinecraftVersion),
                loaderType: lk,
                loaderVersion: loaderVer,
                memoryMaxMb: maxMem,
                memoryMinMb: minMem,
                jvmArgs: _customJvmArgs,
                userJavaPath: effectiveJavaPath);

            Logger.Information("開始建立伺服器: {Name}, 版本: {Version}, 載入器: {Loader}, 記憶體: {Min}M-{Max}M, Java: {Java}",
                plan.Config.Name.Value, plan.Config.MinecraftVersion.Value, plan.Config.LoaderType, plan.Config.MemoryMinMb, plan.Config.MemoryMaxMb, effectiveJavaPath);

            ServerCreationResult created;
            using (var progressDialog = _ui.ShowServerCreationProgress(plan.Config.Name.Value))
            {
                created = await _serverManager.CreateServerAsync(plan, progressDialog.Progress);
            }

            if (created.Completed && created.Config is not null)
            {
                Logger.Information("伺服器檔案與腳本已建立完成: {Name}，路徑: {Path}，即將執行初次啟動初始化", created.Config.Name.Value, created.Config.Path);

                bool initSuccess;
                using (var initVm = new ServerInitializationViewModel(_serverRuntime, _launchPlanner, created.Config, effectiveJavaPath, _ui))
                {
                    initSuccess = await _ui.ShowServerInitializationAsync(initVm);
                }

                _ui.ActivateMainWindow();

                if (initSuccess)
                {
                    Logger.Information("伺服器建立成功: {Name}，路徑: {Path}", created.Config.Name.Value, created.Config.Path);
                    _ui.Notify($"伺服器「{created.Config.Name.Value}」已成功建立並完成初始化！", NotificationType.Success);
                    _navigateCallback("manage", created.Config.Name.Value);
                }
                else
                {
                    Logger.Warning("伺服器「{Name}」初次初始化未完成或已被中斷", created.Config.Name.Value);
                    _ui.ShowNotification(
                        $"伺服器「{created.Config.Name.Value}」初次啟動初始化已被強制中斷。\n\n伺服器檔案已完整保留，您稍後可於「管理伺服器」頁面手動啟動伺服器繼續完成世界生成與設定。",
                        "伺服器初始化已中斷",
                        NotificationType.Warning);
                    _navigateCallback("manage", created.Config.Name.Value);
                }
            }
            else
            {
                Logger.Warning("伺服器建立失敗: {Message}", created.Message);
                await _ui.ShowErrorAsync($"建立伺服器失敗：\n{created.Message}", "建立伺服器被拒絕");
            }
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "建立伺服器時發生例外: {Message}", ex.Message);
            await _ui.ShowErrorAsync($"建立伺服器時發生錯誤：\n{ex.Message}", "建立伺服器失敗");
        }
        finally
        {
            IsCreating = false;
        }
    }

    /// <summary>
    /// 依載入器與版本產生的預設伺服器名稱（使用者未手動編輯時同步）
    /// </summary>
    private string DefaultServerName => string.IsNullOrWhiteSpace(SelectedMinecraftVersion) ? SelectedLoader : $"{SelectedLoader} {SelectedMinecraftVersion}";

    private bool IsPaperSelected => LoaderKinds.ParseOrDefault(SelectedLoader) == LoaderKind.Paper;

    /// <summary>
    /// 依 Java 主版本提示系統建議 GC（未知或 21 以上採 ZGC）
    /// </summary>
    private static string RecommendedJvmSummary(int? javaMajor) =>
        javaMajor is null or >= 21 ? "使用系統建議 JVM 參數 (ZGC)" : "使用系統建議 JVM 參數 (G1GC)";

    private void UpdateMemoryWarning()
    {
        var check = Core.Utilities.MemoryUtils.CheckServerMemory(MaxMemoryMb, MinMemoryMb, _systemMemoryMb);
        MemoryWarningText = check.Level == Core.Utilities.MemoryCheckLevel.Ok ? string.Empty : $"⚠️ 警告：{check.Message}";
        IsMemoryError = check.Level == Core.Utilities.MemoryCheckLevel.Error;
    }
}
