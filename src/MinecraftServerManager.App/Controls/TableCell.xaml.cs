using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace MinecraftServerManager.App.Controls;

/// <summary>表格文字儲存格：右側分隔線、單行截斷並以 ToolTip 顯示完整內容</summary>
public sealed partial class TableCell : UserControl
{
    public static readonly DependencyProperty TextProperty =
        DependencyProperty.Register(
            nameof(Text),
            typeof(string),
            typeof(TableCell),
            new PropertyMetadata(string.Empty));

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
}
