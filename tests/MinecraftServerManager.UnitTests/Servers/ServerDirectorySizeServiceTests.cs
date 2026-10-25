using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests.Servers;

public sealed class ServerDirectorySizeServiceTests : IDisposable
{
    private readonly string _testDir;
    private readonly ServerDirectorySizeService _sizeService;

    public ServerDirectorySizeServiceTests()
    {
        _testDir = Path.Combine(Path.GetTempPath(), "msm-dirsize-tests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_testDir);
        _sizeService = new ServerDirectorySizeService(cacheDuration: TimeSpan.FromSeconds(5));
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_testDir))
            {
                Directory.Delete(_testDir, recursive: true);
            }
        }
        catch (Exception ex) { System.Diagnostics.Debug.WriteLine($"測試清理忽略例外: {ex.Message}"); }
    }

    [Fact]
    public async Task CalculateServerSizeAsync_NonExistentDirectory_ReturnsZero()
    {
        string nonExistent = Path.Combine(_testDir, "DoesNotExist");
        long size = await _sizeService.CalculateServerSizeAsync(nonExistent);
        Assert.Equal(0, size);
    }

    [Fact]
    public async Task CalculateServerSizeAsync_CalculatesFilesAndExcludesBackups()
    {
        // 建立常規檔案
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

        long totalSize = await _sizeService.CalculateServerSizeAsync(_testDir);

        // 預期為 100 + 50 + 200 = 350 位元組（排除 backups 的 1000 位元組）
        Assert.Equal(350, totalSize);
    }

    [Fact]
    public async Task CalculateServerSizeAsync_UsesCacheOnSubsequentCalls()
    {
        string file = Path.Combine(_testDir, "data.bin");
        File.WriteAllBytes(file, new byte[500]);

        long initialSize = await _sizeService.CalculateServerSizeAsync(_testDir);
        Assert.Equal(500, initialSize);

        // 在目錄中新增檔案（不清除快取的情況下呼叫）
        File.WriteAllBytes(Path.Combine(_testDir, "extra.bin"), new byte[300]);

        long cachedSize = await _sizeService.CalculateServerSizeAsync(_testDir);
        // 應該命中快取，仍為 500
        Assert.Equal(500, cachedSize);

        // 失效快取後重新計算
        _sizeService.InvalidateCache(_testDir);
        long refreshedSize = await _sizeService.CalculateServerSizeAsync(_testDir);
        Assert.Equal(800, refreshedSize);
    }

    [Fact]
    public async Task CalculateServerSizeAsync_HonorsCancellation()
    {
        using var cts = new CancellationTokenSource();
        cts.Cancel();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
            _sizeService.CalculateServerSizeAsync(_testDir, cts.Token));
    }

    [Fact]
    public async Task CalculateServerSizeAsync_FailedCalculation_DoesNotCacheAndReturnsNegativeOne()
    {
        // 建立一個嚴格限制最大項目數為 2 的服務實例
        var strictService = new ServerDirectorySizeService(maxEntries: 2);

        // 在目錄中建立 5 個檔案以超出上限
        string overflowDir = Path.Combine(_testDir, "overflowDir");
        Directory.CreateDirectory(overflowDir);
        for (int i = 0; i < 5; i++)
        {
            File.WriteAllText(Path.Combine(overflowDir, $"file_{i}.dat"), "data");
        }

        // 走訪超限會捕捉例外並回傳 -1L
        long result = await strictService.CalculateServerSizeAsync(overflowDir);
        Assert.Equal(-1, result);

        // 驗證失敗結果未被快取：清理檔案至 1 個檔案後再次呼叫，應能即時重新計算成功
        for (int i = 1; i < 5; i++)
        {
            File.Delete(Path.Combine(overflowDir, $"file_{i}.dat"));
        }

        long refreshedResult = await strictService.CalculateServerSizeAsync(overflowDir);
        Assert.Equal(4, refreshedResult); // 1 個檔案長度為 4 位元組 ("data")
    }

    [Fact]
    public void FormatServerSize_ReturnsExpectedLabels()
    {
        Assert.Equal("無法計算", _sizeService.FormatServerSize(-1));
        Assert.Equal("無法計算", _sizeService.FormatServerSize(-100));
        Assert.Equal("-", _sizeService.FormatServerSize(0));
        Assert.Equal("1.0 KiB", _sizeService.FormatServerSize(1024));
    }
}
