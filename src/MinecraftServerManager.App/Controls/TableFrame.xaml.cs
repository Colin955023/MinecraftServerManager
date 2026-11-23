using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Markup;

namespace MinecraftServerManager.App.Controls;

/// <summary>表格外框：上方為表頭列（卡片底色與格線），下方為內容區（左右與下緣格線）</summary>
[ContentProperty(Name = nameof(Body))]
public sealed partial class TableFrame : UserControl
{
    public static readonly DependencyProperty HeaderProperty =
        DependencyProperty.Register(nameof(Header), typeof(UIElement), typeof(TableFrame), new PropertyMetadata(null));

    public static readonly DependencyProperty BodyProperty =
        DependencyProperty.Register(nameof(Body), typeof(UIElement), typeof(TableFrame), new PropertyMetadata(null));

    public static readonly DependencyProperty SortTargetProperty =
        DependencyProperty.Register(nameof(SortTarget), typeof(ITableSortTarget), typeof(TableFrame), new PropertyMetadata(null));

    public static readonly DependencyProperty IsEmptyProperty =
        DependencyProperty.Register(nameof(IsEmpty), typeof(bool), typeof(TableFrame), new PropertyMetadata(false));

    public static readonly DependencyProperty EmptyTextProperty =
        DependencyProperty.Register(nameof(EmptyText), typeof(string), typeof(TableFrame), new PropertyMetadata(string.Empty));

    public static readonly DependencyProperty ShowCardProperty =
        DependencyProperty.Register(nameof(ShowCard), typeof(bool), typeof(TableFrame), new PropertyMetadata(true, OnShowCardChanged));

    private readonly List<WeakReference<Grid>> _rowGrids = [];
    private ListViewBase? _listView;

    public TableFrame()
    {
        InitializeComponent();
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
    }

    /// <summary>表頭列內容</summary>
    public UIElement? Header
    {
        get => (UIElement?)GetValue(HeaderProperty);
        set => SetValue(HeaderProperty, value);
    }

    /// <summary>表頭排序與自動欄寬的對象</summary>
    public ITableSortTarget? SortTarget
    {
        get => (ITableSortTarget?)GetValue(SortTargetProperty);
        set => SetValue(SortTargetProperty, value);
    }

    /// <summary>為 true 時於內容區置中顯示 <see cref="EmptyText"/></summary>
    public bool IsEmpty
    {
        get => (bool)GetValue(IsEmptyProperty);
        set => SetValue(IsEmptyProperty, value);
    }

    /// <summary>空狀態提示文字</summary>
    public string EmptyText
    {
        get => (string)GetValue(EmptyTextProperty);
        set => SetValue(EmptyTextProperty, value);
    }

    /// <summary>清單內容</summary>
    public UIElement? Body
    {
        get => (UIElement?)GetValue(BodyProperty);
        set => SetValue(BodyProperty, value);
    }

    /// <summary>是否在最外層顯示卡片外框與內距（預設為 true）</summary>
    public bool ShowCard
    {
        get => (bool)GetValue(ShowCardProperty);
        set => SetValue(ShowCardProperty, value);
    }

    private static void OnShowCardChanged(DependencyObject d, DependencyPropertyChangedEventArgs e) =>
        ((TableFrame)d).ApplyCardAppearance();

    private void ApplyCardAppearance()
    {
        if (ShowCard)
        {
            CardBorder.ClearValue(Border.BackgroundProperty);
            CardBorder.ClearValue(Border.BorderBrushProperty);
            CardBorder.ClearValue(Border.BorderThicknessProperty);
            CardBorder.ClearValue(Border.CornerRadiusProperty);
            CardBorder.ClearValue(Border.PaddingProperty);
        }
        else
        {
            CardBorder.Background = null;
            CardBorder.BorderBrush = null;
            CardBorder.BorderThickness = default;
            CardBorder.CornerRadius = default;
            CardBorder.Padding = default;
        }
    }

