using MinecraftServerManager.App.Services;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public class DialogStackCoordinatorTests
{
    /// <summary>
    /// 以可觀察行為確認堆疊已清空：新對話框直接顯示，不會要求任何前層對話框隱藏
    /// </summary>
    private static async Task AssertStackEmptyAsync(DialogStackCoordinator coordinator)
    {
        bool staleHideRequested = false;
        string probe = await coordinator.ShowDialogAsync(
            () => Task.FromResult("probe"),
            () => staleHideRequested = true);

        Assert.Equal("probe", probe);
        Assert.False(staleHideRequested);
    }

    [Fact]
    public async Task ShowDialogAsync_SingleDialog_ReturnsResultDirectly()
    {
        var coordinator = new DialogStackCoordinator();
        bool hideCalled = false;

        string result = await coordinator.ShowDialogAsync(
            () => Task.FromResult("Result1"),
            () => hideCalled = true);

        Assert.Equal("Result1", result);
        Assert.False(hideCalled);
        await AssertStackEmptyAsync(coordinator);
    }

    [Fact]
    public async Task ShowDialogAsync_NestedDialog_InterruptsAndResumesOuterDialog()
    {
        var coordinator = new DialogStackCoordinator();
        var outerShownTcs = new TaskCompletionSource();
        var outerResumeTcs = new TaskCompletionSource();
        var outerFinishTcs = new TaskCompletionSource();
        int outerShowCount = 0;
        int outerHideCount = 0;

        // 啟動外層對話框
        var outerTask = coordinator.ShowDialogAsync(
            async () =>
            {
                outerShowCount++;
                if (outerShowCount == 1)
                {
                    outerShownTcs.TrySetResult();
                    // 模擬對話框顯示中，等待被隱藏或結束
                    await outerResumeTcs.Task;
                    return "OuterCancelledDueToHide";
                }

                // 第二次顯示，等待使用者真正完成
                await outerFinishTcs.Task;
                return "OuterFinalResult";
            },
            () =>
            {
                outerHideCount++;
                // 收到 hide 請求時，讓第一次 showAsync 完成並傳回
                outerResumeTcs.TrySetResult();
            });

        // 等待外層對話框已顯示
        await outerShownTcs.Task;

        // 啟動內層（中斷）對話框
        int innerShowCount = 0;
        string innerResult = await coordinator.ShowDialogAsync(
            () =>
            {
                innerShowCount++;
                return Task.FromResult("InnerResult");
            },
            () => { });

        Assert.Equal("InnerResult", innerResult);
        Assert.Equal(1, innerShowCount);
        Assert.Equal(1, outerHideCount);

        // 內層結束後，外層應自動重新執行 showAsync
        // 此時結束外層對話框
        outerFinishTcs.TrySetResult();
        string finalOuterResult = await outerTask;

        Assert.Equal("OuterFinalResult", finalOuterResult);
        Assert.Equal(2, outerShowCount);
        await AssertStackEmptyAsync(coordinator);
    }

    [Fact]
    public async Task ShowDialogAsync_NestedDialog_WaitsUntilOuterIsActuallyHidden()
    {
        var coordinator = new DialogStackCoordinator();
        var outerShownTcs = new TaskCompletionSource();
        var outerHiddenTcs = new TaskCompletionSource();
        var outerFinishTcs = new TaskCompletionSource();
        bool hideRequested = false;
        int outerShowCount = 0;

        var outerTask = coordinator.ShowDialogAsync(
            async () =>
            {
                outerShowCount++;
                if (outerShowCount == 1)
                {
                    outerShownTcs.TrySetResult();
                    await outerHiddenTcs.Task;
                    return "Hidden";
                }

                await outerFinishTcs.Task;
                return "OuterDone";
            },
            () => hideRequested = true);

        await outerShownTcs.Task;

        bool innerShown = false;
        var innerTask = coordinator.ShowDialogAsync(
            () =>
            {
                innerShown = true;
                return Task.FromResult("Inner");
            },
            () => { });

        // 外層尚未真正關閉（隱藏動畫進行中）時，內層不得顯示
        Assert.True(hideRequested);
        Assert.False(innerShown);

        outerHiddenTcs.TrySetResult();
        Assert.Equal("Inner", await innerTask);
        Assert.True(innerShown);

        outerFinishTcs.TrySetResult();
        Assert.Equal("OuterDone", await outerTask);
        await AssertStackEmptyAsync(coordinator);
    }

    [Fact]
    public async Task ShowDialogAsync_InnerThrows_CleansUpStackAndResumesOuter()
    {
        var coordinator = new DialogStackCoordinator();
        var outerShownTcs = new TaskCompletionSource();
        var outerResumeTcs = new TaskCompletionSource();
        var outerFinishTcs = new TaskCompletionSource();
        int outerShowCount = 0;

        var outerTask = coordinator.ShowDialogAsync(
            async () =>
            {
                outerShowCount++;
                if (outerShowCount == 1)
                {
                    outerShownTcs.TrySetResult();
                    await outerResumeTcs.Task;
                    return "Cancelled";
                }
                await outerFinishTcs.Task;
                return "OuterDone";
            },
            () => outerResumeTcs.TrySetResult());

        await outerShownTcs.Task;

        // 內層對話框拋出例外
        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            coordinator.ShowDialogAsync<string>(
                () => throw new InvalidOperationException("Inner failure"),
                () => { }));

        // 確保內層拋出後，外層仍可正確恢復並完成
        outerFinishTcs.TrySetResult();
        string outerResult = await outerTask;

        Assert.Equal("OuterDone", outerResult);
        Assert.Equal(2, outerShowCount);
        await AssertStackEmptyAsync(coordinator);
    }
}
