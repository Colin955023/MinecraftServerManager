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

    /// <summary>清單內容</summary>
    public UIElement? Body
    {
        get => (UIElement?)GetValue(BodyProperty);
        set => SetValue(BodyProperty, value);
    }
}
