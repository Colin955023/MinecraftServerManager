using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace MinecraftServerManager.App.Controls;

/// <summary>
/// 雙色向量圖示控制項，用於顯示 ColorIcons.xaml 中定義之向量 DataTemplate
/// </summary>
public sealed partial class ColorIcon : ContentControl
{
    public static readonly DependencyProperty SourceProperty =
        DependencyProperty.Register(
            nameof(Source),
            typeof(DataTemplate),
            typeof(ColorIcon),
            new PropertyMetadata(null, OnSourceChanged));

    public ColorIcon()
    {
        IsTabStop = false;
        HorizontalContentAlignment = HorizontalAlignment.Stretch;
        VerticalContentAlignment = VerticalAlignment.Stretch;
    }

    /// <summary>
    /// 取得或設定圖示向量資料範本（來自 ColorIcons.xaml 之 StaticResource）
    /// </summary>
    public DataTemplate? Source
    {
        get => (DataTemplate?)GetValue(SourceProperty);
        set => SetValue(SourceProperty, value);
    }

    private static void OnSourceChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is ColorIcon icon)
        {
            icon.ContentTemplate = e.NewValue as DataTemplate;
            icon.Content = e.NewValue is not null ? string.Empty : null;
        }
    }
}
