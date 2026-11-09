using System.Runtime.InteropServices;
using Microsoft.UI;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Windows.UI;

namespace MinecraftServerManager.App.Services;

/// <summary>
/// 視窗標題列與 Caption 控制按鈕深淺色彩主題配置輔助工具
/// </summary>
public static partial class TitleBarThemeHelper
{
    private const int DWMWA_USE_IMMERSIVE_DARK_MODE = 20;

    [LibraryImport("dwmapi.dll", EntryPoint = "DwmSetWindowAttribute")]
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    private static partial int DwmSetWindowAttribute(IntPtr hwnd, int dwAttribute, ref int pvAttribute, int cbAttribute);

    /// <summary>
    /// 套用標題列與右上角視窗控制按鈕（最小化、最大化、關閉）之深淺主題配色
    /// </summary>
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

        IntPtr hwnd = Win32Interop.GetWindowFromWindowId(appWindow.Id);
        if (hwnd != IntPtr.Zero)
        {
            int useDarkMode = isLight ? 0 : 1;
            _ = DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ref useDarkMode, sizeof(int));
        }

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

        if (isLight)
        {
            var darkFore = Color.FromArgb(255, 30, 30, 30);
            var darkHoverFore = Color.FromArgb(255, 0, 0, 0);
            var lightHoverBack = Color.FromArgb(32, 0, 0, 0);
            var lightPressedBack = Color.FromArgb(48, 0, 0, 0);

            titleBar.ButtonForegroundColor = darkFore;
            titleBar.ButtonHoverForegroundColor = darkHoverFore;
            titleBar.ButtonHoverBackgroundColor = lightHoverBack;
            titleBar.ButtonPressedForegroundColor = darkHoverFore;
            titleBar.ButtonPressedBackgroundColor = lightPressedBack;
            titleBar.ButtonInactiveForegroundColor = inactiveFg;
        }
        else
        {
            var lightFore = Color.FromArgb(255, 240, 240, 240);
            var darkHoverBack = Color.FromArgb(32, 255, 255, 255);
            var darkPressedBack = Color.FromArgb(48, 255, 255, 255);

            titleBar.ButtonForegroundColor = lightFore;
            titleBar.ButtonHoverForegroundColor = Colors.White;
            titleBar.ButtonHoverBackgroundColor = darkHoverBack;
            titleBar.ButtonPressedForegroundColor = Colors.White;
            titleBar.ButtonPressedBackgroundColor = darkPressedBack;
            titleBar.ButtonInactiveForegroundColor = inactiveFg;
        }
    }
}
