using System.Collections.Concurrent;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ModBatchOperationsTests
{
    private const string Official = "https://cdn.modrinth.com/data/a/b.jar";

    private sealed class RecordingProgress : IOperationProgress
    {
        public ConcurrentQueue<(int Current, int Total, string Message)> Updates { get; } = new();

        public void UpdateProgress(int current, int total, string message) => Updates.Enqueue((current, total, message));

        public void Dispose()
        {
        }
    }

    private static IModFileService ModFileService() => new StubModFileService();

    private sealed class StubModFileService : IModFileService
    {
        public bool IsOfficialModrinthSource(string? url) => url == Official;

        public Task CleanupStagingDirectoryAsync(string serverPath, CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task<string> EnsureModsDirectoryAsync(string serverPath, CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task<string> ResolveModFilePathAsync(string serverPath, string fileName, CancellationToken cancellationToken = default) => throw new NotSupportedException();

        public Task DeleteModFileVariantsAsync(string serverPath, string fileName, CancellationToken cancellationToken = default) => throw new NotSupportedException();
    }

    [Fact]
    public void ExcludeUnofficialSources_MixedSources_ReturnsOfficialAndWarnsOnce()
    {
        var ui = new ManualUiService();
        (string Name, string Url)[] items = [("A", Official), ("B", "https://evil.example/b.jar"), ("C", Official)];

        var allowed = ModBatchOperations.ExcludeUnofficialSources(ui, ModFileService(), items, static i => i.Name, static i => i.Url, "測試模組");

        Assert.Equal(["A", "C"], allowed.Select(static i => i.Name));
        var notification = Assert.Single(ui.Notifications);
        Assert.Equal(NotificationType.Warning, notification.Type);
        Assert.Contains("測試模組", notification.Message, StringComparison.Ordinal);
        Assert.Contains("• B：https://evil.example/b.jar", notification.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void ExcludeUnofficialSources_AllOfficial_DoesNotNotify()
    {
        var ui = new ManualUiService();

        var allowed = ModBatchOperations.ExcludeUnofficialSources(ui, ModFileService(), [Official], static i => i, static i => i, "x");

        Assert.Single(allowed);
        Assert.Empty(ui.Notifications);
    }

    [Fact]
    public void NotifySummary_NoFailures_ShowsSuccess()
    {
        var ui = new ManualUiService();

        ModBatchOperations.NotifySummary(ui, "安裝", 3, []);

        Assert.Equal(("已成功安裝 3 個模組！", NotificationType.Success), ui.LastNotification);
    }

    [Fact]
    public void NotifySummary_WithFailures_ListsEachReasonAsWarning()
    {
        var ui = new ManualUiService();

        ModBatchOperations.NotifySummary(ui, "更新", 1, ["A：逾時", "B：雜湊不符"]);

        var (message, type) = ui.LastNotification!.Value;
        Assert.Equal(NotificationType.Warning, type);
        Assert.StartsWith("已成功更新 1 個模組，2 個失敗：", message, StringComparison.Ordinal);
        Assert.Contains("• A：逾時", message, StringComparison.Ordinal);
        Assert.Contains("• B：雜湊不符", message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task RunWithProgressAsync_AllItems_ReportsEachCompletionAndRespectsParallelism()
    {
        var progress = new RecordingProgress();
        int running = 0;
        int peak = 0;
        string[] items = ["a", "b", "c", "d", "e"];

        await ModBatchOperations.RunWithProgressAsync(items, 2, progress, "安裝", static i => i, async (_, token) =>
        {
            int now = Interlocked.Increment(ref running);
            InterlockedMax(ref peak, now);
            await Task.Yield();
            Interlocked.Decrement(ref running);
        }, TestContext.Current.CancellationToken);

        Assert.InRange(peak, 1, 2);
        Assert.Equal(items.Length, progress.Updates.Count);
        Assert.Equal(Enumerable.Range(1, items.Length), progress.Updates.Select(static u => u.Current).Order());
        Assert.All(progress.Updates, static u => Assert.Equal(5, u.Total));
    }

    [Fact]
    public async Task RunWithProgressAsync_BodyThrows_StillReportsProgressAndPropagates()
    {
        var progress = new RecordingProgress();

        await Assert.ThrowsAsync<InvalidOperationException>(() => ModBatchOperations.RunWithProgressAsync(
            ["bad"], 1, progress, "安裝", static i => i, static (_, _) => throw new InvalidOperationException("x"), TestContext.Current.CancellationToken));

        Assert.Equal((1, 1, "正在安裝（1/1）：bad..."), Assert.Single(progress.Updates));
    }

    [Fact]
    public async Task RunWithProgressAsync_CanceledToken_ThrowsOperationCanceled()
    {
        var progress = new RecordingProgress();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => ModBatchOperations.RunWithProgressAsync(
            ["a"], 1, progress, "安裝", static i => i, static (_, _) => ValueTask.CompletedTask, new CancellationToken(canceled: true)));

        Assert.Empty(progress.Updates);
    }

    private static void InterlockedMax(ref int target, int value)
    {
        int current;
        while ((current = Volatile.Read(ref target)) < value && Interlocked.CompareExchange(ref target, value, current) != current)
        {
        }
    }
}
