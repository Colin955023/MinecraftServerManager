using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.UnitTests.Servers;

public sealed class ServerDirectorySizeServiceTests : IDisposable
{
    private readonly TempDirectory _testDirTemp = new("msm-dirsize-tests-");
    private readonly string _testDir;
    private readonly ServerDirectorySizeService _sizeService;

    public ServerDirectorySizeServiceTests()
    {
        _testDir = _testDirTemp.FullName;
        _sizeService = new ServerDirectorySizeService(TimeSpan.FromSeconds(5), TimeProvider.System);
    }

    public void Dispose() => _testDirTemp.Dispose();

    [Fact]
    public async Task CalculateServerSizeAsync_NonExistentDirectory_ReturnsZero()
    {
        string nonExistent = Path.Combine(_testDir, "DoesNotExist");
        long size = await _sizeService.CalculateServerSizeAsync(nonExistent, TestContext.Current.CancellationToken);
        Assert.Equal(0, size);
    }

    [Fact]
    public async Task CalculateServerSizeAsync_WithBackups_ExcludesBackups()
    {
        // 建立一般檔案
        File.WriteAllText(Path.Combine(_testDir, "server.jar"), new string('a', 100));
        File.WriteAllText(Path.Combine(_testDir, "server.properties"), new string('b', 50));

        // 建立子目錄與檔案
        string worldDir = Path.Combine(_testDir, "world");
        Directory.CreateDirectory(worldDir);
        File.WriteAllText(Path.Combine(worldDir, "level.dat"), new string('c', 200));

        // 建立 backups 目錄與檔案（應被排除）
        string backupsDir = Path.Combine(_testDir, "backups");
        Directory.CreateDirectory(backupsDir);
        File.WriteAllText(Path.Combine(backupsDir, "backup-1.zip"), new string('d', 1000));

        long totalSize = await _sizeService.CalculateServerSizeAsync(_testDir, TestContext.Current.CancellationToken);

        // 預期為 100 + 50 + 200 = 350 位元組（排除 backups 的 1000 位元組）
        Assert.Equal(350, totalSize);
    }

    [Fact]
    public async Task CalculateServerSizeAsync_RepeatedCall_UsesCache()
    {
        string file = Path.Combine(_testDir, "data.bin");
        File.WriteAllBytes(file, new byte[500]);

        long initialSize = await _sizeService.CalculateServerSizeAsync(_testDir, TestContext.Current.CancellationToken);
        Assert.Equal(500, initialSize);

        // 在目錄中新增檔案
        File.WriteAllBytes(Path.Combine(_testDir, "extra.bin"), new byte[300]);

        long cachedSize = await _sizeService.CalculateServerSizeAsync(_testDir, TestContext.Current.CancellationToken);
        // 應該命中快取，仍為 500
        Assert.Equal(500, cachedSize);
    }

