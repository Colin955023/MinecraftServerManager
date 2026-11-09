using System.ComponentModel;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
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

    private readonly Dictionary<string, UIElement> _viewCache = new(StringComparer.OrdinalIgnoreCase);

    public MainViewModel? ViewModel => _viewModel;

    public MainWindow()
    {
        InitializeComponent();
        Title = "Minecraft 伺服器管理器";

        SystemBackdrop = new MicaBackdrop();
        ExtendsContentIntoTitleBar = true;

        WindowIconHelper.SetIcon(AppWindow);

        AppWindow.Closing += MainWindow_AppWindowClosing;
        RootGrid.Loaded += MainWindow_Loaded;
    }

    /// <summary>
    /// 初始化主視窗之組合根與 ViewModel 繫結
    /// </summary>
    public void InitializeViewModel(AppCompositionRoot compositionRoot)
    {
        _compositionRoot = compositionRoot ?? throw new ArgumentNullException(nameof(compositionRoot));
        _viewModel = compositionRoot.MainViewModel;

        _viewModel.PropertyChanged += ViewModel_PropertyChanged;
        _viewModel.NotificationRequested += ViewModel_NotificationRequested;
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
        WinUiService.Instance.CurrentTheme = targetTheme;
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
            CreateServerViewModel vm => GetOrCreateView("create", () => new CreateServerView { ViewModel = vm }),
            ManageServerViewModel vm => GetOrCreateView("manage", () => new ManageServerView { ViewModel = vm }),
            ModsViewModel vm => GetOrCreateView("mods", () => new ModsView { ViewModel = vm }),
            AboutPreferencesViewModel vm => GetOrCreateView("about_preferences", () => new AboutPreferencesView { ViewModel = vm }),
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
            ShowToast("發現新版本", $"已偵測到新版本 v{result.LatestVersion}，請至「關於與設定」查看詳細更新資訊。", NotificationLevel.Warning, 5);
        });
    }

    private void ViewModel_NotificationRequested(string title, string message, NotificationLevel level) => ShowToast(title, message, level);

    public void ShowToast(string message, string? title = null, ToastType type = ToastType.Info, int durationSeconds = 3)
    {
        var level = type switch
        {
            ToastType.Error => NotificationLevel.Error,
            _ => NotificationLevel.Warning
        };
        ShowToast(title ?? "通知", message, level, durationSeconds);
    }

    private Brush GetSafeThemeBrush(string key, Color fallbackColor)
    {
        try
        {
            string themeKey = RootGrid.ActualTheme == ElementTheme.Light ? "Light" : "Default";
            if (Application.Current?.Resources?.ThemeDictionaries is { } themeDicts &&
                themeDicts.TryGetValue(themeKey, out object? dictObj) &&
                dictObj is ResourceDictionary themeDict &&
                themeDict.TryGetValue(key, out object? brushObj) &&
                brushObj is Brush themeBrush)
            {
                return themeBrush;
            }

            if (Application.Current?.Resources?.TryGetValue(key, out object? rootObj) == true &&
                rootObj is Brush rootBrush)
            {
                return rootBrush;
            }
        }
        catch (Exception ex)
        {
            Logger.Warning("取得通知筆刷「{Key}」異常: {Message}", key, ex.Message);
        }

        return new SolidColorBrush(fallbackColor);
    }

    public void ShowToast(string title, string message, NotificationLevel level, int durationSeconds = 5)
    {
        bool isLight = RootGrid.ActualTheme == ElementTheme.Light;
        Brush cardBrush = GetSafeThemeBrush("CardBrush", isLight ? Color.FromArgb(255, 255, 255, 255) : Color.FromArgb(255, 31, 34, 41));
        Brush borderBrush = level == NotificationLevel.Error
            ? GetSafeThemeBrush("DangerBrush", Color.FromArgb(255, 220, 38, 38))
            : GetSafeThemeBrush("AccentBrush", Color.FromArgb(255, 79, 111, 216));
        Brush textBrush = GetSafeThemeBrush("TextBrush", isLight ? Color.FromArgb(255, 26, 29, 36) : Color.FromArgb(255, 243, 244, 246));
        Brush mutedTextBrush = GetSafeThemeBrush("MutedTextBrush", isLight ? Color.FromArgb(255, 94, 102, 117) : Color.FromArgb(255, 165, 172, 185));

        var toastBorder = new Border
        {
            Background = cardBrush,
            BorderBrush = borderBrush,
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(8),
            Padding = new Thickness(14, 10, 14, 10),
            MinWidth = 280,
            MaxWidth = 420
        };

        var stack = new StackPanel { Spacing = 4 };
        stack.Children.Add(new TextBlock
        {
            Text = title,
            FontWeight = Microsoft.UI.Text.FontWeights.SemiBold,
            FontSize = 14,
            Foreground = textBrush
        });
        stack.Children.Add(new TextBlock
        {
            Text = message,
            FontSize = 12,
            TextWrapping = TextWrapping.Wrap,
            Foreground = mutedTextBrush
        });

        toastBorder.Child = stack;

        var timer = DispatcherQueue.CreateTimer();
        timer.Interval = TimeSpan.FromSeconds(durationSeconds > 0 ? durationSeconds : 3);
        timer.Tick += (s, e) =>
        {
            timer.Stop();
            ToastContainer.Children.Remove(toastBorder);
        };

        toastBorder.PointerEntered += (s, e) => timer.Stop();
        toastBorder.PointerExited += (s, e) => timer.Start();

        while (ToastContainer.Children.Count >= 4)
        {
            ToastContainer.Children.RemoveAt(0);
        }

        ToastContainer.Children.Add(toastBorder);
        timer.Start();

        if (level == NotificationLevel.Error)
        {
            AudioFeedback.PlayError();
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
            _viewModel.NotificationRequested -= ViewModel_NotificationRequested;
            _viewModel.ResetWindowSizeRequested -= OnResetWindowSizeRequested;
            _viewModel.UpdateAvailable -= ViewModel_UpdateAvailable;
            _viewModel.ThemeModeChanged -= ApplyThemeMode;
            _viewModel.UnregisterEvents();
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
            WinUiService.Instance.PostToUi(Close);
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
