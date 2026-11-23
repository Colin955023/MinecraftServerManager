using System.Net;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
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

/// <summary>組合根：相依性注入、服務生命週期與背景預熱</summary>
public sealed class AppCompositionRoot : IAsyncDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(AppCompositionRoot));

    private readonly SocketsHttpHandler _httpHandler;
    private readonly HttpClient _sharedHttpClient;
    private readonly ProcessRunner _sharedProcessRunner;
    private readonly ServerRuntimeHost _runtimeHost;
    private readonly ServerStopCoordinator _stopCoordinator;
    private readonly ServerManager _serverManager;
    private readonly ISettingsManager _settingsManager;
    private readonly JavaRuntimeDetector _javaDetector;
    private readonly LoaderCatalogService _loaderCatalog;
    private readonly AppUpdateService _appUpdateService;
    private readonly MainViewModel _mainViewModel;
    private readonly CancellationTokenSource _warmupCts = new();
    private readonly Lock _warmupLock = new();
    private Task? _warmupTask;
    private int _disposed;

    public MainViewModel MainViewModel => _mainViewModel;
    public bool IsServerRunning => _runtimeHost.IsAnyRunning;

    /// <summary>結束程式前確認並平順停止全部執行中的伺服器；使用者取消回傳 false</summary>
    public Task<bool> StopAllServersForShutdownAsync() => _stopCoordinator.StopAllForShutdownAsync();

    public AppCompositionRoot(string serversRoot, IUiService uiService, ISettingsManager settingsManager, ProcessRunner processRunner, IExternalLauncher launcher, IAccentColorService accentColorService)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serversRoot);
        ArgumentNullException.ThrowIfNull(uiService);
        ArgumentNullException.ThrowIfNull(settingsManager);
        ArgumentNullException.ThrowIfNull(processRunner);
        ArgumentNullException.ThrowIfNull(launcher);
        ArgumentNullException.ThrowIfNull(accentColorService);

        _httpHandler = new SocketsHttpHandler
        {
            PooledConnectionLifetime = TimeSpan.FromMinutes(5),
            ConnectTimeout = TimeSpan.FromSeconds(20),
            AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate,
            AllowAutoRedirect = false,
            // 自訂 ConnectCallback 直連目標並逐一檢查解析後位址；經代理時檢查的會是代理而非目標，故停用系統代理
            UseProxy = false,
            ConnectCallback = HttpUrlPolicy.ConnectAsync,
        };
        _sharedHttpClient = new HttpClient(_httpHandler, disposeHandler: false);
        _sharedProcessRunner = processRunner;
        var runningServerRegistry = new RunningServerRegistry(RuntimePaths.GetUserDataDir(), _sharedProcessRunner);
        _runtimeHost = new ServerRuntimeHost(_sharedProcessRunner, runningServerRegistry);
        _stopCoordinator = new ServerStopCoordinator(uiService, _runtimeHost);
        _settingsManager = settingsManager;

        _javaDetector = new JavaRuntimeDetector(_sharedProcessRunner, JavaSearchSources.FromCurrentEnvironment());
        var javaInstaller = new JavaWingetInstaller(_sharedProcessRunner);
        var httpPort = new HttpDownloadClient(_sharedHttpClient, TimeProvider.System);
        var javaRequirements = new MinecraftJavaRequirementService(httpPort, RuntimePaths.GetVersionCacheDir());
        _loaderCatalog = new LoaderCatalogService(httpPort, RuntimePaths.GetVersionCacheDir(), TimeProvider.System);
        var loaderInstaller = new LoaderInstallerService(httpPort, _sharedProcessRunner, RuntimePaths.GetInstallerCacheDir(), RuntimePaths.GetVersionCacheDir(), TimeProvider.System);
        var directorySizeService = new ServerDirectorySizeService(TimeSpan.FromSeconds(60), TimeProvider.System);
        var serverInspector = new ServerInspector();
        _serverManager = new ServerManager(
            serversRoot,
            inspector: serverInspector,
            loaderInstaller: loaderInstaller,
            javaDetector: _javaDetector,
            javaRequirementService: javaRequirements);
        var backupService = new ServerBackupService(serversRoot, _settingsManager.GetBackupRetentionCount, TimeProvider.System);
        var integrityService = new ServerIntegrityService();
        var launchPlanner = new ServerLaunchPlanner();
        var playerConfigStore = new ServerPlayerConfigStore();
        var propertiesStore = new ServerPropertiesStore(serversRoot);

        var modScanner = new LocalModScanner();
        var modInstaller = new ModFileInstaller(httpPort);
        var modManager = new ModManager(modScanner, modInstaller);
        var modrinthClient = new ModrinthClient(httpPort);
        var dependencyPlanner = new ModDependencyPlanner(modrinthClient);
        var modListExporter = new ModListExporter();
        var updateCheckerService = new UpdateCheckerService(httpPort);
        _appUpdateService = new AppUpdateService(httpPort, Path.Combine(RuntimePaths.GetUserDataDir(), "updates"), _sharedProcessRunner);

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
            Launcher: launcher,
            JavaRequirementService: javaRequirements,
            JavaInstaller: javaInstaller,
            UiService: uiService,
            AppUpdateService: _appUpdateService,
            AccentColorService: accentColorService,
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

        _mainViewModel = new MainViewModel(uiService, _settingsManager, launcher, services.FileSystem, runningServerRegistry, new PageViewModelFactory(services));
    }

    /// <summary>啟動背景非同步預熱任務（Java 偵測與載入器目錄清單）；處置時取消</summary>
    public void StartBackgroundWarmup() => StartBackgroundWarmup(WarmupAsync);

    internal void StartBackgroundWarmup(Func<CancellationToken, Task> warmup)
    {
        ArgumentNullException.ThrowIfNull(warmup);

        lock (_warmupLock)
        {
            if (Volatile.Read(ref _disposed) != 0 || _warmupTask is not null)
            {
                return;
            }

            CancellationToken token = _warmupCts.Token;
            _warmupTask = Task.Run(async () =>
            {
                try
                {
                    await warmup(token).ConfigureAwait(false);
                }
                catch (OperationCanceledException) when (token.IsCancellationRequested)
                {
                    Logger.Information("背景預熱已因程式關閉取消");
                }
                catch (Exception ex)
                {
                    Logger.Warning(ex, "背景預熱過程部分失敗");
                }
            });
        }
    }

    /// <summary>執行預熱作業</summary>
    private async Task WarmupAsync(CancellationToken cancellationToken)
    {
        RuntimePaths.CleanupStaleSingleFileExtractDirectories();
        _appUpdateService.CleanupPreviousUpdateBackup();
        var detectTask = _javaDetector.DetectAsync(cancellationToken: cancellationToken);
        var loadersTask = _loaderCatalog.WarmupLoadersAsync(cancellationToken);

        // 讀取伺服器清單，使墓碑復原於背景提早完成
        var serversTask = _serverManager.GetAllServersAsync(cancellationToken);

        await Task.WhenAll(detectTask, loadersTask, serversTask).ConfigureAwait(false);
        Logger.Information("啟動背景預熱完成（Java 候選與各載入器清單）");
    }

    /// <summary>冪等處置：先取消預熱，再處置頁面、HTTP 與伺服器執行主機</summary>
    public async ValueTask DisposeAsync()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0)
        {
            return;
        }

        await _warmupCts.CancelAsync();
        Task? warmupTask;
        lock (_warmupLock)
        {
            warmupTask = _warmupTask;
        }

        if (warmupTask is not null)
        {
            await warmupTask.ConfigureAwait(false);
        }

        await _mainViewModel.DisposePagesAsync();
        _sharedHttpClient.Dispose();
        _httpHandler.Dispose();
        await _runtimeHost.DisposeAsync().ConfigureAwait(false);
        _warmupCts.Dispose();
    }
}
