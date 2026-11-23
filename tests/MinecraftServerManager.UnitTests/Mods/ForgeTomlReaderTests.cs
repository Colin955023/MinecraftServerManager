using MinecraftServerManager.Infrastructure.Mods;

namespace MinecraftServerManager.UnitTests.Mods;

public sealed class ForgeTomlReaderTests
{
    [Theory]
    [InlineData("\"C:\\\\new\"", "C:\\new")]
    [InlineData("\"a\\nb\"", "a\nb")]
    [InlineData("\"tab\\there\"", "tab\there")]
    [InlineData("\"say \\\"hi\\\"\"", "say \"hi\"")]
    [InlineData("\"keep \\u0041\"", "keep \\u0041")]
    [InlineData("\"plain\"", "plain")]
    public void ExtractValueAt_EscapedValue_UnescapesInSinglePass(string content, string expected)
    {
        int next = 0;
        Assert.Equal(expected, ForgeTomlReader.ExtractValueAt(content, 0, ref next));
    }

    [Fact]
    public void ExtractValueAt_UnclosedQuote_AdvancesToEnd()
    {
        const string content = "\"unterminated\nnext=1";
        int next = 0;
        ForgeTomlReader.ExtractValueAt(content, 0, ref next);
        Assert.Equal(content.Length, next);
    }

    [Fact]
    public void ExtractMinecraftDependency_CommentsAndInlineHeaders_IgnoresThem()
    {
        const string toml = """
        description="mentions [[dependencies.fake]] inline"
        # [[dependencies.commented]]
        # modId="minecraft"
        # versionRange="[1.0,)"
        [[dependencies.real]]
        modId="minecraft"
        versionRange="[1.20.1,1.21)"
        """;

        Assert.Equal("[1.20.1,1.21)", ForgeTomlReader.ExtractMinecraftDependency(toml));
    }
}
