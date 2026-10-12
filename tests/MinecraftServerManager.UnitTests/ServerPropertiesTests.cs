using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class ServerPropertiesTests : IDisposable
{
    private readonly string _testRoot;

    public ServerPropertiesTests()
    {
        _testRoot = Path.Combine(Path.GetTempPath(), "msm-props-tests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_testRoot);
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_testRoot))
            {
                Directory.Delete(_testRoot, recursive: true);
            }
        }
        catch
        {
        }
    }

    [Fact]
    public void CodecParsesBasicAndEscapedProperties()
    {
        string raw = @"
# 伺服器設定範例
server-port=25565
motd=A\ Minecraft\:\ Server\u0021
difficulty:normal
allow-flight=true
";
        var parsed = PropertiesDocumentCodec.Parse(raw);

        Assert.Equal("25565", parsed["server-port"]);
        Assert.Equal("A Minecraft: Server!", parsed["motd"]);
        Assert.Equal("normal", parsed["difficulty"]);
        Assert.Equal("true", parsed["allow-flight"]);
    }

    [Fact]
    public void CodecHandlesMultilineContinuation()
    {
        string raw = @"
motd=Line 1 \
     Line 2
server-port=25565
";
        var parsed = PropertiesDocumentCodec.Parse(raw);

        Assert.Equal("Line 1      Line 2", parsed["motd"]);
        Assert.Equal("25565", parsed["server-port"]);
    }

    [Fact]
    public void CodecSerializesAndRoundTrips()
    {
        var original = new Dictionary<string, string>
        {
            ["server-port"] = "25565",
            ["motd"] = "Hello World!",
            ["difficulty"] = "hard",
        };

        string text = PropertiesDocumentCodec.Serialize(original);
        var parsed = PropertiesDocumentCodec.Parse(text);

        Assert.Equal(original["server-port"], parsed["server-port"]);
        Assert.Equal(original["motd"], parsed["motd"]);
        Assert.Equal(original["difficulty"], parsed["difficulty"]);
    }

    [Fact]
    public async Task StoreReturnsDefaultWhenFileIsMissing()
    {
        var store = new ServerPropertiesStore(_testRoot);
        string serverDir = Path.Combine(_testRoot, "test-server");
        Directory.CreateDirectory(serverDir);

        var snapshot = await store.ReadAsync("test-server");

        Assert.Equal(ServerPropertiesReadStatus.Missing, snapshot.Status);
        Assert.True(snapshot.Readable);
        Assert.Equal("25565", snapshot.GetProperty("server-port"));
    }

    [Fact]
    public async Task StoreUpdatesAndDetectsRevisionConflict()
    {
        var store = new ServerPropertiesStore(_testRoot);
        string serverDir = Path.Combine(_testRoot, "test-server");
        Directory.CreateDirectory(serverDir);

        // 初始建立
        var initial = await store.ReadAsync("test-server");
        var update1 = await store.UpdateAsync(
            "test-server",
            new Dictionary<string, string> { ["server-port"] = "25570", ["difficulty"] = "hard" },
            initial.Revision);

        Assert.True(update1.Success);
        Assert.Equal("25570", update1.Snapshot.GetProperty("server-port"));
        Assert.Equal("hard", update1.Snapshot.GetProperty("difficulty"));

        // 使用舊 revision 嘗試更新，預期發生衝突
        var conflict = await store.UpdateAsync(
            "test-server",
            new Dictionary<string, string> { ["server-port"] = "25580" },
            initial.Revision);

        Assert.False(conflict.Success);
        Assert.Equal(ServerPropertiesUpdateError.Conflict, conflict.ErrorKind);
    }

    [Fact]
    public async Task StoreRejectsInvalidPortRange()
    {
        var store = new ServerPropertiesStore(_testRoot);
        string serverDir = Path.Combine(_testRoot, "test-server");
        Directory.CreateDirectory(serverDir);

        var initial = await store.ReadAsync("test-server");
        var invalidPort = await store.UpdateAsync(
            "test-server",
            new Dictionary<string, string> { ["server-port"] = "999999" },
            initial.Revision);

        Assert.False(invalidPort.Success);
        Assert.Equal(ServerPropertiesUpdateError.Invalid, invalidPort.ErrorKind);
        Assert.Contains("必須在 1 到 65534 之間", invalidPort.Message);
    }
}
