namespace MinecraftServerManager.App.ViewModels;

/// <summary>頁面 ViewModel 工廠</summary>
public sealed class PageViewModelFactory
{
    private readonly PageServices services;

    public PageViewModelFactory(PageServices services)
    {
        ArgumentNullException.ThrowIfNull(services);
        this.services = services;
    }
    /// <summary>建立「建立新伺服器」頁面</summary>
    public CreateServerViewModel CreateCreatePage(Action<string, string?> navigate) => new(
        services.FileSystem,
        services.UiService,
        services.JavaDetector,
        services.ServerManager,
        services.LoaderCatalog,
        systemMemoryMb: Core.Utilities.MemoryHelpers.GetTotalSystemMemoryMb(),
        launcher: services.Launcher,
        navigateCallback: navigate,
        javaRequirementService: services.JavaRequirementService,
        javaInstaller: services.JavaInstaller,
        runtimeHost: services.RuntimeHost,
        createInitializationWorkflow: runtime => new Infrastructure.Servers.ServerInitializationWorkflow(runtime, services.LaunchPlanner));

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

    /// <summary>建立「模組管理」頁面及其共用同一 <see cref="ModsContext"/> 的四個子 ViewModel</summary>
    public ModsViewModel CreateModsPage()
    {
        var ui = services.UiService;
        var context = new ModsContext();
        return new ModsViewModel(
            context,
            new LocalModsViewModel(context, services.ModFileService, services.ModListExporter, ui, services.ModManager, services.Launcher),
            new OnlineModSearchViewModel(context, ui, services.ModrinthClient, services.Launcher),
            new ModInstallQueueViewModel(context, services.DependencyPlanner, services.ModFileService, ui, services.ModManager, services.ModrinthClient, services.RuntimeHost),
            new ModUpdateViewModel(context, services.DependencyPlanner, services.ModFileService, ui, services.ModManager, services.ModrinthClient, services.RuntimeHost),
            services.ServerManager,
            ui);
    }

    /// <summary>建立「關於與設定」頁面</summary>
    public AboutPreferencesViewModel CreateAboutPage(Action<string> onThemeModeChanged, Action onResetWindowSizeRequested) => new(
        services.UiService,
        services.SettingsManager,
        services.StopCoordinator,
        services.UpdateChecker,
        onThemeModeChanged,
        onResetWindowSizeRequested,
        services.Launcher,
        services.AppUpdateService,
        services.AccentColorService);

    /// <summary>建立匯入伺服器對話方塊 ViewModel</summary>
    public ImportServerViewModel CreateImportServerDialog() => new(services.ServerManager, uiService: services.UiService);
}
