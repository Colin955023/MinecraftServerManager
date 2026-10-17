using MinecraftServerManager.Core.Mods;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class ModHelpersTests
{
    [Theory]
    [InlineData("Normal text", "Normal text")]
    [InlineData("\u001b[32mGreen\u001b[0m", "Green")]
    [InlineData("\u001b[1;31mBold Red\u001b[0m", "Bold Red")]
    [InlineData("§aGreen §cRed §lBold§r Normal", "Green Red Bold Normal")]
    [InlineData("§x§1§2§3§4§5§6Custom Hex Color", "Custom Hex Color")]
    [InlineData("\\u00a7eYellow\\u00a7r Text", "Yellow Text")]
    [InlineData("\\u001b[31mRed\\u001b[0m", "Red")]
    [InlineData("", "")]
    [InlineData(null, "")]
    public void StripColorAndFormattingCodesShouldCleanCorrectly(string? input, string expected)
    {
        string actual = ModHelpers.StripColorAndFormattingCodes(input);
        Assert.Equal(expected, actual);
    }

    [Theory]
    [InlineData("Connector-1.0.0-beta.46+1.20.1.jar", "Connector")]
    [InlineData("jei-1.20.1-forge-15.2.0.27.jar", "jei")]
    [InlineData("Jade-1.20.1-Forge-11.8.0.jar", "Jade")]
    [InlineData("fabric-api-0.92.0+1.20.1.jar", "api")]
    [InlineData("appleskin-fabric-mc1.20.1-2.5.1.jar", "appleskin")]
    public void NormalizeModSearchQueryShouldProduceCleanKeywords(string input, string expected)
    {
        string actual = ModHelpers.NormalizeModSearchQuery(input);
        Assert.Equal(expected, actual);
    }
}
