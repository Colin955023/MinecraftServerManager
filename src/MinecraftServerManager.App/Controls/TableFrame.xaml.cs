using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
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

    public TableFrame()
    {
        InitializeComponent();
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
}
