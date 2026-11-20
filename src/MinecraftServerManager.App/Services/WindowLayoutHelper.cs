using System.Runtime.InteropServices;
using Microsoft.UI.Xaml;
using Windows.Graphics;
using WinRT.Interop;

namespace MinecraftServerManager.App.Services;

/// <summary>視窗版面共用入口：DPI 查詢、置中與工作區夾限</summary>
public static partial class WindowLayoutHelper
{
    private const double DefaultDpi = 96.0;

    [LibraryImport("user32.dll")]
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    private static partial uint GetDpiForWindow(IntPtr hwnd);

    /// <summary>取得視窗目前的 DPI 縮放比例（96 DPI = 1.0）</summary>
    public static double GetScale(Window window)
    {
        ArgumentNullException.ThrowIfNull(window);
        uint dpi = GetDpiForWindow(WindowNative.GetWindowHandle(window));
        return dpi > 0 ? dpi / DefaultDpi : 1.0;
    }

    /// <summary>依視窗 DPI 調整為指定的邏輯尺寸</summary>
    public static void ResizeToDip(Window window, int widthDip, int heightDip)
    {
        double scale = GetScale(window);
        window.AppWindow.Resize(new SizeInt32((int)(widthDip * scale), (int)(heightDip * scale)));
    }

    /// <summary>依視窗 DPI 設定可調整的最小邏輯尺寸</summary>
    public static void SetMinimumSizeDip(Window window, int widthDip, int heightDip)
    {
        if (window.AppWindow.Presenter is Microsoft.UI.Windowing.OverlappedPresenter presenter)
        {
            double scale = GetScale(window);
            presenter.PreferredMinimumWidth = (int)(widthDip * scale);
            presenter.PreferredMinimumHeight = (int)(heightDip * scale);
        }
    }

    /// <summary>計算將指定尺寸置中於參考矩形之座標，並夾限於螢幕工作區內</summary>
    public static PointInt32 CenterWithin(RectInt32 reference, RectInt32 workArea, int width, int height)
    {
        int x = reference.X + ((reference.Width - width) / 2);
        int y = reference.Y + ((reference.Height - height) / 2);
        int maxX = Math.Max(workArea.X, workArea.X + workArea.Width - width);
        int maxY = Math.Max(workArea.Y, workArea.Y + workArea.Height - height);
        return new PointInt32(Math.Clamp(x, workArea.X, maxX), Math.Clamp(y, workArea.Y, maxY));
    }
}
