using System.Runtime.InteropServices;
using Microsoft.UI;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Windows.Graphics;
using WinRT.Interop;

namespace MinecraftServerManager.App.Services;

/// <summary>視窗版面共用入口：DPI 查詢、置中與工作區夾限</summary>
public static partial class WindowLayoutHelper
{
    private const double DefaultDpi = 96.0;
    private const int MdtEffectiveDpi = 0;
    // 標題列至少需有此邏輯尺寸位於工作區內，使用者才能拖曳視窗
    private const int MinVisibleTitleBarWidthDip = 120;
    private const int TitleBarHeightDip = 32;

    [LibraryImport("user32.dll")]
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    private static partial uint GetDpiForWindow(IntPtr hwnd);

    [LibraryImport("shcore.dll")]
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    private static partial int GetDpiForMonitor(IntPtr hmonitor, int dpiType, out uint dpiX, out uint dpiY);

    /// <summary>取得視窗目前的 DPI 縮放比例（96 DPI = 1.0）</summary>
    public static double GetScale(Window window)
    {
        ArgumentNullException.ThrowIfNull(window);
        uint dpi = GetDpiForWindow(WindowNative.GetWindowHandle(window));
        return dpi > 0 ? dpi / DefaultDpi : 1.0;
    }

    /// <summary>取得螢幕的 DPI 縮放比例；查詢失敗時回傳 1.0</summary>
    public static double GetScale(DisplayArea displayArea)
    {
        ArgumentNullException.ThrowIfNull(displayArea);
        IntPtr monitor = Win32Interop.GetMonitorFromDisplayId(displayArea.DisplayId);
        return GetDpiForMonitor(monitor, MdtEffectiveDpi, out uint dpiX, out _) == 0 && dpiX > 0 ? dpiX / DefaultDpi : 1.0;
    }

    /// <summary>取得 AppWindow 目前的實體像素位置與大小</summary>
    public static RectInt32 GetBounds(AppWindow appWindow)
    {
        ArgumentNullException.ThrowIfNull(appWindow);
        return new RectInt32(appWindow.Position.X, appWindow.Position.Y, appWindow.Size.Width, appWindow.Size.Height);
    }

    /// <summary>依儲存的實體座標（左上角）與邏輯尺寸，以標題列中心點找出所屬螢幕並以其 DPI 換算還原範圍；標題列不可見時回傳 null</summary>
    public static (RectInt32 Bounds, double Scale)? ResolveRestoreBounds(IReadOnlyList<DisplayMetrics> displays, int x, int y, int widthDip, int heightDip)
    {
        ArgumentNullException.ThrowIfNull(displays);
        foreach (DisplayMetrics display in displays)
        {
            int width = ToPixels(widthDip, display.Scale);
            int titleCenterX = x + (width / 2);
            int titleCenterY = y + ToPixels(TitleBarHeightDip / 2.0, display.Scale);
            RectInt32 outer = display.OuterBounds;
            if (titleCenterX < outer.X || titleCenterX >= outer.X + outer.Width ||
                titleCenterY < outer.Y || titleCenterY >= outer.Y + outer.Height)
            {
                continue;
            }

            var bounds = new RectInt32(x, y, width, ToPixels(heightDip, display.Scale));
            return IsTitleBarVisible(bounds, display.WorkArea, display.Scale) ? (bounds, display.Scale) : null;
        }

        return null;
    }

    /// <summary>取得全部螢幕的外框、工作區與 DPI 縮放比例</summary>
    public static List<DisplayMetrics> GetDisplays() =>
        DisplayArea.FindAll().Select(static area => new DisplayMetrics(area.OuterBounds, area.WorkArea, GetScale(area))).ToList();

    /// <summary>判斷視窗標題列是否有足夠範圍位於工作區內</summary>
    public static bool IsTitleBarVisible(RectInt32 window, RectInt32 workArea, double scale)
    {
        int left = Math.Max(window.X, workArea.X);
        int right = Math.Min(window.X + window.Width, workArea.X + workArea.Width);
        int top = Math.Max(window.Y, workArea.Y);
        int bottom = Math.Min(window.Y + ToPixels(TitleBarHeightDip, scale), workArea.Y + workArea.Height);
        return right - left >= ToPixels(MinVisibleTitleBarWidthDip, scale) && bottom > top && window.Y >= workArea.Y;
    }

    /// <summary>依縮放比例（未指定時取視窗 DPI）調整為指定的邏輯尺寸</summary>
    public static void ResizeToDip(Window window, int widthDip, int heightDip, double? scale = null)
    {
        double s = scale ?? GetScale(window);
        window.AppWindow.Resize(new SizeInt32(ToPixels(widthDip, s), ToPixels(heightDip, s)));
    }

    /// <summary>依縮放比例（未指定時取視窗 DPI）設定可調整的最小邏輯尺寸</summary>
    public static void SetMinimumSizeDip(Window window, int widthDip, int heightDip, double? scale = null)
    {
        if (window.AppWindow.Presenter is OverlappedPresenter presenter)
        {
            double s = scale ?? GetScale(window);
            presenter.PreferredMinimumWidth = ToPixels(widthDip, s);
            presenter.PreferredMinimumHeight = ToPixels(heightDip, s);
        }
    }

    /// <summary>邏輯尺寸換算為實體像素（四捨五入）</summary>
    public static int ToPixels(double dip, double scale) => (int)Math.Round(dip * scale);

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

/// <summary>螢幕的外框、工作區（實體像素）與 DPI 縮放比例</summary>
public readonly record struct DisplayMetrics(RectInt32 OuterBounds, RectInt32 WorkArea, double Scale);