    public Grid? GetHeaderGrid() => Header as Grid ?? Header.FindDescendant<Grid>();

    public void SyncColumnWidth(int columnIndex, GridLength width)
    {
        if (GetHeaderGrid() is { } headerGrid && columnIndex >= 0 && columnIndex < headerGrid.ColumnDefinitions.Count)
        {
            headerGrid.ColumnDefinitions[columnIndex].Width = width;
        }

        for (int i = _rowGrids.Count - 1; i >= 0; i--)
        {
            if (_rowGrids[i].TryGetTarget(out var rowGrid))
            {
                if (columnIndex >= 0 && columnIndex < rowGrid.ColumnDefinitions.Count)
                {
                    rowGrid.ColumnDefinitions[columnIndex].Width = width;
                }
            }
            else
            {
                _rowGrids.RemoveAt(i);
            }
        }
    }

    private void OnLoaded(object sender, RoutedEventArgs e)
    {
        SortTarget?.Attach();

        if (GetHeaderGrid() is { } headerGrid)
        {
            var headers = headerGrid.Children.OfType<SortableTableHeader>().OrderBy(Grid.GetColumn).ToList();
            if (headers.Count > 0)
            {
                headers[^1].ShowSplitter = false;
            }
        }

        _listView?.ContainerContentChanging -= OnContainerContentChanging;
        _listView = Body as ListViewBase ?? Body.FindDescendant<ListViewBase>();
        if (_listView is null)
        {
            return;
        }

        _listView.ContainerContentChanging += OnContainerContentChanging;

        // 補同步掛鉤解除期間已產生的列
        for (int i = 0; i < _listView.Items.Count; i++)
        {
            SyncRow(_listView.ContainerFromIndex(i) as SelectorItem);
        }
    }

    private void OnUnloaded(object sender, RoutedEventArgs e)
    {
        // WinUI 可能於新的 Loaded 之後才送達舊的 Unloaded，仍在樹上時略過以免掛鉤永久失效
        if (IsLoaded)
        {
            return;
        }

        SortTarget?.Detach();
        _listView?.ContainerContentChanging -= OnContainerContentChanging;
        _listView = null;

        _rowGrids.Clear();
    }

    private void OnContainerContentChanging(ListViewBase sender, ContainerContentChangingEventArgs args) => SyncRow(args.ItemContainer);

    private void SyncRow(SelectorItem? container)
    {
        if (container is not null && (container.ContentTemplateRoot as Grid ?? container.FindDescendant<Grid>()) is { } rowGrid)
        {
            SyncRowGridDefinitions(rowGrid);
            RegisterRowGrid(rowGrid);
        }
    }

    private void SyncRowGridDefinitions(Grid rowGrid)
    {
        if (GetHeaderGrid() is not { } headerGrid)
        {
            return;
        }

        int headerCount = headerGrid.ColumnDefinitions.Count;
        while (rowGrid.ColumnDefinitions.Count < headerCount)
        {
            rowGrid.ColumnDefinitions.Add(new ColumnDefinition());
        }

        while (rowGrid.ColumnDefinitions.Count > headerCount)
        {
            rowGrid.ColumnDefinitions.RemoveAt(rowGrid.ColumnDefinitions.Count - 1);
        }

        for (int i = 0; i < headerCount; i++)
        {
            rowGrid.ColumnDefinitions[i].Width = headerGrid.ColumnDefinitions[i].Width;
        }
    }

    private void RegisterRowGrid(Grid rowGrid)
    {
        for (int i = _rowGrids.Count - 1; i >= 0; i--)
        {
            if (!_rowGrids[i].TryGetTarget(out var target))
            {
                _rowGrids.RemoveAt(i);
            }
            else if (ReferenceEquals(target, rowGrid))
            {
                return;
            }
        }

        _rowGrids.Add(new WeakReference<Grid>(rowGrid));
    }
}
