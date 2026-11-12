using System.Net;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Http;
using MinecraftServerManager.Infrastructure.Java;
using MinecraftServerManager.Infrastructure.Loaders;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Mods;
using MinecraftServerManager.Infrastructure.Process;
using MinecraftServerManager.Infrastructure.Servers;
using MinecraftServerManager.Infrastructure.Services;
using MinecraftServerManager.Infrastructure.Settings;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.App;

/// <summary>應用程式組合根（Composition Root）：負責相依性注入、服務生命週期管理與背景預熱</summary>
public sealed class AppCompositionRoot : IAsyncDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(AppCompositionRoot));

    private readonly SocketsHttpHandler _httpHandler;
    private readonly HttpClient _sharedHttpClient;
    private readonly ProcessRunner _sharedProcessRunner;
    private readonly ServerRuntimeHost _runtimeHost;
    private readonly ServerStopCoordinator _stopCoordinator;
    private readonly ServerManager _serverManager;
    private readonly SettingsManager _settingsManager;
    private readonly JavaRuntimeDetector _javaDetector;
    private readonly LoaderCatalogService _loaderCatalog;
    private readonly MainViewModel _mainViewModel;

    public MainViewModel MainViewModel => _mainViewModel;
    public bool IsServerRunning => _runtimeHost.IsAnyRunning;

    /// <summary>結束程式前確認並平順停止全部執行中的伺服器；使用者取消回傳 false</summary>
    public Task<bool> StopAllServersForShutdownAsync() => _stopCoordinator.StopAllForShutdownAsync();

    public AppCompositionRoot(string serversRoot, IUiService uiService, SettingsManager settingsManager, ProcessRunner processRunner)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serversRoot);
        ArgumentNullException.ThrowIfNull(uiService);
        ArgumentNullException.ThrowIfNull(settingsManager);
        ArgumentNullException.ThrowIfNull(processRunner);

        _httpHandler = new SocketsHttpHandler
        {
            PooledConnectionLifetime = TimeSpan.FromMinutes(5),
            ConnectTimeout = TimeSpan.FromSeconds(20),
            AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate,
            AllowAutoRedirect = false,
            ConnectCallback = HttpUrlPolicy.ConnectAsync,
        };
        _sharedHttpClient = new HttpClient(_httpHandler, disposeHandler: false);
        _sharedProcessRunner = processRunner;
        var runningServerRegistry = new RunningServerRegistry(RuntimePaths.GetUserDataDir(), _sharedProcessRunner);
        _runtimeHost = new ServerRuntimeHost(_sharedProcessRunner, runningServerRegistry);
        _stopCoordinator = new ServerStopCoordinator(uiService, _runtimeHost);
        _settingsManager = settingsManager;

        _javaDetector = new JavaRuntimeDetector(_sharedProcessRunner);
        var javaInstaller = new JavaWingetInstaller(_sharedProcessRunner);
        var httpPort = new HttpDownloadClient(_sharedHttpClient);
        var javaRequirements = new MinecraftJavaRequirementService(httpPort, RuntimePaths.GetVersionCacheDir());
        _loaderCatalog = new LoaderCatalogService(httpPort, RuntimePaths.GetVersionCacheDir());
        var loaderInstaller = new LoaderInstallerService(httpPort, _sharedProcessRunner, RuntimePaths.GetInstallerCacheDir());
        var directorySizeService = new ServerDirectorySizeService(TimeSpan.FromSeconds(60));
        var serverInspector = new ServerInspector();
        _serverManager = new ServerManager(
            serversRoot,
            inspector: serverInspector,
            loaderInstaller: loaderInstaller,
            javaDetector: _javaDetector,
            javaRequirementService: javaRequirements);
        var backupService = new ServerBackupService(serversRoot, _settingsManager.GetBackupRetentionCount);
        var integrityService = new ServerIntegrityService();
        var launchPlanner = new ServerLaunchPlanner();
        var playerConfigStore = new ServerPlayerConfigStore();
        var propertiesStore = new ServerPropertiesStore(serversRoot);

        var modScanner = new LocalModScanner();
        var modInstaller = new ModFileInstaller(httpPort);
        var modManager = new ModManager(modScanner, modInstaller);
        var modrinthClient = new ModrinthClient(httpPort);
        var dependencyPlanner = new ModDependencyPlanner();
        var modListExporter = new ModListExporter();
        var updateCheckerService = new UpdateCheckerService(httpPort);
        var appUpdateService = new AppUpdateService(httpPort, Path.Combine(RuntimePaths.GetUserDataDir(), "updates"), _sharedProcessRunner);

        var services = new PageServices(
            SettingsManager: _settingsManager,
            JavaDetector: _javaDetector,
            ServerManager: _serverManager,
            BackupService: backupService,
            RuntimeHost: _runtimeHost,
            StopCoordinator: _stopCoordinator,
            StartPreflight: new ServerStartPreflight(uiService, _settingsManager, backupService, propertiesStore, _runtimeHost),
            RunningServerRegistry: runningServerRegistry,
            LoaderCatalog: _loaderCatalog,
            ModManager: modManager,
            ModrinthClient: modrinthClient,
            UpdateChecker: updateCheckerService,
            Launcher: _sharedProcessRunner,
            JavaRequirementService: javaRequirements,
            JavaInstaller: javaInstaller,
            UiService: uiService,
            AppUpdateService: appUpdateService,
            DependencyPlanner: dependencyPlanner,
            ModListExporter: modListExporter,
            FileSystem: new LocalFileSystem(),
            LogReader: new ServerLogReader(),
            ModFileService: new ModFileService(),
            ServersRootService: new ServersRootService(),
            DirectorySizeService: directorySizeService,
            IntegrityService: integrityService,
            ServerInspector: serverInspector,
            LaunchPlanner: launchPlanner,
            PlayerConfigStore: playerConfigStore,
            PropertiesStore: propertiesStore);

        AccentColorService.ApplyAccentColor(_settingsManager.GetCustomAccentColor());
        _mainViewModel = new MainViewModel(uiService, _settingsManager, updateCheckerService, _sharedProcessRunner, services.FileSystem, runningServerRegistry, new PageViewModelFactory(services));
    }

    /// <summary>啟動背景非同步預熱任務（Java 探測與載入器目錄清單）</summary>
    public void StartBackgroundWarmup()
    {
        _ = Task.Run(async () =>
        {
            try
            {
                await WarmupAsync().ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                Logger.Warning(ex, "背景預熱過程部分失敗");
            }
        });
    }

    /// <summary>執行預熱作業</summary>
    public async Task WarmupAsync()
    {
        RuntimePaths.CleanupStaleSingleFileExtractDirectories();
        var detectTask = _javaDetector.DetectAsync();
        var loadersTask = _loaderCatalog.WarmupLoadersAsync();

        // 讀取伺服器清單，使墓碑復原於背景提早完成
        var serversTask = _serverManager.GetAllServersAsync();

        await Task.WhenAll(detectTask, loadersTask, serversTask).ConfigureAwait(false);
        Logger.Information("啟動背景預熱完成 (Java 候選與各載入器清單)");
    }

    public async ValueTask DisposeAsync()
    {
        _mainViewModel.DisposePages();
        _sharedHttpClient.Dispose();
        _httpHandler.Dispose();
        await _runtimeHost.DisposeAsync().ConfigureAwait(false);
    }
}
