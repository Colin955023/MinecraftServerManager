using System.ComponentModel;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.App.Views;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Logging;
using Windows.Graphics;
using Windows.UI;

namespace MinecraftServerManager.App;

/// <summary>
/// 應用程式主視窗 (WinUI 3 原生視窗)
/// </summary>
public sealed partial class MainWindow : Window, IAsyncDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(MainWindow));

    private AppCompositionRoot? _compositionRoot;
    private MainViewModel? _viewModel;
    private bool _shutdownInProgress;
    private bool _shutdownCompleted;
    private WinUiService? _uiService;

    private readonly Dictionary<string, UIElement> _viewCache = new(StringComparer.OrdinalIgnoreCase);

    public MainViewModel? ViewModel => _viewModel;

    public MainWindow()
    {
        InitializeComponent();
        Title = "Minecraft 伺服器管理器";

        ExtendsContentIntoTitleBar = true;

        WindowIconHelper.SetIcon(AppWindow);

        AppWindow.Closing += MainWindow_AppWindowClosing;
        RootGrid.Loaded += MainWindow_Loaded;
    }

    /// <summary>
    /// 初始化主視窗之組合根與 ViewModel 繫結
    /// </summary>
    public void InitializeViewModel(AppCompositionRoot compositionRoot, WinUiService uiService)
    {
        _uiService = uiService ?? throw new ArgumentNullException(nameof(uiService));
        _compositionRoot = compositionRoot ?? throw new ArgumentNullException(nameof(compositionRoot));
        _viewModel = compositionRoot.MainViewModel;

        _viewModel.PropertyChanged += ViewModel_PropertyChanged;
        _viewModel.ResetWindowSizeRequested += OnResetWindowSizeRequested;
        _viewModel.UpdateAvailable += ViewModel_UpdateAvailable;
        _viewModel.ThemeModeChanged += ApplyThemeMode;

        ApplyThemeMode(_viewModel.ThemeMode);
        UpdateCurrentPage(_viewModel.CurrentPage);

        RestoreWindowPosition();

        _ = ViewModelBase.RunSafeAsync(() => _viewModel.CheckForUpdateOnStartupAsync(), "啟動檢查更新", Logger);
    }

    private void MainWindow_Loaded(object sender, RoutedEventArgs e) => Logger.Information("主視窗 UI 已載入完成");

    private void ApplyThemeMode(string mode)
    {
        ElementTheme targetTheme = mode switch
        {
            "light" => ElementTheme.Light,
            "dark" => ElementTheme.Dark,
            _ => ElementTheme.Default
        };

        RootGrid.RequestedTheme = targetTheme;
        _uiService!.CurrentTheme = targetTheme;
        TitleBarThemeHelper.ApplyTitleBarTheme(AppWindow, targetTheme);
        Logger.Information("主視窗套用主題模式: {0} ({1})", mode, targetTheme);
    }

    private void UpdateCurrentPage(PageViewModel? page)
    {
        if (page is null || _viewModel is null)
        {
            return;
        }

        UIElement view = page switch
        {
            CreateServerViewModel vm => GetOrCreateView("create", () => new CreateServerView(vm)),
            ManageServerViewModel vm => GetOrCreateView("manage", () => new ManageServerView(vm)),
            ModsViewModel vm => GetOrCreateView("mods", () => new ModsView(vm)),
            AboutPreferencesViewModel vm => GetOrCreateView("about_preferences", () => new AboutPreferencesView(vm)),
            _ => new TextBlock { Text = page.Title, Margin = new Thickness(20) }
        };

        PageContentHost.Content = view;
    }

    private UIElement GetOrCreateView(string key, Func<UIElement> factory)
    {
        if (!_viewCache.TryGetValue(key, out var view))
        {
            view = factory();
            _viewCache[key] = view;
        }
        return view;
    }

    private void ViewModel_PropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(MainViewModel.CurrentPage))
        {
            UpdateCurrentPage(_viewModel?.CurrentPage);
        }
    }

    private void ViewModel_UpdateAvailable(UpdateCheckResult result)
    {
        DispatcherQueue.TryEnqueue(() =>
        {
            ShowNotification($"已偵測到新版本 v{result.LatestVersion}，請至「關於與設定」查看詳細更新資訊。", "發現新版本", NotificationType.Info, durationSeconds: 5);
        });
    }


    /// <summary>
    /// 以 InfoBar 顯示資訊、成功與警告通知（錯誤由 WinUiService 以對話方塊顯示）
    /// </summary>
    public void ShowNotification(string message, string? title = null, NotificationType type = NotificationType.Info, int? durationSeconds = null) =>
        ShowInfoBar(
            title ?? NotificationPresentation.GetDefaultTitle(type),
            message,
            type,
            durationSeconds ?? NotificationPresentation.GetDisplaySeconds(type));

    private Brush GetSafeThemeBrush(string key, Color fallbackColor)
    {
        try
        {
            if (ThemeBrush.ResolveBrush(key, RootGrid.ActualTheme) is { } brush)
            {
                return brush;
            }
        }
        catch (Exception ex)
        {
            Logger.Warning("取得通知筆刷「{Key}」異常: {Message}", key, ex.Message);
        }

        return new SolidColorBrush(fallbackColor);
    }

    /// <summary>
    /// 於右上角以 WinUI 原生 InfoBar 顯示浮動通知：滑鼠停留時暫停自動關閉，最多同時顯示 4 則
    /// </summary>
    private void ShowInfoBar(string title, string message, NotificationType type, int durationSeconds)
    {
        bool isLight = RootGrid.ActualTheme == ElementTheme.Light;
        var infoBar = new InfoBar
        {
            Title = title,
            Message = message,
            Severity = NotificationPresentation.ToSeverity(type),
            IsClosable = true,
            IsOpen = true,
        };

        // InfoBar 預設背景為半透明，外層以卡片色承載確保浮於頁面內容上仍清晰可讀
        var host = new Border
        {
            Background = GetSafeThemeBrush("CardBrush", isLight ? Color.FromArgb(255, 255, 255, 255) : Color.FromArgb(255, 31, 34, 41)),
            CornerRadius = new CornerRadius(8),
            MinWidth = 280,
            MaxWidth = 420,
            Child = infoBar,
        };

        var timer = DispatcherQueue.CreateTimer();
        timer.Interval = TimeSpan.FromSeconds(durationSeconds > 0 ? durationSeconds : 3);
        timer.Tick += (s, e) =>
        {
            timer.Stop();
            infoBar.IsOpen = false;
        };

        infoBar.Closed += (s, e) =>
        {
            timer.Stop();
            NotificationContainer.Children.Remove(host);
        };
        host.PointerEntered += (s, e) => timer.Stop();
        host.PointerExited += (s, e) => timer.Start();

        while (NotificationContainer.Children.Count >= 4)
        {
            // 經 IsOpen=false 走 Closed 流程，確保被擠出之通知一併停止計時器
            var oldest = NotificationContainer.Children[0];
            if (oldest is Border { Child: InfoBar oldBar })
            {
                oldBar.IsOpen = false;
            }

            NotificationContainer.Children.Remove(oldest);
        }

        NotificationContainer.Children.Add(host);
        timer.Start();

        if (type == NotificationType.Warning)
        {
            AudioFeedback.PlayWarning();
        }
        else
        {
            AudioFeedback.PlayInfo();
        }
    }

    private void RestoreWindowPosition()
    {
        if (_viewModel is null)
        {
            return;
        }

        double scale = WindowLayoutHelper.GetScale(this);

        var winSettings = _viewModel.Settings.GetMainWindowSettings();

        int targetWidth = winSettings.Width > 0 ? (int)(winSettings.Width * scale) : (int)(1350 * scale);
        int targetHeight = winSettings.Height > 0 ? (int)(winSettings.Height * scale) : (int)(820 * scale);

        AppWindow.Resize(new SizeInt32(targetWidth, targetHeight));

        var displayArea = DisplayArea.GetFromWindowId(AppWindow.Id, DisplayAreaFallback.Primary);
        var workArea = displayArea.WorkArea;

        if (winSettings.X.HasValue && winSettings.Y.HasValue)
        {
            int targetX = (int)(winSettings.X.Value * scale);
            int targetY = (int)(winSettings.Y.Value * scale);

            if (targetX >= workArea.X && targetX + targetWidth <= workArea.X + workArea.Width &&
                targetY >= workArea.Y && targetY + targetHeight <= workArea.Y + workArea.Height)
            {
                AppWindow.Move(new PointInt32(targetX, targetY));
            }
            else
            {
                CenterWindow(workArea, targetWidth, targetHeight);
            }
        }
        else
        {
            CenterWindow(workArea, targetWidth, targetHeight);
        }

        if (winSettings.Maximized && AppWindow.Presenter is OverlappedPresenter presenter)
        {
            presenter.Maximize();
        }
    }

    private void CenterWindow(RectInt32 workArea, int width, int height) =>
        AppWindow.Move(WindowLayoutHelper.CenterWithin(workArea, workArea, width, height));

    private void SaveWindowPosition()
    {
        if (_viewModel is null)
        {
            return;
        }

        double scale = WindowLayoutHelper.GetScale(this);

        bool isMax = AppWindow.Presenter is OverlappedPresenter presenter &&
                     presenter.State == OverlappedPresenterState.Maximized;

        int width = (int)(AppWindow.Size.Width / scale);
        int height = (int)(AppWindow.Size.Height / scale);
        int x = (int)(AppWindow.Position.X / scale);
        int y = (int)(AppWindow.Position.Y / scale);

        _viewModel.Settings.SetMainWindowSettings(width, height, x, y, isMax);
    }

    private void OnResetWindowSizeRequested()
    {
        double scale = WindowLayoutHelper.GetScale(this);

        int width = (int)(1350 * scale);
        int height = (int)(820 * scale);

        if (AppWindow.Presenter is OverlappedPresenter presenter &&
            presenter.State == OverlappedPresenterState.Maximized)
        {
            presenter.Restore();
        }

        AppWindow.Resize(new SizeInt32(width, height));
        var displayArea = DisplayArea.GetFromWindowId(AppWindow.Id, DisplayAreaFallback.Primary);
        CenterWindow(displayArea.WorkArea, width, height);
    }

    private void MainWindow_AppWindowClosing(AppWindow sender, AppWindowClosingEventArgs args)
    {
        if (_shutdownCompleted)
        {
            return;
        }

        if (_compositionRoot?.IsServerRunning != true)
        {
            Logger.Information("主視窗正在關閉，儲存視窗位置與大小");
            SaveWindowPosition();
            UnregisterWindowEvents();
            _shutdownCompleted = true;
            _ = ViewModelBase.RunSafeAsync(DisposeSafelyAsync, "非同步釋放視窗資源", Logger);
            return;
        }

        args.Cancel = true;
        if (_shutdownInProgress)
        {
            return;
        }

        _shutdownInProgress = true;
        Logger.Information("主視窗正在關閉（等待執行中伺服器停止），儲存視窗位置與大小");
        SaveWindowPosition();
        UnregisterWindowEvents();

        _ = ViewModelBase.RunSafeAsync(ShutdownAndCloseAsync, "關閉應用程式與伺服器資源", Logger);
    }

    private void UnregisterWindowEvents()
    {
        if (_viewModel is not null)
        {
            _viewModel.PropertyChanged -= ViewModel_PropertyChanged;
            _viewModel.ResetWindowSizeRequested -= OnResetWindowSizeRequested;
            _viewModel.UpdateAvailable -= ViewModel_UpdateAvailable;
            _viewModel.ThemeModeChanged -= ApplyThemeMode;
            _viewModel.DisposePages();
        }
    }

    private async Task ShutdownAndCloseAsync()
    {
        try
        {
            await DisposeAsync().ConfigureAwait(true);
        }
        catch (Exception ex)
        {
            Logger.Warning("關閉應用程式資源時發生例外: {0}", ex.Message);
        }
        finally
        {
            _shutdownCompleted = true;
            DispatcherQueue.TryEnqueue(Close);
        }
    }

    private async Task DisposeSafelyAsync()
    {
        try
        {
            await DisposeAsync().ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            Logger.Warning("非同步釋放視窗資源時發生例外: {0}", ex.Message);
        }
    }

    public async ValueTask DisposeAsync()
    {
        if (_compositionRoot is not null)
        {
            await _compositionRoot.DisposeAsync().ConfigureAwait(false);
        }
    }

    private void OnNavigateCreateClicked(object sender, RoutedEventArgs e) =>
        _viewModel?.Navigate("create");

    private void OnNavigateManageClicked(object sender, RoutedEventArgs e) =>
        _viewModel?.Navigate("manage");

    private void OnNavigateModsClicked(object sender, RoutedEventArgs e) =>
        _viewModel?.Navigate("mods");

    private void OnNavigateAboutClicked(object sender, RoutedEventArgs e) =>
        _viewModel?.Navigate("about_preferences");

    private void OnImportServerClicked(object sender, RoutedEventArgs e)
    {
        if (_viewModel?.ImportServerCommand.CanExecute(null) == true)
        {
            _viewModel.ImportServerCommand.Execute(null);
        }
    }

    private void OnOpenFolderClicked(object sender, RoutedEventArgs e)
    {
        if (_viewModel?.OpenServersFolderCommand.CanExecute(null) == true)
        {
            _viewModel.OpenServersFolderCommand.Execute(null);
        }
    }
}
