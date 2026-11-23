using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ServerPlayerLogParserTests
{
    [Theory]
    [InlineData("[12:00:00] [Server thread/INFO]: There are 2 of a max of 20 players online: Steve, Alex", "2", 20)]
    [InlineData("[12:00:00] [Server thread/INFO]: There are 2/30 players online: Steve, Alex", "2", 30)]
    public void TryParsePlayerList_ValidLine_ReturnsCountMaxAndPlayers(string line, string count, int max)
    {
        var snapshot = ServerPlayerLogParser.TryParsePlayerList(line);

        Assert.NotNull(snapshot);
        Assert.Equal(count, snapshot.OnlineCount);
        Assert.Equal(max, snapshot.MaxPlayers);
        Assert.Equal(["Steve", "Alex"], snapshot.Players);
    }

    [Fact]
    public void TryParsePlayerList_NoMaxAndNoPlayers_ReturnsNullMaxAndEmptyList()
    {
        var snapshot = ServerPlayerLogParser.TryParsePlayerList("[12:00:00] [Server thread/INFO]: There are 0 players online:");

        Assert.NotNull(snapshot);
        Assert.Equal("0", snapshot.OnlineCount);
        Assert.Null(snapshot.MaxPlayers);
        Assert.Empty(snapshot.Players);
    }

    [Theory]
    [InlineData("[12:00:01] [Server thread/INFO]: <Alice> There are 9 of a max of 20 players online: Bob")]
    [InlineData("[12:00:00] [Server thread/INFO]: Steve joined the game")]
    public void TryParsePlayerList_ChatOrUnrelatedLine_ReturnsNull(string line) =>
        Assert.Null(ServerPlayerLogParser.TryParsePlayerList(line));

    [Theory]
    [InlineData("[12:00:00] [Server thread/INFO]: Steve joined the game", "Steve")]
    [InlineData("[12:00:00] [Server thread/INFO] [minecraft/MinecraftServer]: Steve joined the game", "Steve")]
    public void TryParseJoin_ValidLine_ReturnsPlayer(string line, string player) =>
        Assert.Equal(player, ServerPlayerLogParser.TryParseJoin(line));

    [Theory]
    [InlineData("[12:00:00] [Server thread/INFO]: <Alice> hi: Bob joined the game")]
    [InlineData("[12:00:00] [Server thread/INFO]: Steve left the game")]
    public void TryParseJoin_ChatOrUnrelatedLine_ReturnsNull(string line) =>
        Assert.Null(ServerPlayerLogParser.TryParseJoin(line));

    [Fact]
    public void TryParseLeave_ValidLine_ReturnsPlayer() =>
        Assert.Equal("Steve", ServerPlayerLogParser.TryParseLeave("[12:00:00] [Server thread/INFO]: Steve left the game"));

    [Fact]
    public void TryParseLeave_ChatLine_ReturnsNull() =>
        Assert.Null(ServerPlayerLogParser.TryParseLeave("[12:00:00] [Server thread/INFO]: <Alice> ]: Bob left the game"));
}