    [Fact]
    public async Task CalculateServerSizeAsync_Cancelled_Throws()
    {
        using var cts = new CancellationTokenSource();
        cts.Cancel();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
            _sizeService.CalculateServerSizeAsync(_testDir, cts.Token));
    }

    [Fact]
    public async Task CalculateServerSizeAsync_FailedCalculation_DoesNotCacheAndReturnsNegativeOne()
    {
        // 建立一個嚴格限制最大項目數為 2 的服務執行個體
        var strictService = new ServerDirectorySizeService(TimeSpan.FromSeconds(5), TimeProvider.System, maxEntries: 2);

        // 在目錄中建立 5 個檔案以超出上限
        string overflowDir = Path.Combine(_testDir, "overflowDir");
        Directory.CreateDirectory(overflowDir);
        for (int i = 0; i < 5; i++)
        {
            File.WriteAllText(Path.Combine(overflowDir, $"file_{i}.dat"), "data");
        }

        // 走訪超限會攔截例外並回傳 -1L
        long result = await strictService.CalculateServerSizeAsync(overflowDir, TestContext.Current.CancellationToken);
        Assert.Equal(-1, result);

        // 驗證失敗結果未被快取：清理檔案至 1 個檔案後再次呼叫，應能即時重新計算成功
        for (int i = 1; i < 5; i++)
        {
            File.Delete(Path.Combine(overflowDir, $"file_{i}.dat"));
        }

        long refreshedResult = await strictService.CalculateServerSizeAsync(overflowDir, TestContext.Current.CancellationToken);
        Assert.Equal(4, refreshedResult); // 1 個檔案長度為 4 位元組 ("data")
    }

    [Fact]
    public void FormatBytes_VariousSizes_ReturnsLabels()
    {
        Assert.Equal("0 B", Core.Utilities.UnitFormatter.FormatBytes(0));
        Assert.Equal("512 B", Core.Utilities.UnitFormatter.FormatBytes(512));
        Assert.Equal("1.0 KiB", Core.Utilities.UnitFormatter.FormatBytes(1024));
        Assert.Equal("1.0 MiB", Core.Utilities.UnitFormatter.FormatBytes(1024 * 1024));
    }

    [Fact]
    public async Task CalculateServerSizeAsync_NestedBackupsFolder_CountsIt()
    {
        File.WriteAllBytes(Path.Combine(_testDir, "server.jar"), new byte[100]);
        string nestedBackups = Path.Combine(_testDir, "config", "backups");
        Directory.CreateDirectory(nestedBackups);
        File.WriteAllBytes(Path.Combine(nestedBackups, "data.json"), new byte[40]);
        Directory.CreateDirectory(Path.Combine(_testDir, "backups"));
        File.WriteAllBytes(Path.Combine(_testDir, "backups", "b.zip"), new byte[1000]);

        Assert.Equal(140, await _sizeService.CalculateServerSizeAsync(_testDir + Path.DirectorySeparatorChar, TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task CalculateServerSizeAsync_ConcurrentRequests_ShareResult()
    {
        File.WriteAllBytes(Path.Combine(_testDir, "server.jar"), new byte[64]);

        long[] sizes = await Task.WhenAll(Enumerable.Range(0, 8).Select(_ => _sizeService.CalculateServerSizeAsync(_testDir, TestContext.Current.CancellationToken)));

        Assert.All(sizes, static size => Assert.Equal(64, size));
    }

    [Fact]
    public async Task CalculateServerSizeAsync_EvictsOldestPathWhenCacheIsFull()
    {
        var boundedService = new ServerDirectorySizeService(TimeSpan.FromHours(1), TimeProvider.System);
        string firstPath = Path.Combine(_testDir, "server-0");
        Directory.CreateDirectory(firstPath);
        string firstFile = Path.Combine(firstPath, "data.bin");
        File.WriteAllBytes(firstFile, new byte[1]);
        Assert.Equal(1, await boundedService.CalculateServerSizeAsync(firstPath, TestContext.Current.CancellationToken));

        for (int i = 1; i < 256; i++)
        {
            string serverPath = Path.Combine(_testDir, $"server-{i}");
            Directory.CreateDirectory(serverPath);
            File.WriteAllBytes(Path.Combine(serverPath, "data.bin"), new byte[i + 1]);
            Assert.Equal(i + 1, await boundedService.CalculateServerSizeAsync(serverPath, TestContext.Current.CancellationToken));
        }

        string lastPath = Path.Combine(_testDir, "server-256");
        Directory.CreateDirectory(lastPath);
        File.WriteAllBytes(Path.Combine(lastPath, "data.bin"), new byte[257]);
        Assert.Equal(257, await boundedService.CalculateServerSizeAsync(lastPath, TestContext.Current.CancellationToken));

        File.WriteAllBytes(firstFile, new byte[2]);
        Assert.Equal(2, await boundedService.CalculateServerSizeAsync(firstPath, TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task CalculateServerSizeAsync_ExpiredEntryIsRecalculated()
    {
        string serverPath = Path.Combine(_testDir, "expiring-server");
        Directory.CreateDirectory(serverPath);
        string filePath = Path.Combine(serverPath, "data.bin");
        File.WriteAllBytes(filePath, new byte[1]);
        var timeProvider = new ManualTimeProvider();
        var service = new ServerDirectorySizeService(TimeSpan.FromSeconds(5), timeProvider);

        Assert.Equal(1, await service.CalculateServerSizeAsync(serverPath, TestContext.Current.CancellationToken));
        timeProvider.Advance(TimeSpan.FromSeconds(6));
        File.WriteAllBytes(filePath, new byte[2]);

        Assert.Equal(2, await service.CalculateServerSizeAsync(serverPath, TestContext.Current.CancellationToken));
    }

    private sealed class ManualTimeProvider : TimeProvider
    {
        private long _timestamp;

        public override long TimestampFrequency => TimeSpan.TicksPerSecond;

        public override long GetTimestamp() => Interlocked.Read(ref _timestamp);

        public void Advance(TimeSpan duration) => Interlocked.Add(ref _timestamp, duration.Ticks);
    }
}
