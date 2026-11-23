using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Mods;
using MinecraftServerManager.Infrastructure.Servers;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.UnitTests.TestSupport;

internal static class TestDependencies
{
    /// <summary>建立以 <paramref name="root"/> 為固定伺服器根目錄的設定</summary>
    public static SettingsManager CreateSettings(string root)
    {
        var settings = new SettingsManager(root);
        settings.SetExactServersRoot(root);
        return settings;
    }

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
        var backupService = new ServerBackupService(root, static () => 10, TimeProvider.System);
        var propertiesStore = new ServerPropertiesStore(root);
        var host = runtimeHost ?? new FakeServerRuntimeHost();
        var ui = uiService ?? NoOpUiService.Instance;
        var modrinthClient = NoOp.Create<IModrinthClient>();
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
            DirectorySizeService: new ServerDirectorySizeService(TimeSpan.FromSeconds(60), TimeProvider.System),
            IntegrityService: new ServerIntegrityService(),
            DependencyPlanner: new ModDependencyPlanner(modrinthClient),
            ModListExporter: new ModListExporter(),
            FileSystem: new LocalFileSystem(),
            LogReader: new ServerLogReader(),
            ModFileService: new ModFileService(),
            ServersRootService: new ServersRootService(),
            UiService: ui,
            JavaDetector: javaDetector ?? new FixedJavaRuntimeDetector(),
            LoaderCatalog: NoOp.Create<ILoaderCatalogService>(),
            ModManager: NoOp.Create<IModManager>(),
            ModrinthClient: modrinthClient,
            UpdateChecker: NoOp.Create<IUpdateCheckerService>(),
            Launcher: launcher ?? new RecordingLauncher(),
            JavaRequirementService: javaRequirementService ?? new FixedJavaRequirementService(),
            JavaInstaller: NoOp.Create<IJavaInstaller>(),
            AppUpdateService: NoOp.Create<IAppUpdateService>(),
            AccentColorService: NoOp.Create<IAccentColorService>());
    }

    public static ManageServerViewModel CreateManagePage(PageServices services, Action<string>? navigate = null) =>
        new PageViewModelFactory(services).CreateManagePage(navigate ?? (static _ => { }));

    public static MainViewModel CreateMainViewModel(PageServices services) => new(
        services.UiService,
        services.SettingsManager,
        services.Launcher,
        services.FileSystem,
        services.RunningServerRegistry,
        new PageViewModelFactory(services));
}
