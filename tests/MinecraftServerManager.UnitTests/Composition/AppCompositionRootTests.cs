using MinecraftServerManager.App;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Infrastructure.Settings;
using MinecraftServerManager.UnitTests.UI;
using Xunit;

namespace MinecraftServerManager.UnitTests.Composition;

public sealed partial class AppCompositionRootTests : IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(AppCompositionRootTests));
    private readonly string _testRoot;

    public AppCompositionRootTests()
    {
        _testRoot = Path.Combine(Path.GetTempPath(), "msm-composition-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_testRoot);
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_testRoot))
            {
                Directory.Delete(_testRoot, recursive: true);
            }
        }
        catch (Exception ex)
        {
            Logger.Warning("測試清理暫存資源失敗: {0}", ex.Message);
        }
    }

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
