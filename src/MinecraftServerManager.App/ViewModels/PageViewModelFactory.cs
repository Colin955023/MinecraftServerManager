namespace MinecraftServerManager.App.ViewModels;

/// <summary>頁面 ViewModel 工廠：集中依 <see cref="PageServices"/> 組裝各頁面及其子 ViewModel</summary>
public sealed class PageViewModelFactory(PageServices services)
{
    /// <summary>建立「建立新伺服器」頁面</summary>
    public CreateServerViewModel CreateCreatePage(Action<string, string?> navigate) => new(
        services.FileSystem,
        services.UiService,
        services.JavaDetector,
        services.ServerManager,
        services.LoaderCatalog,
        systemMemoryMb: Core.Utilities.MemoryUtils.GetTotalSystemMemoryMb(),
        launcher: services.Launcher,
        navigateCallback: navigate,
        javaRequirementService: services.JavaRequirementService,
        javaInstaller: services.JavaInstaller,
        runtimeHost: services.RuntimeHost,
        launchPlanner: services.LaunchPlanner);

    /// <summary>建立「管理現有伺服器」頁面及其四個子 ViewModel</summary>
    public ManageServerViewModel CreateManagePage(Action<string> navigate)
    {
        var ui = services.UiService;

        var list = new ServerListViewModel(
            services.SettingsManager,
            services.ServerManager,
            services.BackupService,
            services.RuntimeHost,
            services.StopCoordinator,
            services.IntegrityService,
            services.DirectorySizeService,
            services.FileSystem,
            ui,
            navigate);

        var lifecycle = new ServerLifecycleViewModel(
            services.ServerManager,
            services.RuntimeHost,
            services.StopCoordinator,
            services.StartPreflight,
            services.ServerInspector,
            services.LaunchPlanner,
            services.LogReader,
            services.PropertiesStore,
            services.FileSystem,
            list,
            ui,
            services.JavaDetector,
            services.JavaRequirementService);

        var backup = new ServerBackupViewModel(
            services.ServerManager,
            services.BackupService,
            services.RuntimeHost,
            services.FileSystem,
            list,
            ui,
            services.Launcher);

        var serversRoot = new ServersRootViewModel(
            services.SettingsManager,
            services.ServersRootService,
            services.RuntimeHost,
            services.FileSystem,
            list,
            ui);

        return new ManageServerViewModel(
            list,
            lifecycle,
            backup,
            serversRoot,
            services.ServerManager,
            services.BackupService,
            services.PropertiesStore,
            services.PlayerConfigStore,
            services.ServerInspector,
            services.RuntimeHost,
            services.FileSystem,
            services.Launcher,
            ui);
    }

    /// <summary>建立「模組管理」頁面</summary>
    public ModsViewModel CreateModsPage() => new(
        services.DependencyPlanner,
        services.ModListExporter,
        services.ModFileService,
        services.UiService,
        services.ServerManager,
        services.ModManager,
        services.ModrinthClient,
        services.Launcher);

    /// <summary>建立「關於與設定」頁面</summary>
    public AboutPreferencesViewModel CreateAboutPage(Action<string> onThemeModeChanged, Action onResetWindowSizeRequested) => new(
        services.UiService,
        services.SettingsManager,
        services.UpdateChecker,
        onThemeModeChanged,
        onResetWindowSizeRequested,
        services.Launcher,
        services.AppUpdateService);

    /// <summary>建立匯入伺服器對話方塊 ViewModel</summary>
    public ImportServerViewModel CreateImportServerDialog() => new(services.ServerManager, uiService: services.UiService);
}
