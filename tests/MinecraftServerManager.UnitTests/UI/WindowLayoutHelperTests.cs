using MinecraftServerManager.App.Services;
using Windows.Graphics;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class WindowLayoutHelperTests
{
    private static readonly RectInt32 WorkArea = new(0, 0, 1920, 1040);

    [Theory]
    [InlineData(1350, 1.0, 1350)]
    [InlineData(1350, 1.25, 1688)]
    [InlineData(901, 1.5, 1352)]
    public void ToPixels_FractionalValue_RoundsToNearest(int dip, double scale, int expected) =>
        Assert.Equal(expected, WindowLayoutHelper.ToPixels(dip, scale));

    [Fact]
    public void IsTitleBarVisible_InsideWorkArea_ReturnsTrue() =>
        Assert.True(WindowLayoutHelper.IsTitleBarVisible(new RectInt32(100, 100, 800, 600), WorkArea, 1.0));

    [Theory]
    [InlineData(1850, 100)] // 只剩 70 像素在右緣內，無法拖曳
    [InlineData(100, -20)]  // 標題列高於工作區上緣
    [InlineData(100, 1100)] // 位於工作區下方
    [InlineData(2500, 100)] // 位於其他螢幕
    public void IsTitleBarVisible_OutsideOrClipped_ReturnsFalse(int x, int y) =>
        Assert.False(WindowLayoutHelper.IsTitleBarVisible(new RectInt32(x, y, 800, 600), WorkArea, 1.0));

    [Fact]
    public void ResolveRestoreBounds_MultipleDisplays_UsesContainingDisplayScale()
    {
        // 主螢幕 100%（0～1920），副螢幕 150%（1920～4800）
        DisplayMetrics[] displays =
        [
            new(new RectInt32(0, 0, 1920, 1080), new RectInt32(0, 0, 1920, 1040), 1.0),
            new(new RectInt32(1920, 0, 2880, 1620), new RectInt32(1920, 0, 2880, 1580), 1.5),
        ];

        var result = WindowLayoutHelper.ResolveRestoreBounds(displays, 1920, 100, 1000, 600);

        Assert.NotNull(result);
        Assert.Equal(new RectInt32(1920, 100, 1500, 900), result.Value.Bounds);
        Assert.Equal(1.5, result.Value.Scale);
    }

    [Theory]
    [InlineData(-3000, 100)] // 已拔除的螢幕
    [InlineData(4790, 100)]  // 標題列幾乎全在右緣外
    public void ResolveRestoreBounds_NoVisibleDisplay_ReturnsNull(int x, int y)
    {
        DisplayMetrics[] displays =
        [
            new(new RectInt32(0, 0, 1920, 1080), new RectInt32(0, 0, 1920, 1040), 1.0),
            new(new RectInt32(1920, 0, 2880, 1620), new RectInt32(1920, 0, 2880, 1580), 1.5),
        ];

        Assert.Null(WindowLayoutHelper.ResolveRestoreBounds(displays, x, y, 1000, 600));
    }

    [Fact]
    public void IsTitleBarVisible_ScaledDisplay_ScalesMinimumWidth()
    {
        // 130 像素在 1.0 倍足夠（≥120），在 1.5 倍不足（<180）
        var window = new RectInt32(1790, 100, 800, 600);
        Assert.True(WindowLayoutHelper.IsTitleBarVisible(window, WorkArea, 1.0));
        Assert.False(WindowLayoutHelper.IsTitleBarVisible(window, WorkArea, 1.5));
    }
}
