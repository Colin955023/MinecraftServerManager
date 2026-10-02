using MinecraftServerManager.App.ViewModels;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class CreateServerViewModelTests
{
    [Fact]
    public void MemoryValidationShouldCatchInvalidValues()
    {
        var vm = new CreateServerViewModel(systemMemoryMb: 16384)
        {
            MinMemoryMb = "4096",
            MaxMemoryMb = "2048"
        };
        Assert.True(vm.IsMemoryError);
        Assert.Contains("最小記憶體必須小於最大記憶體", vm.MemoryWarningText);

        vm.MinMemoryMb = "1024";
        vm.MaxMemoryMb = "32768";
        Assert.True(vm.IsMemoryError);
        Assert.Contains("超過系統總記憶體", vm.MemoryWarningText);

        vm.MinMemoryMb = "1024";
        vm.MaxMemoryMb = "12288";
        Assert.False(vm.IsMemoryError);
        Assert.True(vm.IsMemoryWarning);
        Assert.Contains("超過系統記憶體的一半", vm.MemoryWarningText);

        vm.MinMemoryMb = "1024";
        vm.MaxMemoryMb = "4096";
        Assert.False(vm.IsMemoryError);
        Assert.False(vm.IsMemoryWarning);
        Assert.Empty(vm.MemoryWarningText);
    }

    [Fact]
    public void ResetFormShouldRestoreDefaults()
    {
        var vm = new CreateServerViewModel
        {
            ServerName = "自訂伺服器",
            SelectedLoader = "Fabric",
            MaxMemoryMb = "8192"
        };

        vm.ResetFormCommand.Execute(null);

        Assert.Equal($"Paper {vm.SelectedMinecraftVersion}", vm.ServerName);
        Assert.Equal("Paper", vm.SelectedLoader);
        Assert.Equal("2048", vm.MaxMemoryMb);
    }

    [Fact]
    public async Task AutoDetectJavaShouldSilentlySetPathWhenFoundWithoutNotification()
    {
        string notification = string.Empty;
        var fakeDetector = new FakeJavaDetector(new Core.Ports.JavaRuntimeInfo(
            ExecutablePath: @"C:\Java\bin\java.exe",
            MajorVersion: 21,
            Is64Bit: true,
            Vendor: "Microsoft"));

        var fakeReq = new FakeJavaRequirement(21);

        var vm = new CreateServerViewModel(
            javaDetector: fakeDetector,
            javaRequirementService: fakeReq,
            notificationSink: (msg, isErr) => notification = msg)
        {
            SelectedMinecraftVersion = "1.21.4"
        };

        await vm.AutoDetectJavaCommand.ExecuteAsync(null);

        Assert.Equal(@"C:\Java\bin\java.exe", vm.JavaPath);
        Assert.Empty(notification); // 驗證不會彈出提示，靜默填入
    }

    private sealed class FakeJavaDetector(Core.Ports.JavaRuntimeInfo? match) : Core.Ports.IJavaRuntimeDetector
    {
        public Task<IReadOnlyList<Core.Ports.JavaRuntimeInfo>> DetectAsync(bool forceRefresh = false, CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyList<Core.Ports.JavaRuntimeInfo>>(match != null ? [match] : []);

        public Task<Core.Ports.JavaRuntimeInfo?> FindBestMatchAsync(int targetMajor, CancellationToken cancellationToken = default) =>
            Task.FromResult(match);
    }

    private sealed class FakeJavaRequirement(int major) : Core.Ports.IMinecraftJavaRequirementService
    {
        public Task<int> GetRequiredJavaMajorAsync(string minecraftVersion, Domain.Servers.LoaderKind loader = Domain.Servers.LoaderKind.Unknown, CancellationToken cancellationToken = default) =>
            Task.FromResult(major);

        public int? GetCachedJavaMajor(string minecraftVersion, Domain.Servers.LoaderKind loader = Domain.Servers.LoaderKind.Unknown) => major;

        public Task<IReadOnlyDictionary<string, int>> PreloadAllJavaRequirementsAsync(bool force = false, CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyDictionary<string, int>>(new Dictionary<string, int>());

        public void ReloadCache() { }
    }

    [Fact]
    public void IsMinecraftVersionReloadEnabledShouldToggleBasedOnSelectedLoader()
    {
        var vm = new CreateServerViewModel();
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
        var vm = new CreateServerViewModel
        {
            SelectedLoader = "Paper"
        };
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
}

public sealed class CreateServerSynchronizationTests
{
    [Fact]
    public void ServerNameShouldSynchronizeWithLoaderAndVersion()
    {
        var vm = new CreateServerViewModel
        {
            // 初始切換 loader
            SelectedLoader = "Fabric"
        };
        Assert.Equal("Fabric 1.21.4", vm.ServerName);

        // 切換版本
        vm.SelectedMinecraftVersion = "1.20.1";
        Assert.Equal("Fabric 1.20.1", vm.ServerName);

        // 帶後綴切換
        vm.ServerName = "Fabric 1.20.1 - 冒險伺服器";
        vm.SelectedLoader = "Forge";
        Assert.Equal("Forge 1.20.1 - 冒險伺服器", vm.ServerName);

        // 完全自訂名稱不覆蓋
        vm.ServerName = "SuperServer";
        vm.SelectedLoader = "NeoForge";
        Assert.Equal("SuperServer", vm.ServerName);
    }

    [Fact]
    public void IsNotDetectingJavaShouldInvertIsDetectingJava()
    {
        var vm = new CreateServerViewModel();
        Assert.True(vm.IsNotDetectingJava);

        vm.IsDetectingJava = true;
        Assert.False(vm.IsNotDetectingJava);

        vm.IsDetectingJava = false;
        Assert.True(vm.IsNotDetectingJava);
    }
}
