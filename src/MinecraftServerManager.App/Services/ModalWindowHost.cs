using System.Runtime.InteropServices;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using MinecraftServerManager.Infrastructure.Logging;
using Windows.Graphics;
using WinRT.Interop;

namespace MinecraftServerManager.App.Services;

/// <summary>模態視窗宿主：管理 WinUI 3 原生 Window 的父子繫結、視窗置中、OverlappedPresenter 模態行為、前景焦點與非同步工作階段。</summary>
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

    /// <summary>統一設定模態對話視窗標題、DIP 尺寸，並於視窗關閉時自動解除 x:Bind 追蹤</summary>
    public static void ConfigureDialogWindow(
        Window window,
        string title,
        int widthDip,
        int heightDip,
        Action stopBindings)
    {
        ArgumentNullException.ThrowIfNull(window);
        ArgumentNullException.ThrowIfNull(stopBindings);

        window.Title = title;
        WindowLayoutHelper.ResizeToDip(window, widthDip, heightDip);
        window.Closed += (_, _) => stopBindings();
    }

    /// <summary>
    /// 延後至目前的命令處理完成後再關閉視窗。ViewModel 於命令內要求關閉時一律使用：
    /// 同步關閉會讓命令結束時更新已關閉視窗的按鈕狀態，造成原生閃退
    /// </summary>
    public static void CloseDeferred(Window window)
    {
        ArgumentNullException.ThrowIfNull(window);
        if (!window.DispatcherQueue.TryEnqueue(Microsoft.UI.Dispatching.DispatcherQueuePriority.Low, window.Close))
        {
            window.Close();
        }
    }

    /// <summary>為具備未儲存變更之對話視窗登錄統一的關閉確認攔截邏輯</summary>
    public static void RegisterUnsavedChangesPrompt(
        Window window,
        Func<bool> shouldPrompt,
        Func<Task<bool>> confirmDiscardAsync,
        Action onConfirmedDiscard,
        ComponentLogger logger)
    {
        ArgumentNullException.ThrowIfNull(window);
        ArgumentNullException.ThrowIfNull(shouldPrompt);
        ArgumentNullException.ThrowIfNull(confirmDiscardAsync);
        ArgumentNullException.ThrowIfNull(onConfirmedDiscard);
        ArgumentNullException.ThrowIfNull(logger);

        window.AppWindow.Closing += async (_, args) =>
        {
            try
            {
                if (shouldPrompt())
                {
                    args.Cancel = true;
                    if (await confirmDiscardAsync().ConfigureAwait(true))
                    {
                        onConfirmedDiscard();
                        window.Close();
                    }
                }
            }
            catch (Exception ex)
            {
                logger.Warning(ex, "視窗關閉確認失敗");
            }
        };
    }

    /// <summary>將子視窗相對於父視窗置中；若無父視窗則置中於主顯示器工作區，並確保視窗座標夾在螢幕可視工作區內。</summary>
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

    /// <summary>以模態方式顯示子視窗並等待其關閉，回傳子視窗之結果</summary>
    public static async Task<TResult> ShowModalAsync<TWindow, TResult>(
        TWindow childWindow,
        Window? parentWindow,
        ElementTheme theme,
        Func<TWindow, TResult> resultSelector,
        Action<Window> onWindowPushed,
        Action<Window> onWindowPopped)
        where TWindow : Window
    {
        ArgumentNullException.ThrowIfNull(childWindow);
        ArgumentNullException.ThrowIfNull(resultSelector);
        ArgumentNullException.ThrowIfNull(onWindowPushed);
        ArgumentNullException.ThrowIfNull(onWindowPopped);

        var tcs = new TaskCompletionSource<TResult>(TaskCreationOptions.RunContinuationsAsynchronously);

        // 套用視窗圖示與標題列主題
        WindowIconHelper.SetIcon(childWindow.AppWindow);
        TitleBarThemeHelper.ApplyTitleBarTheme(childWindow.AppWindow, theme);

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
        onWindowPushed(childWindow);

        // 停用父視窗以杜絕背景點選
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

                    onWindowPopped(childWindow);
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

            onWindowPopped(childWindow);
            throw;
        }

        return await tcs.Task;
    }
}
