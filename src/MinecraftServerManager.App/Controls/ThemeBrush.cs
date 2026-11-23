using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace MinecraftServerManager.App.Controls;

/// <summary>依主題資源鍵設定前景筆刷的附加屬性，主題切換時重新套用</summary>
public static class ThemeBrush
{
    public static readonly DependencyProperty ForegroundKeyProperty =
        DependencyProperty.RegisterAttached(
            "ForegroundKey",
            typeof(string),
            typeof(ThemeBrush),
            new PropertyMetadata(null, OnForegroundKeyChanged));

    public static string? GetForegroundKey(DependencyObject obj) =>
        (string?)obj.GetValue(ForegroundKeyProperty);

    public static void SetForegroundKey(DependencyObject obj, string? value) =>
        obj.SetValue(ForegroundKeyProperty, value);

    /// <summary>依實際主題自應用程式主題字典解析筆刷；找不到時退回一般資源</summary>
    private static Brush? ResolveBrush(string key, ElementTheme theme)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(key);
        var resources = Application.Current?.Resources;
        if (resources is null)
        {
            return null;
        }

        string themeKey = theme == ElementTheme.Light ? "Light" : "Default";
        if (resources.ThemeDictionaries.TryGetValue(themeKey, out object? dictionary) &&
            dictionary is ResourceDictionary themeDictionary &&
            themeDictionary.TryGetValue(key, out object? themed) &&
            themed is Brush themedBrush)
        {
            return themedBrush;
        }

        return resources.TryGetValue(key, out object? fallback) ? fallback as Brush : null;
    }

    private static void OnForegroundKeyChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is not FrameworkElement element)
        {
            return;
        }

        element.ActualThemeChanged -= OnActualThemeChanged;
        element.Loaded -= OnElementLoaded;
        if (e.NewValue is not string { Length: > 0 })
        {
            // 鍵值清空時還原為樣式或繼承的前景
            ClearForeground(element);
            return;
        }

        element.ActualThemeChanged += OnActualThemeChanged;
        if (!element.IsLoaded)
        {
            // 載入前 ActualTheme 尚未確定，載入後補套一次
            element.Loaded += OnElementLoaded;
        }

        Apply(element);
    }

    private static void OnActualThemeChanged(FrameworkElement sender, object args) => Apply(sender);

    private static void OnElementLoaded(object sender, RoutedEventArgs e)
    {
        var element = (FrameworkElement)sender;
        element.Loaded -= OnElementLoaded;
        Apply(element);
    }

    private static DependencyProperty? GetForegroundProperty(FrameworkElement element) => element switch
    {
        TextBlock => TextBlock.ForegroundProperty,
        Control => Control.ForegroundProperty,
        IconElement => IconElement.ForegroundProperty,
        _ => null,
    };

    private static void Apply(FrameworkElement element)
    {
        if (GetForegroundProperty(element) is not { } property ||
            GetForegroundKey(element) is not { Length: > 0 } key ||
            ResolveBrush(key, element.ActualTheme) is not { } brush)
        {
            return;
        }

        element.SetValue(property, brush);
    }

    private static void ClearForeground(FrameworkElement element)
    {
        if (GetForegroundProperty(element) is { } property)
        {
            element.ClearValue(property);
        }
    }
}
