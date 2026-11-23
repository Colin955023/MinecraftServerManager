using MinecraftServerManager.App.Services;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class AccentColorServiceTests
{
    private static double Luminance(Windows.UI.Color c)
    {
        static double Linear(byte v)
        {
            double x = v / 255d;
            return x <= 0.04045 ? x / 12.92 : Math.Pow((x + 0.055) / 1.055, 2.4);
        }

        return (0.2126 * Linear(c.R)) + (0.7152 * Linear(c.G)) + (0.0722 * Linear(c.B));
    }

    private static double Contrast(Windows.UI.Color a, Windows.UI.Color b)
    {
        double la = Luminance(a);
        double lb = Luminance(b);
        return (Math.Max(la, lb) + 0.05) / (Math.Min(la, lb) + 0.05);
    }

    [Fact]
    public void ParseColor_ValidHex_RoundTripsThroughToHex()
    {
        var parsed = AccentColorService.ParseColor("#3A7BD5");

        Assert.NotNull(parsed);
        Assert.Equal(255, parsed.Value.A);
        Assert.Equal(0x3A, parsed.Value.R);
        Assert.Equal(0x7B, parsed.Value.G);
        Assert.Equal(0xD5, parsed.Value.B);
        Assert.Equal("#3A7BD5", AccentColorService.ToHex(parsed.Value));
    }

    [Theory]
    [InlineData("  #3a7bd5  ", "#3A7BD5")]
    [InlineData("3A7BD5", "#3A7BD5")]
    public void ParseColor_LenientInput_Normalizes(string input, string expected) =>
        Assert.Equal(expected, AccentColorService.ToHex(AccentColorService.ParseColor(input)!.Value));

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("#ZZZZZZ")]
    [InlineData("#FFF")]
    [InlineData("#FF112233")]
    public void ParseColor_InvalidInput_ReturnsNull(string? input) =>
        Assert.Null(AccentColorService.ParseColor(input));

    [Theory]
    [InlineData("#FFB900", "#000000")]
    [InlineData("#FFFFFF", "#000000")]
    [InlineData("#0F2A5C", "#FFFFFF")]
    [InlineData("#000000", "#FFFFFF")]
    public void GetReadableForeground_Background_PicksHigherContrast(string background, string expected)
    {
        var color = AccentColorService.ParseColor(background);
        Assert.NotNull(color);
        Assert.Equal(expected, AccentColorService.ToHex(AccentColorService.GetReadableForeground(color.Value)));
    }

    [Theory]
    [InlineData("#284375", "#2C2C2C", "#8998B3")]
    [InlineData("#FFB900", "#F3F3F3", "#8C6600")]
    [InlineData("#0F2A5C", "#F3F3F3", "#0F2A5C")]
    [InlineData("#4CC2FF", "#2C2C2C", "#4CC2FF")]
    public void EnsureTextContrast_LowContrastText_BlendsToExpected(string text, string background, string expected)
    {
        var textColor = AccentColorService.ParseColor(text);
        var backgroundColor = AccentColorService.ParseColor(background);
        Assert.NotNull(textColor);
        Assert.NotNull(backgroundColor);
        Assert.Equal(expected, AccentColorService.ToHex(AccentColorService.EnsureTextContrast(textColor.Value, backgroundColor.Value)));
    }

    [Theory]
    [InlineData("#808080", "#F3F3F3")]
    [InlineData("#808080", "#2C2C2C")]
    [InlineData("#FFFF00", "#FFFFFF")]
    [InlineData("#000080", "#000000")]
    public void EnsureTextContrast_AnyInput_ReachesWcagAA(string text, string background)
    {
        var bg = AccentColorService.ParseColor(background)!.Value;

        var result = AccentColorService.EnsureTextContrast(AccentColorService.ParseColor(text)!.Value, bg);

        Assert.True(Contrast(result, bg) >= 4.5, $"{AccentColorService.ToHex(result)} 對 {background} 對比不足");
    }

    [Fact]
    public void ApplyAccentColor_CustomThenSystem_FiresAccentColorChangedEachTime()
    {
        var service = new AccentColorService(static action => action());
        int fired = 0;
        service.AccentColorChanged += () => fired++;
        try
        {
            service.ApplyAccentColor("#112233");
            service.ApplyAccentColor(null);

            Assert.Equal(2, fired);
        }
        finally
        {
            service.ApplyAccentColor(null);
            service.Dispose();
        }
    }

    [Fact]
    public void GetSystemAccentColor_Always_ReturnsOpaqueColor()
    {
        using var service = new AccentColorService(static action => action());

        Assert.Equal(255, service.GetSystemAccentColor().A);
    }

    [Fact]
    public void Dispose_CalledTwice_DoesNotThrow()
    {
        var service = new AccentColorService(static action => action());

        Assert.Null(Record.Exception(() =>
        {
            service.Dispose();
            service.Dispose();
        }));
    }
}
