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

    /// <summary>取得實際顯示的 ToolTip</summary>
    public static string PickToolTip(string? toolTipText, string text) => toolTipText ?? text;
}
