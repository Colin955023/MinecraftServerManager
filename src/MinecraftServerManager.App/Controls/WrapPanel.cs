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

    /// <summary>子項以無限高度量測；摺疊子項不佔空間</summary>
    protected override Size MeasureOverride(Size availableSize)
    {
        var childConstraint = new Size(availableSize.Width, double.PositiveInfinity);
        double maxWidth = 0;
        double totalHeight = 0;
        double currentLineWidth = 0;
        double currentLineHeight = 0;
        bool lineHasItem = false;

        foreach (var child in Children)
        {
            if (child.Visibility != Visibility.Visible)
            {
                continue;
            }

            child.Measure(childConstraint);
            Size size = child.DesiredSize;

            if (lineHasItem && currentLineWidth + ItemSpacing + size.Width > availableSize.Width)
            {
                maxWidth = Math.Max(maxWidth, currentLineWidth);
                totalHeight += currentLineHeight + LineSpacing;
                currentLineWidth = size.Width;
                currentLineHeight = size.Height;
            }
            else
            {
                currentLineWidth = lineHasItem ? currentLineWidth + ItemSpacing + size.Width : size.Width;
                currentLineHeight = Math.Max(currentLineHeight, size.Height);
                lineHasItem = true;
            }
        }

        if (lineHasItem)
        {
            maxWidth = Math.Max(maxWidth, currentLineWidth);
            totalHeight += currentLineHeight;
        }

        return new Size(maxWidth, totalHeight);
    }

    /// <summary>逐行以行高安排子項，使子項的 VerticalAlignment 在行內生效</summary>
    protected override Size ArrangeOverride(Size finalSize)
    {
        double y = 0;
        int i = 0;
        int count = Children.Count;

        while (i < count)
        {
            while (i < count && Children[i].Visibility != Visibility.Visible)
            {
                i++;
            }

            if (i >= count)
            {
                break;
            }

            int lineStart = i;
            double lineWidth = 0;
            double lineHeight = 0;
            bool lineHasItem = false;
            int lineEnd = i;

            for (int j = i; j < count; j++)
            {
                var child = Children[j];
                if (child.Visibility != Visibility.Visible)
                {
                    lineEnd = j + 1;
                    continue;
                }

                double w = child.DesiredSize.Width;
                double h = child.DesiredSize.Height;

                if (lineHasItem && lineWidth + ItemSpacing + w > finalSize.Width)
                {
                    break;
                }

                lineWidth = lineHasItem ? lineWidth + ItemSpacing + w : w;
                lineHeight = Math.Max(lineHeight, h);
                lineHasItem = true;
                lineEnd = j + 1;
            }

            double x = 0;
            for (int k = lineStart; k < lineEnd; k++)
            {
                var child = Children[k];
                if (child.Visibility != Visibility.Visible)
                {
                    continue;
                }

                child.Arrange(new Rect(x, y, child.DesiredSize.Width, lineHeight));
                x += child.DesiredSize.Width + ItemSpacing;
            }

            y += lineHeight + LineSpacing;
            i = lineEnd;
        }

        return finalSize;
    }
}
