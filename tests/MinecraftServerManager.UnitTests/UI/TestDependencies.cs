using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Mods;
using MinecraftServerManager.Infrastructure.Servers;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.UnitTests.UI;

/// <summary>
/// 測試用相依集合工廠：核心服務使用真實輕量實作（限定於暫存目錄），網路與外部行程類服務使用不做事替身
/// </summary>
internal static class TestDependencies
{
    public static MainViewModelDependencies Create(
        string root,
        IUiService? uiService = null,
        IExternalLauncher? launcher = null,
        SettingsManager? settings = null,
        IServerRuntime? runtime = null)
    {
        Directory.CreateDirectory(root);
        var inspector = new ServerInspector();
        return new MainViewModelDependencies(
            SettingsManager: settings ?? new SettingsManager(root),
            ServerManager: TestServerManagers.Create(root, inspector),
            BackupService: new ServerBackupService(root),
            ServerRuntime: runtime ?? new FakeServerRuntime(),
            ServerInspector: inspector,
            LaunchPlanner: new ServerLaunchPlanner(),
            PropertiesStore: new ServerPropertiesStore(root),
            PlayerConfigStore: new ServerPlayerConfigStore(),
            DirectorySizeService: new ServerDirectorySizeService(TimeSpan.FromSeconds(60)),
            IntegrityService: new ServerIntegrityService(),
            DependencyPlanner: new ModDependencyPlanner(),
            ModListExporter: new ModListExporter(),
            FileSystem: new LocalFileSystem(),
            LogReader: new ServerLogReader(),
            ModFileService: new ModFileService(),
            ServersRootService: new ServersRootService(),
            UiService: uiService ?? NoOpUiService.Instance,
            JavaDetector: NoOp.Create<IJavaRuntimeDetector>(),
            LoaderCatalog: NoOp.Create<ILoaderCatalogService>(),
            ModManager: NoOp.Create<IModManager>(),
            ModrinthClient: NoOp.Create<IModrinthClient>(),
            UpdateChecker: NoOp.Create<IUpdateCheckerService>(),
            Launcher: launcher ?? new SucceedingLauncher(),
            JavaRequirementService: NoOp.Create<IMinecraftJavaRequirementService>(),
            JavaInstaller: NoOp.Create<IJavaInstaller>(),
            AppUpdateService: NoOp.Create<IAppUpdateService>());
    }

    private sealed class SucceedingLauncher : IExternalLauncher
    {
        public bool OpenFolder(string folderPath) => true;

        public bool ShowInFolder(string filePath) => true;

        public bool OpenFile(string filePath, bool isTrusted = false) => true;

        public bool OpenUrl(string url, bool isTrusted = false) => true;
    }
}
