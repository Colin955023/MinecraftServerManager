namespace MinecraftServerManager.UnitTests.TestSupport;

/// <summary>以條件輪詢等待背景作業完成；逾時即判定測試失敗（不默默通過）</summary>
internal static class TestWait
{
    public static readonly TimeSpan DefaultTimeout = TimeSpan.FromSeconds(10);
    private static readonly TimeSpan PollInterval = TimeSpan.FromMilliseconds(10);

    /// <summary>等待 <paramref name="condition"/> 成立；逾時以 <paramref name="description"/> 說明失敗原因</summary>
    public static async Task UntilAsync(Func<bool> condition, string description, TimeSpan? timeout = null)
    {
        CancellationToken testToken = TestContext.Current.CancellationToken;
        using var timeoutSource = CancellationTokenSource.CreateLinkedTokenSource(testToken);
        timeoutSource.CancelAfter(timeout ?? DefaultTimeout);
        try
        {
            while (!condition())
            {
                await Task.Delay(PollInterval, timeoutSource.Token);
            }
        }
        catch (OperationCanceledException) when (!testToken.IsCancellationRequested)
        {
            Assert.Fail($"等待逾時：{description}");
        }
    }
}
