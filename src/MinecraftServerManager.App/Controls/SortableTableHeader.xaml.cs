using System.ComponentModel;
using Microsoft.UI.Input;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;

namespace MinecraftServerManager.App.Controls;

/// <summary>表頭控制項：排序、方向指示、拖曳或 Alt+方向鍵調欄寬、按兩下分隔線自動對齊</summary>
public sealed partial class SortableTableHeader : UserControl
{
    public const double DefaultMinColumnWidth = 48.0;
    public const double DefaultMaxColumnWidth = 1200.0;
    private const double KeyboardResizeStep = 16.0;

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
            new PropertyMetadata(new GridLength(1, GridUnitType.Star), OnColumnWidthChanged));

    public static readonly DependencyProperty ShowSplitterProperty =
        DependencyProperty.Register(
            nameof(ShowSplitter),
            typeof(bool),
            typeof(SortableTableHeader),
            new PropertyMetadata(true, OnSortStateChanged));

    // 調整欄寬游標為無狀態系統游標，所有表頭共用同一執行個體
    private static InputSystemCursor? s_resizeCursor;

    private bool _isDraggingSplitter;
    private double _dragStartX;
    private double _dragStartWidth;
    private double? _initialPixelWidth;

    public SortableTableHeader()
    {
        InitializeComponent();
        Loaded += OnLoaded;
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

    public string SortGlyph =>
        (string)Application.Current.Resources[SortDirection == ListSortDirection.Ascending ? "IconSortAscending" : "IconSortDescending"];

    /// <summary>供螢幕閱讀程式朗讀的排序狀態</summary>
    public string SortStatusText => !IsActiveSortColumn
        ? string.Empty
        : SortDirection == ListSortDirection.Ascending ? "遞增排序" : "遞減排序";

    public Visibility SortIndicatorVisibility =>
        IsActiveSortColumn ? Visibility.Visible : Visibility.Collapsed;

    public Visibility SplitterVisibility =>
        ShowSplitter ? Visibility.Visible : Visibility.Collapsed;

    private bool IsActiveSortColumn =>
        !string.IsNullOrEmpty(SortPropertyName) &&
        SortDirection.HasValue;

    private void OnLoaded(object sender, RoutedEventArgs e)
    {
        UpdateHitTestState();
        int col = Grid.GetColumn(this);
        if (Parent is Grid parentGrid && col >= 0 && col < parentGrid.ColumnDefinitions.Count)
        {
            var def = parentGrid.ColumnDefinitions[col];
            if (_initialPixelWidth is null && def.Width.IsAbsolute)
            {
                _initialPixelWidth = def.Width.Value;
            }

            ColumnWidth = def.Width;
        }
    }

    private void UpdateHitTestState() => HeaderButton.IsHitTestVisible = !string.IsNullOrEmpty(SortPropertyName);

    /// <summary>計算對齊該欄最寬項目（包含表頭與所有資料列內容）所需之欄位像素寬度</summary>
    public static double CalculateAutoFitWidth(
        double minOrDefaultWidth,
        IEnumerable<string?> values,
        Func<string, double> measureText,
        string? headerText = null)
    {
        ArgumentNullException.ThrowIfNull(measureText);
        double maxEstimatedWidth = Math.Max(DefaultMinColumnWidth, minOrDefaultWidth);

        if (!string.IsNullOrWhiteSpace(headerText))
        {
            double headerWidth = measureText(headerText) + 40.0;
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

            double estimated = measureText(val) + 32.0;
            if (estimated > maxEstimatedWidth)
            {
                maxEstimatedWidth = estimated;
            }
        }

        return Math.Min(maxEstimatedWidth, DefaultMaxColumnWidth);
    }

    /// <summary>依實際量測之顯示文字寬度自動對齊欄寬（不小於初始寬度）</summary>
    public void FitToContent(IEnumerable<string?> values)
    {
        var measurer = new TextBlock();
        double width = CalculateAutoFitWidth(_initialPixelWidth ?? DefaultMinColumnWidth, values, text => MeasureText(measurer, text), Text);
        SetColumnWidth(new GridLength(width, GridUnitType.Pixel));
    }

    private static double MeasureText(TextBlock measurer, string text)
    {
        measurer.Text = text;
        measurer.Measure(new Windows.Foundation.Size(double.PositiveInfinity, double.PositiveInfinity));
        return measurer.DesiredSize.Width;
    }

    /// <summary>鍵盤調整欄寬：Alt+←／→</summary>
    private void OnHeaderKeyDown(object sender, KeyRoutedEventArgs e)
    {
        if (!ShowSplitter || (InputKeyboardSource.GetKeyStateForCurrentThread(Windows.System.VirtualKey.Menu) & Windows.UI.Core.CoreVirtualKeyStates.Down) == 0)
        {
            return;
        }

        double delta = e.Key switch
        {
            Windows.System.VirtualKey.Left => -KeyboardResizeStep,
            Windows.System.VirtualKey.Right => KeyboardResizeStep,
            _ => 0,
        };
        if (delta == 0)
        {
            return;
        }

        e.Handled = true;
        double current = ColumnWidth.IsAbsolute && ColumnWidth.Value > 0 ? ColumnWidth.Value : ActualWidth;
        SetColumnWidth(new GridLength(Math.Clamp(current + delta, DefaultMinColumnWidth, DefaultMaxColumnWidth), GridUnitType.Pixel));
    }

    private void SetColumnWidth(GridLength width)
    {
        ColumnWidth = width;
        int col = Grid.GetColumn(this);
        this.FindAncestor<TableFrame>()?.SyncColumnWidth(col, width);
    }

    /// <summary>僅記錄載入前（XAML 宣告）的初始寬度，拖曳或自動對齊後的寬度不得成為下限</summary>
    private static void OnColumnWidthChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is SortableTableHeader { _initialPixelWidth: null, IsLoaded: false } header && e.NewValue is GridLength { IsAbsolute: true } width)
        {
            header._initialPixelWidth = width.Value;
        }
    }

    private void OnHeaderClicked(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrEmpty(SortPropertyName))
        {
            return;
        }

        ListSortDirection nextDirection = SortDirection == ListSortDirection.Ascending
            ? ListSortDirection.Descending
            : ListSortDirection.Ascending;

        // 同一列的其他表頭各自保留排序狀態，需清除以免殘留多個排序箭頭
        if (Parent is Panel headerRow)
        {
            foreach (SortableTableHeader other in headerRow.Children.OfType<SortableTableHeader>())
            {
                if (!ReferenceEquals(other, this))
                {
                    other.SortDirection = null;
                }
            }
        }

        SortDirection = nextDirection;
        FindSortTarget()?.Sort(SortPropertyName, nextDirection);
    }

    private ITableSortTarget? FindSortTarget() => this.FindAncestor<TableFrame>()?.SortTarget;

    private void EndDrag(bool releaseCapture)
    {
        _isDraggingSplitter = false;
        if (releaseCapture)
        {
            SplitterGrip.ReleasePointerCaptures();
        }

        ProtectedCursor = null;
    }

    /// <summary>按兩下自動對齊僅限分隔線，避免與點選表頭排序衝突</summary>
    private void OnSplitterDoubleTapped(object sender, DoubleTappedRoutedEventArgs e)
    {
        e.Handled = true;
        EndDrag(true);
        if (!string.IsNullOrEmpty(SortPropertyName))
        {
            FindSortTarget()?.AutoFit(this);
        }
    }

    private void OnSplitterPointerEntered(object sender, PointerRoutedEventArgs e) =>
        ProtectedCursor = s_resizeCursor ??= InputSystemCursor.Create(InputSystemCursorShape.SizeWestEast);

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
            : (ActualWidth > 0 ? ActualWidth : DefaultMinColumnWidth);
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
        double newWidth = Math.Clamp(_dragStartWidth + deltaX, DefaultMinColumnWidth, DefaultMaxColumnWidth);
        SetColumnWidth(new GridLength(newWidth, GridUnitType.Pixel));
    }

    private void OnSplitterPointerReleased(object sender, PointerRoutedEventArgs e)
    {
        if (!_isDraggingSplitter)
        {
            return;
        }

        e.Handled = true;
        EndDrag(true);
    }

    private void OnSplitterPointerCanceled(object sender, PointerRoutedEventArgs e) => EndDrag(true);

    private void OnSplitterPointerCaptureLost(object sender, PointerRoutedEventArgs e) => EndDrag(false);

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
            header.UpdateHitTestState();
        }
    }
}
