using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace MinecraftServerManager.App.Controls;

/// <summary>
/// 依主題資源鍵設定前景筆刷之附加屬性：元素實際主題切換時自動重新套用，確保深淺色主題對比
/// </summary>
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

    /// <summary>
    /// 依實際主題自應用程式主題字典解析筆刷；找不到時回退至一般資源
    /// </summary>
    public static Brush? ResolveBrush(string key, ElementTheme theme)
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
        if (e.NewValue is string { Length: > 0 })
        {
            element.ActualThemeChanged += OnActualThemeChanged;
        }

        Apply(element);
    }

    private static void OnActualThemeChanged(FrameworkElement sender, object args) => Apply(sender);

    private static void Apply(FrameworkElement element)
    {
        if (GetForegroundKey(element) is not { Length: > 0 } key || ResolveBrush(key, element.ActualTheme) is not { } brush)
        {
            return;
        }

        switch (element)
        {
            case TextBlock textBlock:
                textBlock.Foreground = brush;
                break;
            case Control control:
                control.Foreground = brush;
                break;
        }
    }
}
