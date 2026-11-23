using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace MinecraftServerManager.App.Controls;

/// <summary>對話框共用的狀態圖示加訊息內容</summary>
public sealed partial class IconMessageContent : UserControl
{
    public static readonly DependencyProperty GlyphProperty =
        DependencyProperty.Register(nameof(Glyph), typeof(string), typeof(IconMessageContent), new PropertyMetadata(string.Empty));

    public static readonly DependencyProperty IconBrushKeyProperty =
        DependencyProperty.Register(nameof(IconBrushKey), typeof(string), typeof(IconMessageContent), new PropertyMetadata(null));

    public static readonly DependencyProperty MessageProperty =
        DependencyProperty.Register(nameof(Message), typeof(string), typeof(IconMessageContent), new PropertyMetadata(string.Empty));

    public IconMessageContent()
    {
        InitializeComponent();
    }

    /// <summary>Segoe Fluent Icons 字碼（見 Resources/Glyphs.xaml）</summary>
    public string Glyph
    {
        get => (string)GetValue(GlyphProperty);
        set => SetValue(GlyphProperty, value);
    }

    /// <summary>圖示前景的主題筆刷鍵</summary>
    public string? IconBrushKey
    {
        get => (string?)GetValue(IconBrushKeyProperty);
        set => SetValue(IconBrushKeyProperty, value);
    }

    public string Message
    {
        get => (string)GetValue(MessageProperty);
        set => SetValue(MessageProperty, value);
    }
}
