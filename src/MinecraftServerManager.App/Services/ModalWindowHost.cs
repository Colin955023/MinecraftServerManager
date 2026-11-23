using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Input;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Infrastructure.Logging;
using Windows.Graphics;
using Windows.System;
using WinRT.Interop;

namespace MinecraftServerManager.App.Services;

/// <summary>模態視窗宿主：父子繫結、置中、模態行為與前景焦點</summary>
public static partial class ModalWindowHost
{
    private const int GWLP_HWNDPARENT = -8;

    // 對話視窗附加狀態：邏輯尺寸（供依父視窗 DPI 重算）與關閉要求處理常式（Escape 與未儲存提示共用）
    private static readonly ConditionalWeakTable<Window, DialogWindowState> States = [];

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

    /// <summary>設定對話視窗標題、外框與尺寸，註冊 Escape 關閉，關閉時解除 x:Bind 追蹤</summary>
    public static void ConfigureDialogWindow(
        Window window,
        string title,
        int widthDip,
        int heightDip,
        Action stopBindings,
        bool closeOnEscape = true)
    {
        ArgumentNullException.ThrowIfNull(window);
        ArgumentNullException.ThrowIfNull(stopBindings);

        var state = States.GetValue(window, static _ => new DialogWindowState());
        state.WidthDip = widthDip;
        state.HeightDip = heightDip;
        state.StopBindings = stopBindings;

        window.Title = title;
        WindowChromeService.ApplyDialog(window, title);
        ApplyDialogSize(window, state, WindowLayoutHelper.GetScale(window));
        window.Closed += (_, _) => state.ExecuteCleanup();

        if (closeOnEscape && window.Content is UIElement root)
        {
            var escape = new KeyboardAccelerator { Key = VirtualKey.Escape };
            escape.Invoked += (_, args) =>
            {
                args.Handled = true;
                RequestClose(window);
            };
            root.KeyboardAcceleratorPlacementMode = KeyboardAcceleratorPlacementMode.Hidden;
            root.KeyboardAccelerators.Add(escape);
        }
    }

    /// <summary>一次完成對話視窗外框、關閉請求、未儲存變更提示與排序目標退訂</summary>
    public static void AttachDialog(
        Window window,
        string title,
        int widthDip,
        int heightDip,
        Action stopBindings,
        IDialogCloseRequester requester,
        ComponentLogger? logger = null,
        bool closeOnEscape = true,
        Action? beforeClose = null,
        params ITableSortTarget?[] sortTargets)
    {
        ArgumentNullException.ThrowIfNull(requester);
        ConfigureDialogWindow(window, title, widthDip, heightDip, stopBindings, closeOnEscape);
        BindRequestClose(window, requester, success => SetDialogResult(window, success), beforeClose);

        if (requester is IUnsavedChangesPrompt prompt)
        {
            ArgumentNullException.ThrowIfNull(logger);
            RegisterUnsavedChangesPrompt(
                window,
                () => GetDialogResult(window) is null && prompt.HasUnsavedChanges,
                prompt.ConfirmDiscardAsync,
                () => SetDialogResult(window, false),
                logger);
        }

        if (sortTargets.Length > 0)
        {
            window.Closed += (_, _) =>
            {
                foreach (var target in sortTargets)
                {
                    target?.Detach();
                }
            };
        }
    }

    /// <summary>取得由 <see cref="AttachDialog"/> 記錄的對話視窗關閉結果</summary>
    public static bool? GetDialogResult(Window window)
    {
        ArgumentNullException.ThrowIfNull(window);
        return States.TryGetValue(window, out var state) ? state.DialogResult : null;
    }

    private static void SetDialogResult(Window window, bool result)
    {
        var state = States.GetValue(window, static _ => new DialogWindowState());
        state.DialogResult = result;
    }

    /// <summary>要求關閉對話視窗：有未儲存變更提示時先確認，否則直接延後關閉</summary>
    public static void RequestClose(Window window)
    {
        ArgumentNullException.ThrowIfNull(window);
        if (States.TryGetValue(window, out var state) && state.CloseRequestHandler is { } handler)
        {
            handler();
        }
        else
        {
            CloseDeferred(window);
        }
    }

    private static void ApplyDialogSize(Window window, DialogWindowState state, double scale)
    {
        WindowLayoutHelper.ResizeToDip(window, state.WidthDip, state.HeightDip, scale);
        WindowLayoutHelper.SetMinimumSizeDip(window, Math.Max(480, state.WidthDip * 2 / 3), Math.Max(360, state.HeightDip * 2 / 3), scale);
    }

    /// <summary>延後關閉視窗；命令內同步關閉會造成原生閃退。<paramref name="beforeClose"/> 於關閉前執行（如解除繫結）</summary>
    public static void CloseDeferred(Window window, Action? beforeClose = null)
    {
        ArgumentNullException.ThrowIfNull(window);
        void CloseNow()
        {
            beforeClose?.Invoke();
            if (States.TryGetValue(window, out var state))
            {
                state.ExecuteCleanup();
            }
            window.Close();
        }

        if (!window.DispatcherQueue.TryEnqueue(Microsoft.UI.Dispatching.DispatcherQueuePriority.Low, CloseNow))
        {
            CloseNow();
        }
    }

