using MinecraftServerManager.App;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Infrastructure.Settings;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.UnitTests.UI;

/// <summary>組合根於隔離使用者資料目錄下建構與釋放</summary>
[Collection("EnvironmentVariableCollection")]
public sealed class AppCompositionRootTests : IDisposable
{

    private readonly TempDirectory _testRootTemp = new("msm-composition-test-");
    private readonly string _testRoot;

    public AppCompositionRootTests()
    {
        _testRoot = _testRootTemp.FullName;
    }

    public void Dispose() => _testRootTemp.Dispose();

    [Fact]
    public async Task Constructor_IsolatedDataDir_BuildsObjectGraph()
    {
        string userDataDir = Path.Combine(_testRoot, "userdata");
        using var scoped = new ScopedEnvironmentVariable("MSM_USER_DATA_DIR", userDataDir);
        Assert.Equal(Path.GetFullPath(userDataDir), RuntimePaths.GetUserDataDir());

        await using var root = new AppCompositionRoot(_testRoot, NoOpUiService.Instance, new SettingsManager(_testRoot), new Infrastructure.Process.ProcessRunner(), new Infrastructure.Process.ShellLauncher(static _ => { }), NoOp.Create<IAccentColorService>());

        Assert.NotNull(root.MainViewModel);
        Assert.False(root.IsServerRunning);

        // 建立頁面可成功導覽，代表各頁面的相依注入完整
        root.MainViewModel.Navigate("manage");
        var manageVm = Assert.IsType<ManageServerViewModel>(root.MainViewModel.CurrentPage);

        // 等待導覽觸發之背景清單刷新完成，避免釋放後仍存取暫存目錄
        await WaitUntilIdleAsync(manageVm.List);
    }

    [Fact]
    public async Task DisposeAsync_WaitsForBackgroundWarmupToFinish()
    {
        string userDataDir = Path.Combine(_testRoot, "warmup-userdata");
        using var scoped = new ScopedEnvironmentVariable("MSM_USER_DATA_DIR", userDataDir);
        var root = new AppCompositionRoot(
            _testRoot,
            NoOpUiService.Instance,
            new SettingsManager(_testRoot),
            new Infrastructure.Process.ProcessRunner(),
            new Infrastructure.Process.ShellLauncher(static _ => { }),
            NoOp.Create<IAccentColorService>());
        var started = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var finish = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);

        root.StartBackgroundWarmup(async _ =>
        {
            started.TrySetResult();
            await finish.Task.ConfigureAwait(false);
        });
        await started.Task.WaitAsync(TestContext.Current.CancellationToken);

        Task disposeTask = root.DisposeAsync().AsTask();
        Assert.False(disposeTask.IsCompleted);

        finish.TrySetResult();
        await disposeTask;
    }

    private static Task WaitUntilIdleAsync(ServerListViewModel list) =>
        TestWait.UntilAsync(() => !list.IsBusy, "伺服器清單刷新完成");
}
