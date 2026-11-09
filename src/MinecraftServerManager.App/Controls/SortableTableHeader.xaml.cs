using System.ComponentModel;
using Microsoft.UI.Input;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;

namespace MinecraftServerManager.App.Controls;

/// <summary>
/// 支援自然排序、方向指示、右側垂直分隔線、拖曳手動調整欄寬與點兩下自動對齊最寬項目之表頭控制項
/// </summary>
public sealed partial class SortableTableHeader : UserControl
{
    public const double DefaultMinColumnWidth = 48.0;
    public const double DefaultMaxColumnWidth = 1200.0;

    public static readonly DependencyProperty TextProperty =
        DependencyProperty.Register(
            nameof(Text),
            typeof(string),
            typeof(SortableTableHeader),
            new PropertyMetadata(string.Empty, OnTextChanged));

    public static readonly DependencyProperty SortPropertyNameProperty =
        DependencyProperty.Register(
            nameof(SortPropertyName),
            typeof(string),
            typeof(SortableTableHeader),
            new PropertyMetadata(string.Empty));

    public static readonly DependencyProperty CurrentSortPropertyProperty =
        DependencyProperty.Register(
            nameof(CurrentSortProperty),
            typeof(string),
            typeof(SortableTableHeader),
            new PropertyMetadata(string.Empty, OnSortStateChanged));

    public static readonly DependencyProperty SortDirectionProperty =
        DependencyProperty.Register(
            nameof(SortDirection),
            typeof(ListSortDirection?),
            typeof(SortableTableHeader),
            new PropertyMetadata(null, OnSortStateChanged));

    public static readonly DependencyProperty ColumnWidthProperty =
        DependencyProperty.Register(
            nameof(ColumnWidth),
            typeof(GridLength),
            typeof(SortableTableHeader),
            new PropertyMetadata(new GridLength(1, GridUnitType.Star)));

    public static readonly DependencyProperty ShowSplitterProperty =
        DependencyProperty.Register(
            nameof(ShowSplitter),
            typeof(bool),
            typeof(SortableTableHeader),
            new PropertyMetadata(true, OnSortStateChanged));

    public static readonly DependencyProperty MinColumnWidthProperty =
        DependencyProperty.Register(
            nameof(MinColumnWidth),
            typeof(double),
            typeof(SortableTableHeader),
            new PropertyMetadata(DefaultMinColumnWidth));

    private bool _isDraggingSplitter;
    private double _dragStartX;
    private double _dragStartWidth;
    private long _lastDoubleTapTick;

    public event EventHandler<SortRequestedEventArgs>? SortRequested;
    public event EventHandler<string>? AutoFitRequested;

    public SortableTableHeader()
    {
        InitializeComponent();
    }

    public string Text
    {
        get => (string)GetValue(TextProperty);
        set => SetValue(TextProperty, value);
    }

    public string SortPropertyName
    {
        get => (string)GetValue(SortPropertyNameProperty);
        set => SetValue(SortPropertyNameProperty, value);
    }

    public string CurrentSortProperty
    {
        get => (string)GetValue(CurrentSortPropertyProperty);
        set => SetValue(CurrentSortPropertyProperty, value);
    }

    public ListSortDirection? SortDirection
    {
        get => (ListSortDirection?)GetValue(SortDirectionProperty);
        set => SetValue(SortDirectionProperty, value);
    }

    public GridLength ColumnWidth
    {
        get => (GridLength)GetValue(ColumnWidthProperty);
        set => SetValue(ColumnWidthProperty, value);
    }

    public bool ShowSplitter
    {
        get => (bool)GetValue(ShowSplitterProperty);
        set => SetValue(ShowSplitterProperty, value);
    }

    public double MinColumnWidth
    {
        get => (double)GetValue(MinColumnWidthProperty);
        set => SetValue(MinColumnWidthProperty, value);
    }

    public string SortGlyph =>
        SortDirection == ListSortDirection.Ascending ? "\uE70E" : "\uE70D";

    public Visibility SortIndicatorVisibility =>
        IsActiveSortColumn ? Visibility.Visible : Visibility.Collapsed;

    public Visibility SplitterVisibility =>
        ShowSplitter ? Visibility.Visible : Visibility.Collapsed;

    private bool IsActiveSortColumn =>
        !string.IsNullOrEmpty(SortPropertyName) &&
        string.Equals(SortPropertyName, CurrentSortProperty, StringComparison.OrdinalIgnoreCase) &&
        SortDirection.HasValue;

    /// <summary>
    /// 計算對齊該欄最寬項目（包含表頭與所有資料列內容）所需之欄位像素寬度。
    /// </summary>
    public static double CalculateAutoFitWidth(
        double minOrDefaultWidth,
        IEnumerable<string?> values,
        string? headerText = null)
    {
        double maxEstimatedWidth = Math.Max(DefaultMinColumnWidth, minOrDefaultWidth);

        if (!string.IsNullOrWhiteSpace(headerText))
        {
            double headerWidth = EstimateTextPixelWidth(headerText) + 40.0;
            if (headerWidth > maxEstimatedWidth)
            {
                maxEstimatedWidth = headerWidth;
            }
        }

        foreach (string? val in values)
        {
            if (string.IsNullOrWhiteSpace(val))
            {
                continue;
            }

            double estimated = EstimateTextPixelWidth(val) + 32.0;
            if (estimated > maxEstimatedWidth)
            {
                maxEstimatedWidth = estimated;
            }
        }

        return Math.Min(maxEstimatedWidth, DefaultMaxColumnWidth);
    }

