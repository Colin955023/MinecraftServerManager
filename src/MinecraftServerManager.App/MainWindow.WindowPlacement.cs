using System.Runtime.InteropServices;
using Microsoft.UI.Windowing;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Infrastructure.Settings;
using Windows.Graphics;

namespace MinecraftServerManager.App;

public sealed partial class MainWindow
{
    /// <summary>還原視窗位置：位置為實體像素、尺寸為邏輯單位並以所在螢幕 DPI 換算；找不到螢幕或標題列不可見時置中於主螢幕</summary>
    private void RestoreWindowPosition(MainWindowSettings saved)
    {
        int widthDip = saved.Width > 0 ? saved.Width : DefaultWidthDip;
        int heightDip = saved.Height > 0 ? saved.Height : DefaultHeightDip;

        (RectInt32 Bounds, double Scale)? target = null;
        if (saved.X is int x && saved.Y is int y)
        {
            try
            {
                target = WindowLayoutHelper.ResolveRestoreBounds(WindowLayoutHelper.GetDisplays(), x, y, widthDip, heightDip);
            }
            catch (Exception ex) when (ex is InvalidCastException or COMException)
            {
                Logger.Warning(ex, "列舉螢幕失敗，視窗改置中於主螢幕");
            }
        }

        if (target is { } restore)
        {
            WindowLayoutHelper.SetMinimumSizeDip(this, 900, 580, restore.Scale);
            AppWindow.MoveAndResize(restore.Bounds);
        }
        else
        {
            var primary = DisplayArea.Primary;
            double scale = WindowLayoutHelper.GetScale(primary);
            WindowLayoutHelper.SetMinimumSizeDip(this, 900, 580, scale);
            int width = WindowLayoutHelper.ToPixels(widthDip, scale);
            int height = WindowLayoutHelper.ToPixels(heightDip, scale);
            AppWindow.MoveAndResize(new RectInt32(0, 0, width, height));
            CenterWindow(primary.WorkArea, width, height);
        }

        // 最大化前先記下還原後的視窗範圍，供關閉時儲存（最大化時的外框尺寸不可當作還原尺寸）
        _restoredBounds = WindowLayoutHelper.GetBounds(AppWindow);

        if (saved.Maximized && AppWindow.Presenter is OverlappedPresenter presenter)
        {
            presenter.Maximize();
        }
    }

    private void OnAppWindowChanged(AppWindow sender, AppWindowChangedEventArgs args)
    {
        if (args.DidSizeChange || args.DidPositionChange)
        {
            if (AppWindow.Presenter is not OverlappedPresenter { State: not OverlappedPresenterState.Restored })
            {
                _restoredBounds = WindowLayoutHelper.GetBounds(AppWindow);
            }

            // 大小或位置（可能換到不同縮放的螢幕）改變時同步「關於與設定」顯示的即時尺寸
            PushWindowMetrics();
        }
    }

    private void PushWindowMetrics()
    {
        if (_viewModel is null)
        {
            return;
        }

        double scale = WindowLayoutHelper.GetScale(this);
        var screen = DisplayArea.GetFromWindowId(AppWindow.Id, DisplayAreaFallback.Primary).OuterBounds;
        _viewModel.UpdateWindowMetrics(new WindowMetrics(
            (int)Math.Round(AppWindow.Size.Width / scale),
            (int)Math.Round(AppWindow.Size.Height / scale),
            screen.Width,
            screen.Height,
            scale));
    }

    private void CenterWindow(RectInt32 workArea, int width, int height) =>
        AppWindow.Move(WindowLayoutHelper.CenterWithin(workArea, workArea, width, height));

    /// <summary>於 UI 執行緒擷取視窗範圍，背景執行緒寫入設定檔</summary>
    private async Task SaveWindowPositionAsync()
    {
        if (_settings is null)
        {
            return;
        }

        var state = (AppWindow.Presenter as OverlappedPresenter)?.State;
        bool isMax = state == OverlappedPresenterState.Maximized;

        // 最大化或最小化時改存先前的還原範圍
        RectInt32 bounds = state is OverlappedPresenterState.Maximized or OverlappedPresenterState.Minimized && _restoredBounds is { } restored
            ? restored
            : WindowLayoutHelper.GetBounds(AppWindow);

        // 位置存實體像素（跨螢幕座標唯一），尺寸以所在螢幕 DPI 換算為邏輯單位
        double scale = WindowLayoutHelper.GetScale(DisplayArea.GetFromRect(bounds, DisplayAreaFallback.Nearest));
        try
        {
            int width = (int)Math.Round(bounds.Width / scale);
            int height = (int)Math.Round(bounds.Height / scale);
            ISettingsManager settings = _settings;
            await Task.Run(() => settings.SetMainWindowSettings(width, height, bounds.X, bounds.Y, isMax));
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Warning(ex, "儲存主視窗位置失敗");
        }
    }

    private void OnResetWindowSizeRequested()
    {
        if (AppWindow.Presenter is OverlappedPresenter presenter &&
            presenter.State == OverlappedPresenterState.Maximized)
        {
            presenter.Restore();
        }

        WindowLayoutHelper.ResizeToDip(this, DefaultWidthDip, DefaultHeightDip);
        var displayArea = DisplayArea.GetFromWindowId(AppWindow.Id, DisplayAreaFallback.Primary);
        CenterWindow(displayArea.WorkArea, AppWindow.Size.Width, AppWindow.Size.Height);
    }
}
