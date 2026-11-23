using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace MinecraftServerManager.App.Controls;

/// <summary>表格文字儲存格：右側分隔線、單行截斷並附 ToolTip</summary>
public sealed partial class TableCell : UserControl
{
    public static readonly DependencyProperty TextProperty =
        DependencyProperty.Register(
            nameof(Text),
            typeof(string),
            typeof(TableCell),
            new PropertyMetadata(string.Empty));

    public static readonly DependencyProperty ToolTipTextProperty =
        DependencyProperty.Register(
            nameof(ToolTipText),
            typeof(string),
            typeof(TableCell),
            new PropertyMetadata(null));

    public static readonly DependencyProperty ShowRightBorderProperty =
        DependencyProperty.Register(
            nameof(ShowRightBorder),
            typeof(bool),
            typeof(TableCell),
            new PropertyMetadata(true));

    public static readonly DependencyProperty ForegroundKeyProperty =
        DependencyProperty.Register(
            nameof(ForegroundKey),
            typeof(string),
            typeof(TableCell),
            new PropertyMetadata(null));

    public static readonly DependencyProperty TextFontWeightProperty =
        DependencyProperty.Register(
            nameof(TextFontWeight),
            typeof(Windows.UI.Text.FontWeight),
            typeof(TableCell),
            new PropertyMetadata(Microsoft.UI.Text.FontWeights.Normal));

    public TableCell()
    {
        InitializeComponent();
    }

    /// <summary>顯示文字，同時作為 ToolTip</summary>
    public string Text
    {
        get => (string)GetValue(TextProperty);
        set => SetValue(TextProperty, value);
    }

    /// <summary>ToolTip 文字；未指定時用 Text</summary>
    public string? ToolTipText
    {
        get => (string?)GetValue(ToolTipTextProperty);
        set => SetValue(ToolTipTextProperty, value);
    }

    /// <summary>是否顯示右側分隔線；最後一欄設為 false</summary>
    public bool ShowRightBorder
    {
        get => (bool)GetValue(ShowRightBorderProperty);
        set => SetValue(ShowRightBorderProperty, value);
    }

    /// <summary>文字主題色彩資源鍵</summary>
    public string? ForegroundKey
    {
        get => (string?)GetValue(ForegroundKeyProperty);
        set => SetValue(ForegroundKeyProperty, value);
    }

    /// <summary>文字字型粗細</summary>
    public Windows.UI.Text.FontWeight TextFontWeight
    {
        get => (Windows.UI.Text.FontWeight)GetValue(TextFontWeightProperty);
        set => SetValue(TextFontWeightProperty, value);
    }

    /// <summary>取得實際顯示的 ToolTip；空白時回傳 null 以免顯示空白提示</summary>
    public static string? PickToolTip(string? toolTipText, string? text) =>
        string.IsNullOrWhiteSpace(toolTipText) ? (string.IsNullOrWhiteSpace(text) ? null : text) : toolTipText;

    public static Thickness ToBorderThickness(bool showRightBorder) => new(0, 0, showRightBorder ? 1 : 0, 0);
}
