using Microsoft.UI;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Windows.UI;

namespace MinecraftServerManager.App.Services;

/// <summary>視窗標題列與控制按鈕深淺主題配置工具</summary>
public static class TitleBarThemeHelper
{
    public static void ApplyTitleBarTheme(AppWindow? appWindow, ElementTheme theme)
    {
        if (appWindow is null)
        {
            return;
        }

        bool isLight = theme switch
        {
            ElementTheme.Light => true,
            ElementTheme.Dark => false,
            _ => Application.Current?.RequestedTheme == ApplicationTheme.Light
        };

        var titleBar = appWindow.TitleBar;
        if (titleBar is null)
        {
            return;
        }

        titleBar.PreferredTheme = isLight ? TitleBarTheme.Light : TitleBarTheme.Dark;

        Color bg = isLight ? Color.FromArgb(255, 245, 246, 250) : Color.FromArgb(255, 16, 17, 20);
        Color fg = isLight ? Color.FromArgb(255, 26, 29, 36) : Color.FromArgb(255, 243, 244, 246);
        Color inactiveFg = isLight ? Color.FromArgb(160, 94, 102, 117) : Color.FromArgb(160, 165, 172, 185);

        titleBar.BackgroundColor = bg;
        titleBar.InactiveBackgroundColor = bg;
        titleBar.ForegroundColor = fg;
        titleBar.InactiveForegroundColor = inactiveFg;

        titleBar.ButtonBackgroundColor = bg;
        titleBar.ButtonInactiveBackgroundColor = bg;

        Color hoverBack = isLight ? Blend(bg, Colors.Black, 0.07) : Blend(bg, Colors.White, 0.10);
        Color pressedBack = isLight ? Blend(bg, Colors.Black, 0.12) : Blend(bg, Colors.White, 0.07);
        Color buttonFore = isLight ? Color.FromArgb(255, 30, 30, 30) : Color.FromArgb(255, 240, 240, 240);

        titleBar.ButtonForegroundColor = buttonFore;
        titleBar.ButtonHoverForegroundColor = buttonFore;
        titleBar.ButtonHoverBackgroundColor = hoverBack;
        titleBar.ButtonPressedForegroundColor = buttonFore;
        titleBar.ButtonPressedBackgroundColor = pressedBack;
        titleBar.ButtonInactiveForegroundColor = inactiveFg;
    }

    private static Color Blend(Color background, Color overlay, double opacity) => Color.FromArgb(
        255,
        (byte)Math.Round((background.R * (1 - opacity)) + (overlay.R * opacity)),
        (byte)Math.Round((background.G * (1 - opacity)) + (overlay.G * opacity)),
        (byte)Math.Round((background.B * (1 - opacity)) + (overlay.B * opacity)));
}
