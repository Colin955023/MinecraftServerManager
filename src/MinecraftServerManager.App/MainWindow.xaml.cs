using System.ComponentModel;
using System.Windows;
using System.Windows.Media;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.App.Views;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.App;

public sealed partial class MainWindow : Window, IAsyncDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("MainWindow");
    private readonly AppCompositionRoot? _compositionRoot;
    private readonly MainViewModel _viewModel;
    private bool _shutdownInProgress;
    private bool _shutdownCompleted;

    /// <summary>
    /// 建立主視窗並持有其應用程式組合根（於視窗關閉時非同步釋放）
    /// </summary>
    public MainWindow(string serversRoot, SettingsManager settingsManager)
    {
        _compositionRoot = new AppCompositionRoot(serversRoot, settingsManager);
        InitializeComponent();
        _viewModel = _compositionRoot.MainViewModel;
        InitializeWindow();
    }

    /// <summary>
    /// 於背景開始預熱（Java 候選、版本清單等）
    /// </summary>
    public void StartBackgroundWarmup() => _compositionRoot?.StartBackgroundWarmup();

    private void InitializeWindow()
    {
        _viewModel.PropertyChanged += ViewModel_PropertyChanged;
        _viewModel.NotificationRequested += ViewModel_NotificationRequested;
        _viewModel.ResetWindowSizeRequested += OnResetWindowSizeRequested;
        _viewModel.UiScaleChanged += ApplyUiScale;
        DataContext = _viewModel;

        Loaded += MainWindow_Loaded;
        Closing += MainWindow_Closing;
        SizeChanged += MainWindow_SizeChanged;
    }

    private void MainWindow_SizeChanged(object sender, SizeChangedEventArgs e)
    {
        if (_viewModel.CurrentPage is AboutPreferencesViewModel aboutVm)
        {
            int sw = (int)SystemParameters.PrimaryScreenWidth;
            int sh = (int)SystemParameters.PrimaryScreenHeight;
            int ww = (int)ActualWidth;
            int wh = (int)ActualHeight;
            aboutVm.UpdateDisplayInfo(sw, sh, ww, wh);
        }
    }

    /// <summary>
    /// 套用全域 UI 縮放至主視窗與所有快顯對話方塊（經由共用動態資源）。
    /// </summary>
    private void ApplyUiScale(double scale)
    {
        if (double.IsNaN(scale) || double.IsInfinity(scale) || scale <= 0)
        {
            scale = 1.0;
        }

        scale = Math.Clamp(scale, 0.5, 3.0);
        UiScaleTransform.ScaleX = scale;
        UiScaleTransform.ScaleY = scale;

        // 提供給對話方塊使用的共用縮放資源
        Application.Current.Resources["UiScaleValue"] = scale;
        Application.Current.Resources["UiScaleTransform"] = new ScaleTransform(scale, scale);

        Logger.Information("已套用全域 UI 縮放: {Scale:P0}", scale);
    }

    private void OnResetWindowSizeRequested()
    {
        Logger.Information("收到重設主視窗大小請求，還原為 1350x820 並置中");
        WindowState = WindowState.Normal;
        Width = 1350;
        Height = 820;
        Left = (SystemParameters.PrimaryScreenWidth - Width) / 2;
        Top = (SystemParameters.PrimaryScreenHeight - Height) / 2;
    }

    private void ViewModel_NotificationRequested(string title, string message, NotificationLevel level)
    {
        if (level == NotificationLevel.Error)
        {
            _compositionRoot?.UiService.ShowError(message, title);
        }
        else
        {
            _compositionRoot?.UiService.ShowWarning(message, title);
        }
    }

    private void MainWindow_Loaded(object sender, RoutedEventArgs e)
    {
        Logger.Information("主視窗已載入完成，目前主題: {Theme}", _viewModel.IsLightTheme ? "淺色 (Light)" : "深色 (Dark)");
        ApplyTheme(_viewModel.IsLightTheme);
        RestoreWindowPosition();
        ApplyUiScale(_viewModel.Settings.GetUiScale());

        int sw = (int)SystemParameters.PrimaryScreenWidth;
        int sh = (int)SystemParameters.PrimaryScreenHeight;
        int ww = (int)ActualWidth;
        int wh = (int)ActualHeight;
        _viewModel.AboutPreferences?.UpdateDisplayInfo(sw, sh, ww, wh);

        // 啟動時自動檢查更新（判斷邏輯位於 ViewModel，此處僅負責提示）
        _ = ViewModelBase.RunSafeAsync(() => _viewModel.CheckForUpdateOnStartupAsync(), "啟動檢查更新", Logger);
    }



    /// <summary>
    /// 非同步釋放主視窗持有的應用程式組合根
    /// </summary>
    public async ValueTask DisposeAsync()
    {
        if (_compositionRoot is not null)
        {
            await _compositionRoot.DisposeAsync().ConfigureAwait(true);
        }
    }

    private void MainWindow_Closing(object? sender, CancelEventArgs e)
    {
        if (_shutdownCompleted)
        {
            return;
        }

        // 若無伺服器執行中，直接儲存狀態並允許視窗即時關閉
        if (_compositionRoot?.IsServerRunning != true)
        {
            Logger.Information("主視窗正在關閉，儲存視窗位置與大小");
            if (_viewModel is not null)
            {
                SaveWindowPosition();
                UnregisterWindowEvents();
            }

            _shutdownCompleted = true;
            _ = ViewModelBase.RunSafeAsync(DisposeSafelyAsync, "非同步釋放視窗資源", Logger);
            return;
        }

        // 有伺服器正在執行，取消立即關閉並在背景停止伺服器後再關閉
        e.Cancel = true;
        if (_shutdownInProgress)
        {
            return;
        }

        _shutdownInProgress = true;
        Logger.Information("主視窗正在關閉（等候執行中伺服器停止），儲存視窗位置與大小");
        if (_viewModel is not null)
        {
            SaveWindowPosition();
            UnregisterWindowEvents();
        }

        _ = ViewModelBase.RunSafeAsync(ShutdownAndCloseAsync, "關閉應用程式與伺服器資源", Logger);
    }

    private void UnregisterWindowEvents()
    {
        if (_viewModel is not null)
        {
            _viewModel.PropertyChanged -= ViewModel_PropertyChanged;
            _viewModel.NotificationRequested -= ViewModel_NotificationRequested;
            _viewModel.ResetWindowSizeRequested -= OnResetWindowSizeRequested;
            _viewModel.UiScaleChanged -= ApplyUiScale;
            _viewModel.UnregisterEvents();
        }
    }

    /// <summary>
    /// 以非同步方式釋放應用程式資源（伺服器行程等）後再關閉視窗，避免 UI 執行緒同步等待
    /// </summary>
    private async Task ShutdownAndCloseAsync()
    {
        try
        {
            await DisposeAsync().ConfigureAwait(true);
        }
        catch (Exception ex)
        {
            Logger.Warning("關閉應用程式資源時發生例外: {Message}", ex.Message);
        }
        finally
        {
            _shutdownCompleted = true;
            _compositionRoot?.UiService.RunOnUi(Close);
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
            Logger.Warning("非同步釋放視窗資源時發生例外: {Message}", ex.Message);
        }
    }

    private void RestoreWindowPosition()
    {
        var settings = _viewModel.Settings;
        var winSettings = settings.GetMainWindowSettings();

        if (winSettings.Width > 0 && winSettings.Height > 0)
        {
            Width = Math.Max(MinWidth, winSettings.Width);
            Height = Math.Max(MinHeight, winSettings.Height);
        }

        WindowStartupLocation = WindowStartupLocation.CenterScreen;

        if (winSettings.Maximized)
        {
            WindowState = WindowState.Maximized;
        }
    }

    private void SaveWindowPosition()
    {
        var settings = _viewModel.Settings;

        bool isMax = WindowState == WindowState.Maximized;
        int width = isMax ? (int)RestoreBounds.Width : (int)ActualWidth;
        int height = isMax ? (int)RestoreBounds.Height : (int)ActualHeight;
        int? x = isMax ? (int?)RestoreBounds.Left : (int?)Left;
        int? y = isMax ? (int?)RestoreBounds.Top : (int?)Top;

        settings.SetMainWindowSettings(width, height, x, y, isMax);
    }

    private void ViewModel_PropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(MainViewModel.IsLightTheme))
        {
            ApplyTheme(_viewModel.IsLightTheme);
        }
    }

    private static readonly KeyValuePair<string, SolidColorBrush>[] LightBrushes = CreateBrushes([
        ("WindowBrush", "#F5F6FA"),
        ("SidebarBrush", "#FFFFFF"),
        ("CardBrush", "#FFFFFF"),
        ("BorderBrush", "#D9DEE8"),
        ("TextBrush", "#1A1D24"),
        ("MutedTextBrush", "#5E6675"),
        ("AccentBrush", "#4F6FD8"),
        ("AccentHoverBrush", "#3D5CC4"),
        ("DangerBrush", "#DC2626"),
        ("DangerHoverBrush", "#B91C1C"),
        ("SuccessBrush", "#1A7F37"),
        ("SuccessHoverBrush", "#1F883D"),
        ("NotificationBrush", "#E7EEFF"),
        ("ButtonDefaultHoverBrush", "#E2E8F0"),
        ("NavButtonHoverBrush", "#E5E7EB"),
        ("DataGridGridLineBrush", "#D1D5DB"),
        ("WarningBrush", "#B45309"),
        ("ButtonDisabledBackgroundBrush", "#E2E8F0"),
        ("ButtonDisabledForegroundBrush", "#1A1D24"),
        ("ButtonDisabledBorderBrush", "#CBD5E1"),
        ("ComboBoxPopupBackgroundBrush", "#FFFFFF"),
        ("ComboBoxItemHoverBrush", "#EBF0FF"),
        ("ComboBoxItemSelectedBrush", "#D6E4FF")
    ]);

    private static readonly KeyValuePair<string, SolidColorBrush>[] DarkBrushes = CreateBrushes([
        ("WindowBrush", "#101114"),
        ("SidebarBrush", "#17191E"),
        ("CardBrush", "#1F2229"),
        ("BorderBrush", "#353A45"),
        ("TextBrush", "#F3F4F6"),
        ("MutedTextBrush", "#A5ACB9"),
        ("AccentBrush", "#4F6FD8"),
        ("AccentHoverBrush", "#3D5CC4"),
        ("DangerBrush", "#B91C1C"),
        ("DangerHoverBrush", "#991B1B"),
        ("SuccessBrush", "#238636"),
        ("SuccessHoverBrush", "#2EA043"),
        ("NotificationBrush", "#283A5A"),
        ("ButtonDefaultHoverBrush", "#2E3440"),
        ("NavButtonHoverBrush", "#2D323E"),
        ("DataGridGridLineBrush", "#3F4552"),
        ("WarningBrush", "#F59E0B"),
        ("ButtonDisabledBackgroundBrush", "#2B2D35"),
        ("ButtonDisabledForegroundBrush", "#94A3B8"),
        ("ButtonDisabledBorderBrush", "#383C46"),
        ("ComboBoxPopupBackgroundBrush", "#1F2229"),
        ("ComboBoxItemHoverBrush", "#2E3442"),
        ("ComboBoxItemSelectedBrush", "#3B4459")
    ]);

    private static KeyValuePair<string, SolidColorBrush>[] CreateBrushes((string Key, string Hex)[] items)
    {
        var result = new KeyValuePair<string, SolidColorBrush>[items.Length];
        for (int i = 0; i < items.Length; i++)
        {
            var color = (Color)ColorConverter.ConvertFromString(items[i].Hex);
            var brush = new SolidColorBrush(color);
            brush.Freeze();
            result[i] = new KeyValuePair<string, SolidColorBrush>(items[i].Key, brush);
        }
        return result;
    }

    private static void ApplyTheme(bool isLight)
    {
        var brushes = isLight ? LightBrushes : DarkBrushes;
        var resources = Application.Current.Resources;
        foreach (var pair in brushes)
        {
            resources[pair.Key] = pair.Value;
        }
    }
}
