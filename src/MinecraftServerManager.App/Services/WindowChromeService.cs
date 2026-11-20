using Microsoft.UI;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace MinecraftServerManager.App.Services;

/// <summary>視窗外框：Mica 材質、自訂標題列與標題列按鈕主題</summary>
public static class WindowChromeService
{
    /// <summary>套用 Mica 並以指定元素作為標題列</summary>
    public static void Apply(Window window, UIElement titleBar)
    {
        ArgumentNullException.ThrowIfNull(window);
        ArgumentNullException.ThrowIfNull(titleBar);

        window.SystemBackdrop = new MicaBackdrop();
        window.ExtendsContentIntoTitleBar = true;
        window.SetTitleBar(titleBar);
    }

    /// <summary>對話視窗：於既有內容上方插入 TitleBar 後套用 Mica</summary>
    public static void ApplyDialog(Window window, string title)
    {
        ArgumentNullException.ThrowIfNull(window);

        var titleBar = new TitleBar { Title = title };
        var host = new Grid();
        host.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        host.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });

        UIElement? content = window.Content;
        window.Content = host;
        host.Children.Add(titleBar);
        if (content is FrameworkElement element)
        {
            Grid.SetRow(element, 1);
            host.Children.Add(element);
        }

        Apply(window, titleBar);
    }

    /// <summary>依主題設定標題列按鈕；背景透明以透出 Mica</summary>
    public static void ApplyTheme(AppWindow? appWindow, ElementTheme theme)
    {
        if (appWindow?.TitleBar is not { } titleBar)
        {
            return;
        }

        titleBar.PreferredTheme = theme switch
        {
            ElementTheme.Light => TitleBarTheme.Light,
            ElementTheme.Dark => TitleBarTheme.Dark,
            _ => TitleBarTheme.UseDefaultAppMode
        };

        titleBar.ButtonBackgroundColor = Colors.Transparent;
        titleBar.ButtonInactiveBackgroundColor = Colors.Transparent;
    }
}
