using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Windows.Foundation;

namespace MinecraftServerManager.App.Controls;

/// <summary>自動折行面板，依照可用寬度將子元素水平排列並依序換行</summary>
public sealed partial class WrapPanel : Panel
{
    public static readonly DependencyProperty ItemSpacingProperty =
        DependencyProperty.Register(
            nameof(ItemSpacing),
            typeof(double),
            typeof(WrapPanel),
            new PropertyMetadata(8.0, OnSpacingChanged));

    public static readonly DependencyProperty LineSpacingProperty =
        DependencyProperty.Register(
            nameof(LineSpacing),
            typeof(double),
            typeof(WrapPanel),
            new PropertyMetadata(8.0, OnSpacingChanged));

    public double ItemSpacing
    {
        get => (double)GetValue(ItemSpacingProperty);
        set => SetValue(ItemSpacingProperty, value);
    }

    public double LineSpacing
    {
        get => (double)GetValue(LineSpacingProperty);
        set => SetValue(LineSpacingProperty, value);
    }

    private static void OnSpacingChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is WrapPanel panel)
        {
            panel.InvalidateMeasure();
            panel.InvalidateArrange();
        }
    }

    protected override Size MeasureOverride(Size availableSize)
    {
        double curLineX = 0;
        double curLineY = 0;
        double curLineHeight = 0;
        double maxWidth = 0;

        double itemSpacing = ItemSpacing;
        double lineSpacing = LineSpacing;

        foreach (var child in Children)
        {
            child.Measure(availableSize);
            var sz = child.DesiredSize;

            if (curLineX + sz.Width > availableSize.Width && curLineX > 0)
            {
                curLineX = 0;
                curLineY += curLineHeight + lineSpacing;
                curLineHeight = 0;
            }

            maxWidth = Math.Max(maxWidth, curLineX + sz.Width);
            curLineX += sz.Width + itemSpacing;
            curLineHeight = Math.Max(curLineHeight, sz.Height);
        }

        return new Size(maxWidth, curLineY + curLineHeight);
    }

    protected override Size ArrangeOverride(Size finalSize)
    {
        double curLineX = 0;
        double curLineY = 0;
        double curLineHeight = 0;

        double itemSpacing = ItemSpacing;
        double lineSpacing = LineSpacing;

        foreach (var child in Children)
        {
            var sz = child.DesiredSize;

            if (curLineX + sz.Width > finalSize.Width && curLineX > 0)
            {
                curLineX = 0;
                curLineY += curLineHeight + lineSpacing;
                curLineHeight = 0;
            }

            child.Arrange(new Rect(curLineX, curLineY, sz.Width, sz.Height));
            curLineX += sz.Width + itemSpacing;
            curLineHeight = Math.Max(curLineHeight, sz.Height);
        }

        return finalSize;
    }
}
