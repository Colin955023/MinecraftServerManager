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
    public void ExtractValueAt_ShouldUnescapeInSinglePass(string content, string expected)
    {
        int next = 0;
        Assert.Equal(expected, ForgeTomlReader.ExtractValueAt(content, 0, ref next));
    }
}
