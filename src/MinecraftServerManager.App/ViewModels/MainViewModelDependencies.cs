using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 主視窗 ViewModel 之不可變相依集合，集中管理組合根所提供的共用服務實例
/// </summary>
public sealed record MainViewModelDependencies(
    SettingsManager SettingsManager,
    IServerManager ServerManager,
    IServerBackupService BackupService,
    IServerRuntime ServerRuntime,
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
    IAppUpdateService AppUpdateService);
