using System.Runtime.InteropServices;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Windows.Graphics;
using WinRT.Interop;

namespace MinecraftServerManager.App.Services;

/// <summary>
/// 模態視窗宿主：管理 WinUI 3 原生 Window 的父子綁定、視窗置中、OverlappedPresenter 模態行為、前景焦點與非同步工作階段。
/// </summary>
public static partial class ModalWindowHost
{
    private const int GWLP_HWNDPARENT = -8;

    [LibraryImport("user32.dll", EntryPoint = "SetWindowLongPtrW")]
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    private static partial IntPtr SetWindowLongPtr64(IntPtr hWnd, int nIndex, IntPtr dwNewLong);

    [LibraryImport("user32.dll", EntryPoint = "EnableWindow")]
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool EnableWindow(IntPtr hWnd, [MarshalAs(UnmanagedType.Bool)] bool bEnable);

    [LibraryImport("user32.dll", EntryPoint = "SetForegroundWindow")]
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool SetForegroundWindow(IntPtr hWnd);

    /// <summary>
    /// 將子視窗相對於父視窗置中；若無父視窗則置中於主顯示器工作區，並確保視窗座標夾在螢幕可視工作區內。
    /// </summary>
    public static void CenterOnParent(Window childWindow, Window? parentWindow)
    {
        ArgumentNullException.ThrowIfNull(childWindow);

        var childAppWindow = childWindow.AppWindow;
        if (childAppWindow is null)
        {
            return;
        }

        var parentAppWindow = parentWindow?.AppWindow;
        var referenceId = parentAppWindow?.Id ?? childAppWindow.Id;
        var displayArea = DisplayArea.GetFromWindowId(referenceId, DisplayAreaFallback.Primary);
        var workArea = displayArea.WorkArea;

        int childWidth = childAppWindow.Size.Width > 0 ? childAppWindow.Size.Width : 800;
        int childHeight = childAppWindow.Size.Height > 0 ? childAppWindow.Size.Height : 600;

        RectInt32 reference = parentAppWindow is not null && parentAppWindow.Size.Width > 0 && parentAppWindow.Size.Height > 0
            ? new RectInt32(parentAppWindow.Position.X, parentAppWindow.Position.Y, parentAppWindow.Size.Width, parentAppWindow.Size.Height)
            : workArea;

        childAppWindow.Move(WindowLayoutHelper.CenterWithin(reference, workArea, childWidth, childHeight));
    }

    /// <summary>
    /// 以模態方式顯示子視窗並等待其關閉，回傳子視窗之結果
    /// </summary>
    public static async Task<TResult> ShowModalAsync<TWindow, TResult>(
        TWindow childWindow,
        Window? parentWindow,
        ElementTheme theme,
        Func<TWindow, TResult> resultSelector,
        Action<Window>? onWindowPushed = null,
        Action<Window>? onWindowPopped = null)
        where TWindow : Window
    {
        ArgumentNullException.ThrowIfNull(childWindow);
        ArgumentNullException.ThrowIfNull(resultSelector);

        var tcs = new TaskCompletionSource<TResult>(TaskCreationOptions.RunContinuationsAsynchronously);

        // 套用視窗圖示與標題列主題
        WindowIconHelper.SetIcon(childWindow.AppWindow);
        TitleBarThemeHelper.ApplyTitleBarTheme(childWindow.AppWindow, theme);
        childWindow.SystemBackdrop ??= new Microsoft.UI.Xaml.Media.MicaBackdrop();

        // 套用主題
        if (childWindow.Content is FrameworkElement fe)
        {
            fe.RequestedTheme = theme;
        }

        IntPtr childHwnd = WindowNative.GetWindowHandle(childWindow);
        IntPtr parentHwnd = parentWindow is not null ? WindowNative.GetWindowHandle(parentWindow) : IntPtr.Zero;

        if (parentHwnd != IntPtr.Zero)
        {
            SetWindowLongPtr64(childHwnd, GWLP_HWNDPARENT, parentHwnd);
        }

        if (childWindow.AppWindow.Presenter is OverlappedPresenter presenter)
        {
            presenter.IsMinimizable = true;
            presenter.IsMaximizable = true;
            presenter.IsResizable = true;
        }

        // 相對於父視窗置中顯示
        CenterOnParent(childWindow, parentWindow);

        // 推入作用中視窗堆疊
        onWindowPushed?.Invoke(childWindow);

        // 停用父視窗以杜絕背景點擊
        if (parentHwnd != IntPtr.Zero)
        {
            EnableWindow(parentHwnd, false);
        }

        try
        {
            childWindow.Closed += (sender, args) =>
            {
                try
                {
                    if (parentHwnd != IntPtr.Zero)
                    {
                        EnableWindow(parentHwnd, true);
                        SetForegroundWindow(parentHwnd);
                    }

                    onWindowPopped?.Invoke(childWindow);
                    tcs.TrySetResult(resultSelector(childWindow));
                }
                catch (Exception ex)
                {
                    tcs.TrySetException(ex);
                }
            };

            childWindow.Activate();
        }
        catch (Exception)
        {
            if (parentHwnd != IntPtr.Zero)
            {
                EnableWindow(parentHwnd, true);
                SetForegroundWindow(parentHwnd);
            }

            onWindowPopped?.Invoke(childWindow);
            throw;
        }

        return await tcs.Task;
    }
}
