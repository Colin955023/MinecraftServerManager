using System.Text;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests.Servers;

public sealed class ServerPropertiesStoreEdgeCaseTests : IDisposable
{
    private readonly TempDirectory _temp = new("msm-props-edge-");
    private readonly ServerPropertiesStore _store;

    public ServerPropertiesStoreEdgeCaseTests() => _store = new ServerPropertiesStore(_temp.FullName);

    public void Dispose() => _temp.Dispose();

    private string PropsPath(string server) => Path.Combine(_temp.FullName, server, "server.properties");

    private void CreateServer(string name) => Directory.CreateDirectory(Path.Combine(_temp.FullName, name));

    [Fact]
    public async Task Read_EmptyFile_ReturnsDefaultsWithEmptyStatus()
    {
        CreateServer("S");
        File.WriteAllText(PropsPath("S"), string.Empty);

        var snapshot = await _store.ReadAsync("S", TestContext.Current.CancellationToken);

        Assert.Equal(ServerPropertiesReadStatus.Empty, snapshot.Status);
        Assert.True(snapshot.Readable);
        Assert.Equal("25565", snapshot.Properties["server-port"]);
    }

    [Fact]
    public async Task Read_FileWithUtf8Bom_DoesNotPrefixFirstKey()
    {
        CreateServer("S");
        File.WriteAllBytes(PropsPath("S"), [.. Encoding.UTF8.GetPreamble(), .. Encoding.UTF8.GetBytes("motd=Hello\nserver-port=25570\n")]);

        var snapshot = await _store.ReadAsync("S", TestContext.Current.CancellationToken);

        Assert.Equal(ServerPropertiesReadStatus.Ok, snapshot.Status);
        Assert.Equal("Hello", snapshot.Properties["motd"]);
        Assert.Equal("25570", snapshot.Properties["server-port"]);
    }

    [Fact]
    public async Task Read_OversizedFile_IsReportedUnreadable()
    {
        CreateServer("S");
        File.WriteAllText(PropsPath("S"), new string('a', 2 * 1024 * 1024));

        var snapshot = await _store.ReadAsync("S", TestContext.Current.CancellationToken);

        Assert.Equal(ServerPropertiesReadStatus.Unreadable, snapshot.Status);
        Assert.False(snapshot.Readable);
        Assert.Empty(snapshot.Properties);
    }

    [Fact]
    public async Task Read_MissingServerDirectory_ReportsMissing()
    {
        var snapshot = await _store.ReadAsync("Nope", TestContext.Current.CancellationToken);

        Assert.Equal(ServerPropertiesReadStatus.Missing, snapshot.Status);
    }

    [Fact]
    public async Task Update_WhenFileUnreadable_FailsWithReadFailedAndKeepsFile()
    {
        CreateServer("S");
        File.WriteAllText(PropsPath("S"), new string('a', 2 * 1024 * 1024));

        var result = await _store.UpdateAsync("S", new Dictionary<string, string> { ["motd"] = "x" }, "any", TestContext.Current.CancellationToken);

        Assert.False(result.Success);
        Assert.Equal(ServerPropertiesUpdateError.ReadFailed, result.ErrorKind);
        Assert.Equal(2 * 1024 * 1024, new FileInfo(PropsPath("S")).Length);
    }

    [Fact]
    public async Task Update_PreservesExistingUnrelatedKeysAndWritesPatch()
    {
        CreateServer("S");
        File.WriteAllText(PropsPath("S"), "motd=Keep me\nlevel-name=world\n");
        var before = await _store.ReadAsync("S", TestContext.Current.CancellationToken);

        var result = await _store.UpdateAsync("S", new Dictionary<string, string> { ["difficulty"] = "hard" }, before.Revision, TestContext.Current.CancellationToken);

        Assert.True(result.Success);
        string text = File.ReadAllText(PropsPath("S"));
        Assert.Contains("motd=Keep me", text, StringComparison.Ordinal);
        Assert.Contains("level-name=world", text, StringComparison.Ordinal);
        Assert.Contains("difficulty=hard", text, StringComparison.Ordinal);
        Assert.NotEqual(before.Revision, result.Snapshot.Revision);
    }

    [Fact]
    public async Task Update_MissingFileCreatesItFromDefaultsPlusPatch()
    {
        CreateServer("S");
        var before = await _store.ReadAsync("S", TestContext.Current.CancellationToken);

        var result = await _store.UpdateAsync("S", new Dictionary<string, string> { ["motd"] = "New" }, before.Revision, TestContext.Current.CancellationToken);

        Assert.True(result.Success);
        Assert.True(File.Exists(PropsPath("S")));
        Assert.Equal("New", result.Snapshot.Properties["motd"]);
        Assert.Equal("25565", result.Snapshot.Properties["server-port"]);
    }
}
