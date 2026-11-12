using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Mods;
using MinecraftServerManager.Infrastructure.Servers;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.UnitTests.UI;

/// <summary>測試用相依集合工廠：核心服務使用真實輕量實作（限定於暫存目錄），網路與外部行程類服務使用不做事替身</summary>
internal static class TestDependencies
{
    public static PageServices Create(
        string root,
        IUiService? uiService = null,
        IExternalLauncher? launcher = null,
        SettingsManager? settings = null,
        IServerRuntimeHost? runtimeHost = null,
        IRunningServerRegistry? runningServerRegistry = null,
        IJavaRuntimeDetector? javaDetector = null,
        IMinecraftJavaRequirementService? javaRequirementService = null)
    {
        Directory.CreateDirectory(root);
        var inspector = new ServerInspector();
        var settingsManager = settings ?? new SettingsManager(root);
        var backupService = new ServerBackupService(root, static () => 10);
        var propertiesStore = new ServerPropertiesStore(root);
        var host = runtimeHost ?? new FakeServerRuntimeHost();
        var ui = uiService ?? NoOpUiService.Instance;
        return new PageServices(
            SettingsManager: settingsManager,
            ServerManager: TestServerManagers.Create(root, inspector),
            BackupService: backupService,
            RuntimeHost: host,
            StopCoordinator: new ServerStopCoordinator(ui, host),
            StartPreflight: new ServerStartPreflight(ui, settingsManager, backupService, propertiesStore, host),
            RunningServerRegistry: runningServerRegistry ?? NoOp.Create<IRunningServerRegistry>(),
            ServerInspector: inspector,
            LaunchPlanner: new ServerLaunchPlanner(),
            PropertiesStore: propertiesStore,
            PlayerConfigStore: new ServerPlayerConfigStore(),
            DirectorySizeService: new ServerDirectorySizeService(TimeSpan.FromSeconds(60)),
            IntegrityService: new ServerIntegrityService(),
            DependencyPlanner: new ModDependencyPlanner(),
            ModListExporter: new ModListExporter(),
            FileSystem: new LocalFileSystem(),
            LogReader: new ServerLogReader(),
            ModFileService: new ModFileService(),
            ServersRootService: new ServersRootService(),
            UiService: ui,
            JavaDetector: javaDetector ?? new FixedJavaRuntimeDetector(),
            LoaderCatalog: NoOp.Create<ILoaderCatalogService>(),
            ModManager: NoOp.Create<IModManager>(),
            ModrinthClient: NoOp.Create<IModrinthClient>(),
            UpdateChecker: NoOp.Create<IUpdateCheckerService>(),
            Launcher: launcher ?? new RecordingLauncher(),
            JavaRequirementService: javaRequirementService ?? new FixedJavaRequirementService(),
            JavaInstaller: NoOp.Create<IJavaInstaller>(),
            AppUpdateService: NoOp.Create<IAppUpdateService>());
    }

    /// <summary>以相依集合組裝「管理現有伺服器」頁面</summary>
    public static ManageServerViewModel CreateManagePage(PageServices services, Action<string>? navigate = null) =>
        new PageViewModelFactory(services).CreateManagePage(navigate ?? (static _ => { }));

    /// <summary>以相依集合組裝主視窗 ViewModel</summary>
    public static MainViewModel CreateMainViewModel(PageServices services) => new(
        services.UiService,
        services.SettingsManager,
        services.UpdateChecker,
        services.Launcher,
        services.FileSystem,
        services.RunningServerRegistry,
        new PageViewModelFactory(services));
}
