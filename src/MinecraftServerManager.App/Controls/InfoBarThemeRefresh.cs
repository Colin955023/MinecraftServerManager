using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace MinecraftServerManager.App.Controls;

/// <summary>主題切換或重新載入時重新套用 InfoBar 嚴重性視覺狀態，使背景色隨主題更新</summary>
public static class InfoBarThemeRefresh
{
    public static readonly DependencyProperty IsEnabledProperty =
        DependencyProperty.RegisterAttached(
            "IsEnabled",
            typeof(bool),
            typeof(InfoBarThemeRefresh),
            new PropertyMetadata(false, OnIsEnabledChanged));

    public static bool GetIsEnabled(DependencyObject obj) => (bool)obj.GetValue(IsEnabledProperty);

    public static void SetIsEnabled(DependencyObject obj, bool value) => obj.SetValue(IsEnabledProperty, value);

    private static void OnIsEnabledChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is not InfoBar infoBar)
        {
            return;
        }

        infoBar.ActualThemeChanged -= OnActualThemeChanged;
        infoBar.Loaded -= OnLoaded;
        if (e.NewValue is true)
        {
            infoBar.ActualThemeChanged += OnActualThemeChanged;
            infoBar.Loaded += OnLoaded;
        }
    }

    private static void OnActualThemeChanged(FrameworkElement sender, object args) => Refresh((InfoBar)sender);

    private static void OnLoaded(object sender, RoutedEventArgs e) => Refresh((InfoBar)sender);

    /// <summary>視覺狀態 Setter 內的 ThemeResource 不會隨主題重新解析，暫換嚴重性以重新進入狀態</summary>
    private static void Refresh(InfoBar infoBar)
    {
        InfoBarSeverity severity = infoBar.Severity;
        infoBar.Severity = severity == InfoBarSeverity.Informational ? InfoBarSeverity.Warning : InfoBarSeverity.Informational;
        infoBar.Severity = severity;
    }
}
