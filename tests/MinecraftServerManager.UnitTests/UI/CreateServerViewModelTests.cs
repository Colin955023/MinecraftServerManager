using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class CreateServerViewModelTests
{
    internal static CreateServerViewModel Create(Core.Ports.ILoaderCatalogService? loaderCatalog = null, long systemMemoryMb = 16384, App.Services.IUiService? ui = null) =>
        new(
            new Infrastructure.FileSystem.LocalFileSystem(),
            ui ?? NoOpUiService.Instance,
            NoOp.Create<Core.Ports.IJavaRuntimeDetector>(),
            NoOp.Create<Core.Ports.IServerManager>(),
            loaderCatalog ?? NoOp.Create<Core.Ports.ILoaderCatalogService>(),
            systemMemoryMb,
            NoOp.Create<Core.Ports.IExternalLauncher>(),
            static (_, _) => { },
            NoOp.Create<Core.Ports.IMinecraftJavaRequirementService>(),
            NoOp.Create<Core.Ports.IJavaInstaller>(),
            NoOp.Create<Core.Ports.IServerRuntimeHost>(),
            static runtime => new Infrastructure.Servers.ServerInitializationWorkflow(runtime, NoOp.Create<Core.Ports.IServerLaunchPlanner>()));

    [Fact]
    public void MemoryValidation_InvalidValues_ReportsErrors()
    {
        var vm = Create(systemMemoryMb: 16384);
        vm.MinMemoryMb = "4096";
        vm.MaxMemoryMb = "2048";
        Assert.True(vm.IsMemoryError);
        Assert.Contains("最小記憶體不可大於最大記憶體", vm.MemoryWarningText);

        vm.MinMemoryMb = "1024";
        vm.MaxMemoryMb = "32768";
        Assert.True(vm.IsMemoryError);
        Assert.Contains("超過系統總記憶體", vm.MemoryWarningText);

        vm.MinMemoryMb = "1024";
        vm.MaxMemoryMb = "12288";
        Assert.False(vm.IsMemoryError);
        Assert.Contains("超過系統記憶體的一半", vm.MemoryWarningText);

        vm.MinMemoryMb = "1024";
        vm.MaxMemoryMb = "4096";
        Assert.False(vm.IsMemoryError);
        Assert.Empty(vm.MemoryWarningText);
    }

    [Fact]
    public void ResetForm_ModifiedForm_RestoresDefaults()
    {
        var vm = Create();
        vm.ServerName = "自訂伺服器";
        vm.SelectedLoader = "Fabric";
        vm.MaxMemoryMb = "8192";

        vm.ResetFormCommand.Execute(null);

        Assert.Equal(string.IsNullOrWhiteSpace(vm.SelectedMinecraftVersion) ? "Paper" : $"Paper {vm.SelectedMinecraftVersion}", vm.ServerName);
        Assert.Equal("Paper", vm.SelectedLoader);
        Assert.Equal(Domain.Servers.ServerDefaults.DefaultMemoryMaxMb.ToString(System.Globalization.CultureInfo.InvariantCulture), vm.MaxMemoryMb);
    }

    [Fact]
    public void IsMinecraftVersionReloadEnabled_LoaderChanged_Toggles()
    {
        var vm = Create();
        Assert.Equal("Paper", vm.SelectedLoader);
        Assert.False(vm.IsMinecraftVersionReloadEnabled);

        vm.SelectedLoader = "Fabric";
        Assert.True(vm.IsMinecraftVersionReloadEnabled);

        vm.SelectedLoader = "Forge";
        Assert.True(vm.IsMinecraftVersionReloadEnabled);

        vm.SelectedLoader = "NeoForge";
        Assert.True(vm.IsMinecraftVersionReloadEnabled);

        vm.SelectedLoader = "Quilt";
        Assert.True(vm.IsMinecraftVersionReloadEnabled);

        vm.SelectedLoader = "Paper";
        Assert.False(vm.IsMinecraftVersionReloadEnabled);

        vm.SelectedLoader = "Fabric";
        Assert.True(vm.IsMinecraftVersionReloadEnabled);
        vm.ResetFormCommand.Execute(null);
        Assert.Equal("Paper", vm.SelectedLoader);
        Assert.False(vm.IsMinecraftVersionReloadEnabled);
    }

    [Fact]
    public void LoaderVersionsMenu_LoaderChanged_EnabledOnlyForForgeFamily()
    {
        var vm = Create();
        vm.SelectedLoader = "Paper";
        Assert.False(vm.IsLoaderVersionEnabled);

        vm.SelectedLoader = "Fabric";
        Assert.False(vm.IsLoaderVersionEnabled);

        vm.SelectedLoader = "Quilt";
        Assert.False(vm.IsLoaderVersionEnabled);

        vm.SelectedLoader = "Forge";
        Assert.True(vm.IsLoaderVersionEnabled);

        vm.SelectedLoader = "NeoForge";
        Assert.True(vm.IsLoaderVersionEnabled);
    }

    [Fact]
    public async Task InitializeVersions_NoManualSelection_SelectsLatest()
    {
        var fakeCatalog = new FakeLoaderCatalog();
        var vm = Create(fakeCatalog);

        await TestWait.UntilAsync(() => !vm.IsLoadingVersions && vm.SelectedMinecraftVersion is not null, "版本清單載入");

        Assert.Equal("26.3", vm.SelectedMinecraftVersion);
        Assert.Equal("Paper 26.3", vm.ServerName);
    }

    [Fact]
    public async Task LoadVersions_StaleResponse_KeepsNewerSelection()
    {
        var catalog = new PendingLoaderCatalog();
        var vm = Create(catalog);

        vm.SelectedLoader = "Fabric";
        vm.SelectedLoader = "Quilt";

        catalog.Complete(Domain.Servers.LoaderKind.Quilt, "Q1");
        catalog.Complete(Domain.Servers.LoaderKind.Fabric, "F1");
        catalog.Complete(Domain.Servers.LoaderKind.Paper, "P1");

        await TestWait.UntilAsync(() => !vm.IsLoadingVersions && vm.AvailableMinecraftVersions.Count > 0, "最新選擇的版本清單載入");

        // 負向斷言：保留時間讓過期回應的接續工作執行，確認其不會覆寫
        await Task.Delay(200, TestContext.Current.CancellationToken);
        Assert.Equal(["Q1"], vm.AvailableMinecraftVersions);
    }

    [Fact]
    public void ResetForm_ManualServerName_FollowsLoaderAgain()
    {
        var vm = Create();
        vm.ServerName = "SuperServer";

        vm.ResetFormCommand.Execute(null);
        vm.SelectedLoader = "Fabric";

        Assert.Equal("Fabric", vm.ServerName);
    }

    [Fact]
    public void ReloadMinecraftVersionsCommand_Paper_IsDisabled()
    {
        var vm = Create();

        Assert.False(vm.ReloadMinecraftVersionsCommand.CanExecute(null));
        vm.SelectedLoader = "Fabric";
        Assert.True(vm.ReloadMinecraftVersionsCommand.CanExecute(null));
    }

    [Fact]
    public async Task ReloadMinecraftVersions_Failure_NotifiesWarning()
    {
        var ui = new ManualUiService();
        var vm = Create(new FailingReloadCatalog(), ui: ui);
        vm.SelectedLoader = "Fabric";

        await vm.ReloadMinecraftVersionsCommand.ExecuteAsync(null);

        Assert.Contains(ui.Notifications, n => n.Type == App.Services.NotificationType.Warning && n.Message.Contains("重新整理 Minecraft 版本清單失敗", StringComparison.Ordinal));
        Assert.False(vm.IsLoadingVersions);
    }

    [Fact]
    public async Task CreateServerCommand_ValidInput_CreatesServerAndNotifiesSuccess()
    {
        using var rootTemp = new TempDirectory("msm-create-vm-");
        string javaExe = rootTemp.Combine("java.exe");
        await File.WriteAllTextAsync(javaExe, "stub java", TestContext.Current.CancellationToken);

        var ui = new ManualUiService();
        var serverManager = TestServerManagers.Create(rootTemp.FullName);
        var runtimeHost = new FakeServerRuntimeHost();
        string? navigatedPage = null;
        string? navigatedServer = null;

        using var vm = new CreateServerViewModel(
            new Infrastructure.FileSystem.LocalFileSystem(),
            ui,
            new FixedJavaRuntimeDetector(21, javaExe),
            serverManager,
            new FakeLoaderCatalog(),
            systemMemoryMb: 16384,
            new RecordingLauncher(),
            (page, target) =>
            {
                navigatedPage = page;
                navigatedServer = target;
            },
            new FixedJavaRequirementService(21),
            NoOp.Create<Core.Ports.IJavaInstaller>(),
            runtimeHost,
            static runtime => new Infrastructure.Servers.ServerInitializationWorkflow(runtime, new Infrastructure.Servers.ServerLaunchPlanner()));

        await TestWait.UntilAsync(() => !vm.IsLoadingVersions && vm.SelectedMinecraftVersion is not null, "版本清單載入");
        vm.ServerName = "IntegrationTestServer";
        vm.JavaPath = javaExe;

        await vm.CreateServerCommand.ExecuteAsync(null);

        Assert.False(vm.IsCreating);
        Assert.Empty(ui.ErrorMessages);
        Assert.True(Directory.Exists(Path.Combine(rootTemp.FullName, "IntegrationTestServer")));
        Assert.Contains(ui.Notifications, n => n.Type == App.Services.NotificationType.Success && n.Message.Contains("IntegrationTestServer", StringComparison.Ordinal));
        Assert.Equal("manage", navigatedPage);
        Assert.Equal("IntegrationTestServer", navigatedServer);
    }

    private sealed class FailingReloadCatalog : Core.Ports.ILoaderCatalogService
    {
        public Task<IReadOnlyList<Core.Loaders.LoaderVersion>> GetMinecraftVersionsForLoaderAsync(Domain.Servers.LoaderKind loader, bool includeSnapshots = false, bool forceReload = false, CancellationToken cancellationToken = default) =>
            forceReload ? throw new HttpRequestException("offline") : Task.FromResult<IReadOnlyList<Core.Loaders.LoaderVersion>>([]);

        public Task<IReadOnlyList<Core.Loaders.LoaderVersion>> GetPaperMinecraftVersionsAsync(bool forceReload = false, CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyList<Core.Loaders.LoaderVersion>>([]);

        public Task<IReadOnlyList<Core.Loaders.LoaderVersion>> GetLoaderVersionsAsync(Domain.Servers.LoaderKind loader, string minecraftVersion, CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyList<Core.Loaders.LoaderVersion>>([]);

        public Task ForceReloadAllLoadersAsync(CancellationToken cancellationToken = default) => Task.CompletedTask;
        public Task WarmupLoadersAsync(CancellationToken cancellationToken = default) => Task.CompletedTask;
    }

    private sealed class PendingLoaderCatalog : Core.Ports.ILoaderCatalogService
    {
        private readonly System.Collections.Concurrent.ConcurrentDictionary<Domain.Servers.LoaderKind, TaskCompletionSource<IReadOnlyList<Core.Loaders.LoaderVersion>>> _pending = new();

        public void Complete(Domain.Servers.LoaderKind loader, string version) =>
            Request(loader).SetResult([new(version)]);

        private TaskCompletionSource<IReadOnlyList<Core.Loaders.LoaderVersion>> Request(Domain.Servers.LoaderKind loader) =>
            _pending.GetOrAdd(loader, static _ => new(TaskCreationOptions.RunContinuationsAsynchronously));

        public Task<IReadOnlyList<Core.Loaders.LoaderVersion>> GetMinecraftVersionsForLoaderAsync(Domain.Servers.LoaderKind loader, bool includeSnapshots = false, bool forceReload = false, CancellationToken cancellationToken = default) =>
            Request(loader).Task;

        public Task<IReadOnlyList<Core.Loaders.LoaderVersion>> GetPaperMinecraftVersionsAsync(bool forceReload = false, CancellationToken cancellationToken = default) =>
            Request(Domain.Servers.LoaderKind.Paper).Task;

        public Task<IReadOnlyList<Core.Loaders.LoaderVersion>> GetLoaderVersionsAsync(Domain.Servers.LoaderKind loader, string minecraftVersion, CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyList<Core.Loaders.LoaderVersion>>([new("最新穩定版")]);

        public Task ForceReloadAllLoadersAsync(CancellationToken cancellationToken = default) => Task.CompletedTask;
        public Task WarmupLoadersAsync(CancellationToken cancellationToken = default) => Task.CompletedTask;
    }

    private sealed class FakeLoaderCatalog : Core.Ports.ILoaderCatalogService
    {
        public Task<IReadOnlyList<Core.Loaders.LoaderVersion>> GetMinecraftVersionsForLoaderAsync(Domain.Servers.LoaderKind loader, bool includeSnapshots = false, bool forceReload = false, CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyList<Core.Loaders.LoaderVersion>>([new("26.3"), new("1.21.4"), new("1.20.1")]);

        public Task<IReadOnlyList<Core.Loaders.LoaderVersion>> GetPaperMinecraftVersionsAsync(bool forceReload = false, CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyList<Core.Loaders.LoaderVersion>>([new("26.3"), new("1.21.4")]);

        public Task<IReadOnlyList<Core.Loaders.LoaderVersion>> GetLoaderVersionsAsync(Domain.Servers.LoaderKind loader, string minecraftVersion, CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyList<Core.Loaders.LoaderVersion>>([new("最新穩定版")]);

        public Task ForceReloadAllLoadersAsync(CancellationToken cancellationToken = default) => Task.CompletedTask;
        public Task WarmupLoadersAsync(CancellationToken cancellationToken = default) => Task.CompletedTask;
    }
}

public sealed class CreateServerSynchronizationTests
{
    [Fact]
    public void ServerName_LoaderOrVersionChanged_Synchronizes()
    {
        var vm = CreateServerViewModelTests.Create();
        // 初始切換 loader（版本尚未載入時與 loader 同步）
        vm.SelectedLoader = "Fabric";
        Assert.Equal("Fabric", vm.ServerName);

        // 切換版本
        vm.SelectedMinecraftVersion = "1.20.1";
        Assert.Equal("Fabric 1.20.1", vm.ServerName);

        // 帶字尾切換
        vm.ServerName = "Fabric 1.20.1 - 冒險伺服器";
        vm.SelectedLoader = "Forge";
        Assert.Equal("Forge 1.20.1 - 冒險伺服器", vm.ServerName);

        // 完全自訂名稱不覆蓋
        vm.ServerName = "SuperServer";
        vm.SelectedLoader = "NeoForge";
        Assert.Equal("SuperServer", vm.ServerName);
    }

}
