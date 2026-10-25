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
    IJavaRuntimeDetector? JavaDetector = null,
    ILoaderCatalogService? LoaderCatalog = null,
    IModManager? ModManager = null,
    IModrinthClient? ModrinthClient = null,
    IUpdateCheckerService? UpdateChecker = null,
    IExternalLauncher? Launcher = null,
    IMinecraftJavaRequirementService? JavaRequirementService = null,
    IJavaInstaller? JavaInstaller = null,
    IUiService? UiService = null,
    IAppUpdateService? AppUpdateService = null);
