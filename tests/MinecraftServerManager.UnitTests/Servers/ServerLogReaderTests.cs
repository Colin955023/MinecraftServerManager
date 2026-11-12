using System.Text;
using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests.Servers;

/// <summary>latest.log 尾端讀取服務測試（行數與位元組上限、截斷首行捨棄、色碼清洗、缺檔回傳空清單）</summary>
public sealed class ServerLogReaderTests : IDisposable
{
    private static readonly UTF8Encoding Utf8NoBom = new(false);
    private readonly TempDirectory _serverDirTemp = new("msm-logreader-");
    private readonly string _serverDir;
    private readonly string _logFile;

    public ServerLogReaderTests()
    {
        _serverDir = _serverDirTemp.FullName;
        Directory.CreateDirectory(Path.Combine(_serverDir, "logs"));
        _logFile = Path.Combine(_serverDir, "logs", "latest.log");
    }

    public void Dispose() => _serverDirTemp.Dispose();

    [Fact]
    public async Task MissingLogFile_ReturnsEmpty()
    {
        var reader = new ServerLogReader();

        var lines = await reader.ReadLatestLogTailAsync(_serverDir);

        Assert.Empty(lines);
    }

    [Fact]
    public async Task EmptyServerPath_ReturnsEmpty()
    {
        var reader = new ServerLogReader();

        var lines = await reader.ReadLatestLogTailAsync(string.Empty);

        Assert.Empty(lines);
    }

    [Fact]
    public async Task ReadsAllLines_WhenWithinLimits_AndStripsColorCodes()
    {
        await File.WriteAllTextAsync(_logFile, "\u001b[32mLine 1\u001b[0m\n§aLine 2\nLine 3\n", Utf8NoBom);
        var reader = new ServerLogReader();

        var lines = await reader.ReadLatestLogTailAsync(_serverDir);

        Assert.Equal(["Line 1", "Line 2", "Line 3"], lines);
    }

    [Fact]
    public async Task KeepsOnlyLastLines_WhenExceedingLineLimit()
    {
        await File.WriteAllLinesAsync(_logFile, Enumerable.Range(1, 10).Select(static i => $"L{i}"), Utf8NoBom);
        var reader = new ServerLogReader(maxLines: 3);

        var lines = await reader.ReadLatestLogTailAsync(_serverDir);

        Assert.Equal(["L8", "L9", "L10"], lines);
    }

    [Fact]
    public async Task DropsPartialFirstLine_WhenTruncatedByByteLimit()
    {
        await File.WriteAllTextAsync(_logFile, "AAAAAAAAAA\nBBBB\nCCCC\n", Utf8NoBom);
        var reader = new ServerLogReader(maxBytesToRead: 12);

        var lines = await reader.ReadLatestLogTailAsync(_serverDir);

        // 尾端 12 位元組為 "A\nBBBB\nCCCC\n"，第一行不完整須捨棄
        Assert.Equal(["BBBB", "CCCC"], lines);
    }

    [Fact]
    public async Task ReadsWhileFileIsOpenedForWriting()
    {
        await File.WriteAllTextAsync(_logFile, "Running\n", Utf8NoBom);
        using var writer = new FileStream(_logFile, FileMode.Open, FileAccess.ReadWrite, FileShare.ReadWrite);
        var reader = new ServerLogReader();

        var lines = await reader.ReadLatestLogTailAsync(_serverDir);

        Assert.Equal(["Running"], lines);
    }
}
