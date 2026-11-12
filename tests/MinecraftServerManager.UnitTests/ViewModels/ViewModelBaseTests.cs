using MinecraftServerManager.App.ViewModels;
using Xunit;

namespace MinecraftServerManager.UnitTests.ViewModels;

public sealed class ViewModelBaseTests
{
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
    public async Task RunSafeAsync_WhenExceptionThrown_DoesNotCrashCaller()
    {
        var task = ViewModelBase.RunSafeAsync(() => Task.FromException(new InvalidOperationException("測試錯誤")), "失敗測試");
        await task;

        Assert.True(task.IsCompletedSuccessfully);
    }
}
