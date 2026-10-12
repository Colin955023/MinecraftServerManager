using System.IO;
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
public sealed class AppCompositionRoot : IAsyncDisposable, IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("AppCompositionRoot");

    private readonly SocketsHttpHandler _httpHandler;
    private readonly HttpClient _sharedHttpClient;
    private readonly ProcessRunner _sharedProcessRunner;
    private readonly ServerRuntime _sharedServerRuntime;
    private readonly SettingsManager _settingsManager;
    private readonly JavaRuntimeDetector _javaDetector;
    private readonly MinecraftJavaRequirementService _javaRequirements;
    private readonly LoaderCatalogService _loaderCatalog;
    private readonly UpdateCheckerService? _updateCheckerService;
    private readonly MainViewModel _mainViewModel;

    public MainViewModel MainViewModel => _mainViewModel;
    public SettingsManager Settings => _settingsManager;
    public ServerRuntime ServerRuntime => _sharedServerRuntime;

    public AppCompositionRoot() : this(ResolveInitialServersRoot(new SettingsManager()))
    {
    }

    public AppCompositionRoot(string serversRoot, SettingsManager? settingsManager = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serversRoot);

        _httpHandler = new SocketsHttpHandler
        {
            PooledConnectionLifetime = TimeSpan.FromMinutes(5),
            AutomaticDecompression = DecompressionMethods.All,
            AllowAutoRedirect = false,
        };
        _sharedHttpClient = new HttpClient(_httpHandler, disposeHandler: false);
        _sharedProcessRunner = new ProcessRunner();
        _sharedServerRuntime = new ServerRuntime(_sharedProcessRunner);
        _settingsManager = settingsManager ?? new SettingsManager();

        _javaDetector = new JavaRuntimeDetector(_sharedProcessRunner);
        var javaInstaller = new JavaWingetInstaller(_sharedProcessRunner);
        var httpPort = new HttpDownloadClient(_sharedHttpClient);
        _javaRequirements = new MinecraftJavaRequirementService(httpPort, RuntimePaths.GetVersionCacheDir());
        _loaderCatalog = new LoaderCatalogService(httpPort, RuntimePaths.GetVersionCacheDir());
        var loaderInstaller = new LoaderInstallerService(httpPort, _sharedProcessRunner, RuntimePaths.GetInstallerCacheDir());
        var serverManager = new ServerManager(
            serversRoot,
            loaderInstaller: loaderInstaller,
            javaDetector: _javaDetector,
            javaRequirementService: _javaRequirements);
        var backupService = new ServerBackupService(serversRoot);

        var modScanner = new LocalModScanner();
        var modInstaller = new ModFileInstaller(httpPort);
        var modManager = new ModManager(modScanner, modInstaller);
        var modrinthClient = new ModrinthClient(httpPort);
        _updateCheckerService = new UpdateCheckerService(httpPort);

        _mainViewModel = new MainViewModel(
            _settingsManager,
            _javaDetector,
            serverManager,
            backupService,
            _sharedServerRuntime,
            _loaderCatalog,
            modManager,
            modrinthClient,
            _updateCheckerService,
            _sharedProcessRunner,
            _javaRequirements,
            javaInstaller);
    }

    private static string ResolveInitialServersRoot(SettingsManager settings)
    {
        string configured = settings.GetServersRoot();
        if (string.IsNullOrWhiteSpace(configured))
        {
            return Path.Combine(RuntimePaths.GetUserDataDir(), "servers");
        }

        try
        {
            return settings.GetValidatedServersRootPath(create: true);
        }
        catch
        {
            return Path.Combine(RuntimePaths.GetUserDataDir(), "servers");
        }
    }

    /// <summary>
    /// 啟動背景非同步預熱任務（Java 探測、版本需求、載入器目錄與 Paper 版本清單）
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
        var reqTask = _javaRequirements.PreloadAllJavaRequirementsAsync();
        var mcTask = _loaderCatalog.GetMinecraftVersionsAsync();
        var paperTask = _loaderCatalog.GetPaperMinecraftVersionsAsync();
        var loadersTask = _loaderCatalog.ForceReloadAllLoadersAsync();

        await Task.WhenAll(detectTask, reqTask, mcTask, paperTask, loadersTask).ConfigureAwait(false);
        Logger.Information("啟動背景預熱完成 (Java 候選、官方與 Paper Java 需求、Minecraft 版本與各載入器清單)");
    }

    public void Dispose()
    {
        try
        {
            _sharedServerRuntime.DisposeAsync().AsTask().GetAwaiter().GetResult();
        }
        catch
        {
            // 忽略同步處置逾時或例外
        }

        _sharedHttpClient.Dispose();
        _httpHandler.Dispose();
    }

    public async ValueTask DisposeAsync()
    {
        _sharedHttpClient.Dispose();
        _httpHandler.Dispose();
        await _sharedServerRuntime.DisposeAsync().ConfigureAwait(false);
    }
}