    private static double EstimateTextPixelWidth(string text)
    {
        double len = 0;
        foreach (char c in text)
        {
            len += c > 127 ? 15.0 : 8.5;
        }
        return len;
    }

    private void OnHeaderClicked(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrEmpty(SortPropertyName))
        {
            return;
        }

        if (Environment.TickCount64 - _lastDoubleTapTick < 350)
        {
            return;
        }

        ListSortDirection nextDirection = SortDirection == ListSortDirection.Ascending
            ? ListSortDirection.Descending
            : ListSortDirection.Ascending;

        SortDirection = nextDirection;
        CurrentSortProperty = SortPropertyName;
        SortRequested?.Invoke(this, new SortRequestedEventArgs(SortPropertyName, nextDirection));
    }

    private void OnButtonDoubleTapped(object sender, DoubleTappedRoutedEventArgs e)
    {
        e.Handled = true;
        _lastDoubleTapTick = Environment.TickCount64;
        if (!string.IsNullOrEmpty(SortPropertyName))
        {
            AutoFitRequested?.Invoke(this, SortPropertyName);
        }
    }

    private void OnSplitterDoubleTapped(object sender, DoubleTappedRoutedEventArgs e)
    {
        e.Handled = true;
        _lastDoubleTapTick = Environment.TickCount64;
        _isDraggingSplitter = false;
        SplitterGrip.ReleasePointerCaptures();
        if (!string.IsNullOrEmpty(SortPropertyName))
        {
            AutoFitRequested?.Invoke(this, SortPropertyName);
        }
    }

    private void OnSplitterPointerEntered(object sender, PointerRoutedEventArgs e) => ProtectedCursor = InputSystemCursor.Create(InputSystemCursorShape.SizeWestEast);

    private void OnSplitterPointerExited(object sender, PointerRoutedEventArgs e)
    {
        if (!_isDraggingSplitter)
        {
            ProtectedCursor = null;
        }
    }

    private void OnSplitterPointerPressed(object sender, PointerRoutedEventArgs e)
    {
        var point = e.GetCurrentPoint(XamlRoot?.Content);
        if (!point.Properties.IsLeftButtonPressed)
        {
            return;
        }

        e.Handled = true;
        _isDraggingSplitter = true;
        _dragStartX = point.Position.X;
        _dragStartWidth = ColumnWidth.IsAbsolute && ColumnWidth.Value > 0
            ? ColumnWidth.Value
            : (ActualWidth > 0 ? ActualWidth : Math.Max(DefaultMinColumnWidth, MinColumnWidth));
        SplitterGrip.CapturePointer(e.Pointer);
    }

    private void OnSplitterPointerMoved(object sender, PointerRoutedEventArgs e)
    {
        if (!_isDraggingSplitter)
        {
            return;
        }

        e.Handled = true;
        double currentX = e.GetCurrentPoint(XamlRoot?.Content).Position.X;
        double deltaX = currentX - _dragStartX;
        double minW = Math.Max(DefaultMinColumnWidth, MinColumnWidth);
        double newWidth = Math.Clamp(_dragStartWidth + deltaX, minW, DefaultMaxColumnWidth);
        ColumnWidth = new GridLength(newWidth, GridUnitType.Pixel);
    }

    private void OnSplitterPointerReleased(object sender, PointerRoutedEventArgs e)
    {
        if (!_isDraggingSplitter)
        {
            return;
        }

        e.Handled = true;
        _isDraggingSplitter = false;
        SplitterGrip.ReleasePointerCaptures();
        ProtectedCursor = null;
    }

    private void OnSplitterPointerCanceled(object sender, PointerRoutedEventArgs e)
    {
        _isDraggingSplitter = false;
        SplitterGrip.ReleasePointerCaptures();
        ProtectedCursor = null;
    }

    private void OnSplitterPointerCaptureLost(object sender, PointerRoutedEventArgs e)
    {
        _isDraggingSplitter = false;
        ProtectedCursor = null;
    }

    private static void OnTextChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is SortableTableHeader header && e.NewValue is string text)
        {
            ToolTipService.SetToolTip(header, text);
        }
    }

    private static void OnSortStateChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is SortableTableHeader header)
        {
            header.Bindings.Update();
        }
    }
}

/// <summary>
/// 欄位排序請求事件參數
/// </summary>
public sealed class SortRequestedEventArgs(string propertyName, ListSortDirection direction) : EventArgs
{
    public string PropertyName { get; } = propertyName;
    public ListSortDirection Direction { get; } = direction;
}
