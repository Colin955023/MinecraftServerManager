using System.Net;
using System.Net.Http;
using MinecraftServerManager.App.ViewModels;
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

/// <summary>
/// 應用程式組合根（Composition Root）：負責相依性注入、服務生命週期管理與背景預熱
/// </summary>
public sealed class AppCompositionRoot : IAsyncDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("AppCompositionRoot");

    private readonly SocketsHttpHandler _httpHandler;
    private readonly HttpClient _sharedHttpClient;
    private readonly ProcessRunner _sharedProcessRunner;
    private readonly ServerRuntime _sharedServerRuntime;
    private readonly SettingsManager _settingsManager;
    private readonly JavaRuntimeDetector _javaDetector;
    private readonly LoaderCatalogService _loaderCatalog;
    private readonly MainViewModel _mainViewModel;
    private readonly Services.WpfUiService _uiService;

    public MainViewModel MainViewModel => _mainViewModel;
    public Services.IUiService UiService => _uiService;
    public SettingsManager Settings => _settingsManager;
    public bool IsServerRunning => _sharedServerRuntime.IsRunning;
    public MainViewModelDependencies Dependencies { get; }

    public AppCompositionRoot(string serversRoot, SettingsManager? settingsManager = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serversRoot);

        _httpHandler = new SocketsHttpHandler
        {
            PooledConnectionLifetime = TimeSpan.FromMinutes(5),
            AutomaticDecompression = DecompressionMethods.All,
            AllowAutoRedirect = false,
            ConnectCallback = HttpUrlPolicy.ConnectAsync,
        };
        _sharedHttpClient = new HttpClient(_httpHandler, disposeHandler: false);
        _sharedProcessRunner = new ProcessRunner();
        _sharedServerRuntime = new ServerRuntime(_sharedProcessRunner);
        _settingsManager = settingsManager ?? new SettingsManager();

        _javaDetector = new JavaRuntimeDetector(_sharedProcessRunner);
        var javaInstaller = new JavaWingetInstaller(_sharedProcessRunner);
        var httpPort = new HttpDownloadClient(_sharedHttpClient);
        var javaRequirements = new MinecraftJavaRequirementService(httpPort, RuntimePaths.GetVersionCacheDir());
        _loaderCatalog = new LoaderCatalogService(httpPort, RuntimePaths.GetVersionCacheDir());
        var loaderInstaller = new LoaderInstallerService(httpPort, _sharedProcessRunner, RuntimePaths.GetInstallerCacheDir());
        var directorySizeService = new ServerDirectorySizeService();
        var serverInspector = new ServerInspector(directorySizeService);
        var serverManager = new ServerManager(
            serversRoot,
            inspector: serverInspector,
            loaderInstaller: loaderInstaller,
            javaDetector: _javaDetector,
            javaRequirementService: javaRequirements);
        var backupService = new ServerBackupService(serversRoot);
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
        var appUpdateService = new AppUpdateService(httpPort, processRunner: _sharedProcessRunner);

        _uiService = new Services.WpfUiService();

        var dependencies = new MainViewModelDependencies(
            SettingsManager: _settingsManager,
            JavaDetector: _javaDetector,
            ServerManager: serverManager,
            BackupService: backupService,
            ServerRuntime: _sharedServerRuntime,
            LoaderCatalog: _loaderCatalog,
            ModManager: modManager,
            ModrinthClient: modrinthClient,
            UpdateChecker: updateCheckerService,
            Launcher: _sharedProcessRunner,
            JavaRequirementService: javaRequirements,
            JavaInstaller: javaInstaller,
            UiService: _uiService,
            AppUpdateService: appUpdateService,
            DependencyPlanner: dependencyPlanner,
            ModListExporter: modListExporter,
            DirectorySizeService: directorySizeService,
            IntegrityService: integrityService,
            ServerInspector: serverInspector,
            LaunchPlanner: launchPlanner,
            PlayerConfigStore: playerConfigStore,
            PropertiesStore: propertiesStore);

        _mainViewModel = new MainViewModel(dependencies);
        Dependencies = dependencies;
    }

    /// <summary>
    /// 啟動背景非同步預熱任務（Java 探測與載入器目錄清單）
    /// </summary>
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
                Logger.Warning("背景預熱過程發生部分異常: {Message}", ex.Message);
            }
        });
    }

    /// <summary>
    /// 執行預熱作業
    /// </summary>
    public async Task WarmupAsync()
    {
        var detectTask = _javaDetector.DetectAsync();
        var loadersTask = _loaderCatalog.WarmupLoadersAsync();

        await Task.WhenAll(detectTask, loadersTask).ConfigureAwait(false);
        Logger.Information("啟動背景預熱完成 (Java 候選與各載入器清單)");
    }

    public async ValueTask DisposeAsync()
    {
        _mainViewModel.DisposePages();
        _sharedHttpClient.Dispose();
        _httpHandler.Dispose();
        await _sharedServerRuntime.DisposeAsync().ConfigureAwait(false);
    }
}
