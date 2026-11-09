using MinecraftServerManager.App.ViewModels;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class CreateServerViewModelTests
{
    internal static CreateServerViewModel Create(Core.Ports.ILoaderCatalogService? loaderCatalog = null, long systemMemoryMb = 16384) =>
        new(
            new Infrastructure.FileSystem.LocalFileSystem(),
            NoOpUiService.Instance,
            NoOp.Create<Core.Ports.IJavaRuntimeDetector>(),
            NoOp.Create<Core.Ports.IServerManager>(),
            loaderCatalog ?? NoOp.Create<Core.Ports.ILoaderCatalogService>(),
            systemMemoryMb,
            NoOp.Create<Core.Ports.IExternalLauncher>(),
            static (_, _) => { },
            NoOp.Create<Core.Ports.IMinecraftJavaRequirementService>(),
            NoOp.Create<Core.Ports.IJavaInstaller>(),
            NoOp.Create<Core.Ports.IServerRuntime>(),
            NoOp.Create<Core.Servers.IServerLaunchPlanner>());

    [Fact]
    public void MemoryValidationShouldCatchInvalidValues()
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
    public void ResetFormShouldRestoreDefaults()
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
    public void IsMinecraftVersionReloadEnabledShouldToggleBasedOnSelectedLoader()
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
    public void LoaderVersionsMenuShouldBeDisabledForPaperFabricQuiltAndEnabledForForgeNeoForge()
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
    public async Task InitializeVersionsShouldAutoSelectFirstLatestVersionWhenNotManuallySelected()
    {
        var fakeCatalog = new FakeLoaderCatalog();
        var vm = Create(fakeCatalog);

        for (int i = 0; i < 50 && vm.IsLoadingVersions; i++)
        {
            await Task.Delay(20);
        }

        Assert.Equal("26.3", vm.SelectedMinecraftVersion);
        Assert.Equal("Paper 26.3", vm.ServerName);
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
    public void ServerNameShouldSynchronizeWithLoaderAndVersion()
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
