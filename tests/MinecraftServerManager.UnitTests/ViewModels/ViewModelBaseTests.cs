using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using Xunit;

namespace MinecraftServerManager.UnitTests.ViewModels;

public sealed class ViewModelBaseTests
{
    private sealed class TestUiService : NoOpUiService
    {
        public string? LastErrorMessage { get; private set; }
        public string? LastErrorTitle { get; private set; }

        public override Task ShowErrorAsync(string message, string title)
        {
            LastErrorMessage = message;
            LastErrorTitle = title;
            return Task.CompletedTask;
        }
    }

    [Fact]
    public async Task RunSafeAsync_WhenWorkSucceeds_CompletesWithoutErrors()
    {
        bool executed = false;
        await ViewModelBase.RunSafeAsync(() =>
        {
            executed = true;
            return Task.CompletedTask;
        }, "成功測試");

        Assert.True(executed);
    }

    [Fact]
    public async Task RunSafeAsync_WhenOperationCanceledExceptionThrown_SwallowsException()
    {
        var task = ViewModelBase.RunSafeAsync(() => throw new OperationCanceledException(), "取消測試");
        await task;

        Assert.True(task.IsCompletedSuccessfully);
    }

    [Fact]
    public async Task RunSafeAsync_WhenExceptionThrown_CatchesAndCallsOnException()
    {
        Exception? captured = null;
        var expectedEx = new InvalidOperationException("測試錯誤");

        await ViewModelBase.RunSafeAsync(
            () => Task.FromException(expectedEx),
            "失敗測試",
            onException: ex => captured = ex);

        Assert.Same(expectedEx, captured);
    }

    [Fact]
    public async Task RunSafeAsync_WhenNotifyUserIsTrue_InvokesUiServiceShowError()
    {
        var ui = new TestUiService();
        var expectedEx = new InvalidOperationException("嚴重失敗");

        await ViewModelBase.RunSafeAsync(
            () => Task.FromException(expectedEx),
            "使用者提示測試",
            uiService: ui,
            notifyUser: true);

        Assert.NotNull(ui.LastErrorMessage);
        Assert.Contains("嚴重失敗", ui.LastErrorMessage);
        Assert.Equal("操作錯誤", ui.LastErrorTitle);
    }

    [Fact]
    public async Task RunSafeAsync_WhenOnExceptionThrows_DoesNotCrashCaller()
    {
        await ViewModelBase.RunSafeAsync(
            () => Task.FromException(new InvalidOperationException("初始錯誤")),
            "雙重異常測試",
            onException: _ => throw new InvalidOperationException("回呼異常"));
    }
}
