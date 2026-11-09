using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Views;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ManageServerViewTests
{
    [Fact]
    public void ToggleColumnWidth_AlwaysAutoFitsToWidestItem()
    {
        double current = 250.0;
        double defaultWidth = 100.0;
        double assignedWidth = 0;

        ManageServerView.ToggleColumnWidth(
            () => current,
            w => assignedWidth = w,
            defaultWidth,
            ["01234567890123456789"]);

        // 20 個 ASCII 字元: 20 * 8.5 + 32 = 202.0（不再切回預設寬度）
        Assert.Equal(202.0, assignedWidth);
    }

    [Fact]
    public void ToggleColumnWidth_WithEmptyOrNullValues_KeepsDefaultWidth()
    {
        double current = 100.0;
        double defaultWidth = 100.0;
        double assignedWidth = 0;

        ManageServerView.ToggleColumnWidth(
            () => current,
            w => assignedWidth = w,
            defaultWidth,
            [null, string.Empty, "   "]);

        Assert.Equal(defaultWidth, assignedWidth);
    }

    [Fact]
    public void ToggleColumnWidth_WithAsciiValues_CalculatesEstimatedWidth()
    {
        double current = 100.0;
        double defaultWidth = 100.0;
        double assignedWidth = 0;

        ManageServerView.ToggleColumnWidth(
            () => current,
            w => assignedWidth = w,
            defaultWidth,
            ["0123456789"]);

        Assert.Equal(117.0, assignedWidth);
    }

    [Fact]
    public void ToggleColumnWidth_WithCjkValues_AppliesCjkWeight()
    {
        double current = 100.0;
        double defaultWidth = 100.0;
        double assignedWidth = 0;

        ManageServerView.ToggleColumnWidth(
            () => current,
            w => assignedWidth = w,
            defaultWidth,
            ["測試伺服器名稱說明文字"]);

        Assert.Equal(197.0, assignedWidth);
    }

    [Fact]
    public void ToggleColumnWidth_WhenWidthExceedsMaxCap_ClampsToMaxColumnWidth()
    {
        double current = 100.0;
        double defaultWidth = 100.0;
        double assignedWidth = 0;

        string veryLongCjk = new('伺', 100);

        ManageServerView.ToggleColumnWidth(
            () => current,
            w => assignedWidth = w,
            defaultWidth,
            [veryLongCjk]);

        Assert.Equal(SortableTableHeader.DefaultMaxColumnWidth, assignedWidth);
    }
}
