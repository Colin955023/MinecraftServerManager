using System.Globalization;
using System.Reflection;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Data;
using System.Windows.Input;
using System.Windows.Media;

namespace MinecraftServerManager.App.Behaviors;

/// <summary>
/// 提供 DataGrid 欄位標頭雙擊自動最適欄寬之附加行為（依資料來源全部資料列之單行最寬文字為基準）
/// </summary>
public static class DataGridHeaderAutoFitBehavior
{
    private static bool _handlerRegistered;
    [ThreadStatic]
    private static TextBlock? _evaluatorTextBlock;

    public static readonly DependencyProperty EnableHeaderDoubleClickAutoFitProperty =
        DependencyProperty.RegisterAttached(
            "EnableHeaderDoubleClickAutoFit",
            typeof(bool),
            typeof(DataGridHeaderAutoFitBehavior),
            new PropertyMetadata(false, OnEnableChanged));

    public static bool GetEnableHeaderDoubleClickAutoFit(DependencyObject obj) =>
        (bool)obj.GetValue(EnableHeaderDoubleClickAutoFitProperty);

    public static void SetEnableHeaderDoubleClickAutoFit(DependencyObject obj, bool value) =>
        obj.SetValue(EnableHeaderDoubleClickAutoFitProperty, value);

    private static void OnEnableChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if ((bool)e.NewValue && !_handlerRegistered)
        {
            _handlerRegistered = true;
            EventManager.RegisterClassHandler(
                typeof(DataGridColumnHeader),
                Control.MouseDoubleClickEvent,
                new MouseButtonEventHandler(OnHeaderMouseDoubleClick));
        }
    }

    private static void OnHeaderMouseDoubleClick(object sender, MouseButtonEventArgs e)
    {
        if (sender is not DataGridColumnHeader header || header.Column is null)
        {
            return;
        }

        var dataGrid = FindVisualParent<DataGrid>(header);
        if (dataGrid is null || !GetEnableHeaderDoubleClickAutoFit(dataGrid))
        {
            return;
        }

        e.Handled = true;
        AutoFitColumnToAllItems(dataGrid, header, header.Column);
    }

    private static void AutoFitColumnToAllItems(DataGrid dataGrid, DataGridColumnHeader header, DataGridColumn column)
    {
        header.Measure(new Size(double.PositiveInfinity, double.PositiveInfinity));
        double maxRequiredWidth = Math.Max(header.DesiredSize.Width, 50.0) + 16.0;

        var fontFamily = dataGrid.FontFamily ?? new FontFamily("Segoe UI");
        double fontSize = dataGrid.FontSize > 0 ? dataGrid.FontSize : 13.0;
        var typeface = new Typeface(fontFamily, FontStyles.Normal, FontWeights.Normal, FontStretches.Normal);
        double pixelsPerDip = VisualTreeHelper.GetDpi(dataGrid).PixelsPerDip;

        var binding = (column as DataGridBoundColumn)?.Binding as Binding;
        string? fallbackPath = column.SortMemberPath;

        _evaluatorTextBlock ??= new TextBlock();
        if (binding is not null)
        {
            _evaluatorTextBlock.SetBinding(TextBlock.TextProperty, binding);
        }

        try
        {
            foreach (object? item in dataGrid.Items)
            {
                if (item is null)
                {
                    continue;
                }

                string cellText = string.Empty;
                if (binding is not null)
                {
                    _evaluatorTextBlock.DataContext = item;
                    cellText = _evaluatorTextBlock.Text;
                }
                else if (!string.IsNullOrWhiteSpace(fallbackPath))
                {
                    var prop = item.GetType().GetProperty(fallbackPath, BindingFlags.Public | BindingFlags.Instance);
                    cellText = prop?.GetValue(item)?.ToString() ?? string.Empty;
                }

                if (string.IsNullOrEmpty(cellText))
                {
                    continue;
                }

                var formattedText = new FormattedText(
                    cellText,
                    CultureInfo.CurrentCulture,
                    FlowDirection.LeftToRight,
                    typeface,
                    fontSize,
                    Brushes.Black,
                    pixelsPerDip);

                double cellWidth = formattedText.WidthIncludingTrailingWhitespace + 28.0;
                if (cellWidth > maxRequiredWidth)
                {
                    maxRequiredWidth = cellWidth;
                }
            }
        }
        finally
        {
            if (binding is not null)
            {
                BindingOperations.ClearBinding(_evaluatorTextBlock, TextBlock.TextProperty);
                _evaluatorTextBlock.DataContext = null;
            }
        }

        if (column.MinWidth > 0)
        {
            maxRequiredWidth = Math.Max(maxRequiredWidth, column.MinWidth);
        }
        if (!double.IsNaN(column.MaxWidth) && !double.IsInfinity(column.MaxWidth))
        {
            maxRequiredWidth = Math.Min(maxRequiredWidth, column.MaxWidth);
        }

        column.Width = new DataGridLength(Math.Ceiling(maxRequiredWidth), DataGridLengthUnitType.Pixel);
    }

    private static T? FindVisualParent<T>(DependencyObject? child) where T : DependencyObject
    {
        while (child is not null)
        {
            if (child is T parent)
            {
                return parent;
            }
            child = VisualTreeHelper.GetParent(child);
        }
        return null;
    }
}