    /// <summary>訂閱 ViewModel 的 RequestClose：先記錄結果（若有）再延後關閉視窗，視窗關閉後自動退訂</summary>
    public static void BindRequestClose(
        Window window,
        IDialogCloseRequester requester,
        Action<bool>? setResult = null,
        Action? beforeClose = null)
    {
        ArgumentNullException.ThrowIfNull(window);
        ArgumentNullException.ThrowIfNull(requester);

        void OnRequestClose(bool success)
        {
            setResult?.Invoke(success);
            CloseDeferred(window, beforeClose);
        }

        requester.RequestClose += OnRequestClose;
        window.Closed += (_, _) => requester.RequestClose -= OnRequestClose;
    }

    /// <summary>於視窗內容首次 Loaded 時執行一次性非同步初始化，並於觸發或視窗關閉後自動退訂</summary>
    public static void RunOnLoadedOnce(
        Window window,
        Func<Task> initializeAsync,
        ComponentLogger logger,
        string operationName)
    {
        ArgumentNullException.ThrowIfNull(window);
        ArgumentNullException.ThrowIfNull(initializeAsync);
        ArgumentNullException.ThrowIfNull(logger);
        ArgumentException.ThrowIfNullOrWhiteSpace(operationName);

        if (window.Content is not FrameworkElement root)
        {
            return;
        }

        async void OnLoaded(object sender, RoutedEventArgs e)
        {
            root.Loaded -= OnLoaded;
            try
            {
                await initializeAsync();
            }
            catch (OperationCanceledException)
            {
                logger.Information("{Operation}已取消", operationName);
            }
            catch (Exception ex)
            {
                logger.Error(ex, "{Operation}失敗", operationName);
            }
        }

        root.Loaded += OnLoaded;
        window.Closed += (_, _) => root.Loaded -= OnLoaded;
    }

    /// <summary>為具備未儲存變更之對話視窗登錄統一的關閉確認攔截邏輯（標題列關閉與 Escape 共用）</summary>
    private static void RegisterUnsavedChangesPrompt(
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

        var state = States.GetValue(window, static _ => new DialogWindowState());

        // 確認對話框顯示期間再次要求關閉時忽略，避免疊出多個確認
        async Task PromptAsync()
        {
            if (Interlocked.Exchange(ref state.PromptActive, 1) != 0)
            {
                return;
            }

            try
            {
                if (await confirmDiscardAsync())
                {
                    onConfirmedDiscard();
                    CloseDeferred(window);
                }
            }
            catch (OperationCanceledException)
            {
                logger.Information("視窗關閉確認已取消");
            }
            catch (Exception ex)
            {
                logger.Warning(ex, "視窗關閉確認失敗");
            }
            finally
            {
                Volatile.Write(ref state.PromptActive, 0);
            }
        }

        state.CloseRequestHandler = () =>
        {
            if (shouldPrompt())
            {
                _ = PromptAsync();
            }
            else
            {
                CloseDeferred(window);
            }
        };

        window.AppWindow.Closing += (sender, args) =>
        {
            bool prompt;
            try
            {
                prompt = shouldPrompt();
            }
            catch (Exception ex)
            {
                logger.Warning(ex, "檢查未儲存變更失敗");
                return;
            }

            if (prompt)
            {
                args.Cancel = true;
                _ = PromptAsync();
            }
        };
    }

    /// <summary>相對父視窗置中（無父視窗則置中於主螢幕），並夾限於工作區內</summary>
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
            ? WindowLayoutHelper.GetBounds(parentAppWindow)
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
        WindowChromeService.ApplyTheme(childWindow.AppWindow, theme);

        // 套用主題
        if (childWindow.Content is FrameworkElement fe)
        {
            fe.RequestedTheme = theme;
        }

        IntPtr childHwnd = WindowNative.GetWindowHandle(childWindow);
        IntPtr parentHwnd = parentWindow is not null ? WindowNative.GetWindowHandle(parentWindow) : IntPtr.Zero;

        // 子視窗尚未顯示前 DPI 取自預設螢幕；改依父視窗所在螢幕 DPI 重算尺寸
        if (parentWindow is not null && States.TryGetValue(childWindow, out var state) && state.WidthDip > 0)
        {
            ApplyDialogSize(childWindow, state, WindowLayoutHelper.GetScale(parentWindow));
        }

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

        // Closed 與啟動失敗皆會清理，確保父視窗只重新啟用一次
        int cleanedUp = 0;
        void Cleanup()
        {
            if (Interlocked.Exchange(ref cleanedUp, 1) != 0)
            {
                return;
            }

            if (parentHwnd != IntPtr.Zero)
            {
                EnableWindow(parentHwnd, true);
                SetForegroundWindow(parentHwnd);
            }

            onWindowPopped(childWindow);
        }

        try
        {
            childWindow.Closed += (_, _) =>
            {
                try
                {
                    Cleanup();
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
            Cleanup();
            throw;
        }

        return await tcs.Task;
    }

    private sealed class DialogWindowState
    {
        public int WidthDip;
        public int HeightDip;
        public int PromptActive;
        public bool? DialogResult;
        public Action? CloseRequestHandler;
        public Action? StopBindings;
        private int _cleanupExecuted;

        public void ExecuteCleanup()
        {
            if (Interlocked.Exchange(ref _cleanupExecuted, 1) == 0)
            {
                StopBindings?.Invoke();
            }
        }
    }
}
