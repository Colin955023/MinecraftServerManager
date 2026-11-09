using System.Runtime.InteropServices;
using Microsoft.UI.Xaml;
using Windows.Graphics;
using WinRT.Interop;

namespace MinecraftServerManager.App.Services;

/// <summary>
/// 視窗版面配置的唯一共用入口：DPI 縮放比例查詢（GetDpiForWindow）與視窗置中／工作區夾限計算
/// </summary>
public static partial class WindowLayoutHelper
{
    private const double DefaultDpi = 96.0;

    [LibraryImport("user32.dll")]
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    private static partial uint GetDpiForWindow(IntPtr hwnd);

    /// <summary>
    /// 取得視窗目前的 DPI 縮放比例（96 DPI = 1.0）
    /// </summary>
    public static double GetScale(Window window)
    {
        ArgumentNullException.ThrowIfNull(window);
        uint dpi = GetDpiForWindow(WindowNative.GetWindowHandle(window));
        return dpi > 0 ? dpi / DefaultDpi : 1.0;
    }

    /// <summary>
    /// 計算將指定尺寸置中於參考矩形之座標，並夾限於螢幕工作區內
    /// </summary>
    public static PointInt32 CenterWithin(RectInt32 reference, RectInt32 workArea, int width, int height)
    {
        int x = reference.X + ((reference.Width - width) / 2);
        int y = reference.Y + ((reference.Height - height) / 2);
        int maxX = Math.Max(workArea.X, workArea.X + workArea.Width - width);
        int maxY = Math.Max(workArea.Y, workArea.Y + workArea.Height - height);
        return new PointInt32(Math.Clamp(x, workArea.X, maxX), Math.Clamp(y, workArea.Y, maxY));
    }
}
