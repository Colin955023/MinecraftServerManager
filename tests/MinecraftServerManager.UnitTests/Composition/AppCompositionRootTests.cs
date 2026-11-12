using MinecraftServerManager.App;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Infrastructure.Settings;
using MinecraftServerManager.UnitTests.UI;
using Xunit;

namespace MinecraftServerManager.UnitTests.Composition;

public sealed partial class AppCompositionRootTests : IDisposable
{
    private readonly TempDirectory _testRootTemp = new("msm-composition-test-");
    private readonly string _testRoot;

    public AppCompositionRootTests()
    {
        _testRoot = _testRootTemp.FullName;
    }

    public void Dispose() => _testRootTemp.Dispose();

    [Fact]
    public async Task ConstructsCompleteObjectGraphSuccessfully()
    {
        await using var root = new AppCompositionRoot(_testRoot, NoOpUiService.Instance, new SettingsManager(_testRoot), new Infrastructure.Process.ProcessRunner());

        Assert.NotNull(root.MainViewModel);
        Assert.False(root.IsServerRunning);

        // 建立頁面可成功導覽，代表各頁面的相依注入完整
        root.MainViewModel.Navigate("manage");
        Assert.IsType<ManageServerViewModel>(root.MainViewModel.CurrentPage);
    }
}
