using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>頁面組裝所需的服務集合，僅供組合根與 <see cref="PageViewModelFactory"/> 使用</summary>
public sealed record PageServices(
    ISettingsManager SettingsManager,
    IServerManager ServerManager,
    IServerBackupService BackupService,
    IServerRuntimeHost RuntimeHost,
    ServerStopCoordinator StopCoordinator,
    ServerStartPreflight StartPreflight,
    IRunningServerRegistry RunningServerRegistry,
    IServerInspector ServerInspector,
    IServerLaunchPlanner LaunchPlanner,
    IServerPropertiesStore PropertiesStore,
    IServerPlayerConfigStore PlayerConfigStore,
    IServerDirectorySizeService DirectorySizeService,
    IServerIntegrityService IntegrityService,
    IModDependencyPlanner DependencyPlanner,
    IModListExporter ModListExporter,
    ILocalFileSystem FileSystem,
    IServerLogReader LogReader,
    IModFileService ModFileService,
    IServersRootService ServersRootService,
    IUiService UiService,
    IJavaRuntimeDetector JavaDetector,
    ILoaderCatalogService LoaderCatalog,
    IModManager ModManager,
    IModrinthClient ModrinthClient,
    IUpdateCheckerService UpdateChecker,
    IExternalLauncher Launcher,
    IMinecraftJavaRequirementService JavaRequirementService,
    IJavaInstaller JavaInstaller,
    IAppUpdateService AppUpdateService,
    IAccentColorService AccentColorService);
