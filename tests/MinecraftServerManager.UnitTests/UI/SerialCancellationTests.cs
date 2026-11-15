using MinecraftServerManager.App.Services;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class SerialCancellationTests
{
    [Fact]
    public void Next_CancelsPreviousTokenAndKeepsLatestActive()
    {
        using var serial = new SerialCancellation();
        var first = serial.Next();
        var second = serial.Next();

        Assert.True(first.IsCancellationRequested);
        Assert.False(second.IsCancellationRequested);
    }

    [Fact]
    public void Dispose_CancelsCurrentToken()
    {
        var serial = new SerialCancellation();
        var token = serial.Next();

        serial.Dispose();

        Assert.True(token.IsCancellationRequested);
    }

    [Fact]
    public void Next_AfterDispose_ReturnsCanceledToken()
    {
        var serial = new SerialCancellation();
        serial.Dispose();

        Assert.True(serial.Next().IsCancellationRequested);
    }
}
