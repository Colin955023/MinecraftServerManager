using System.ComponentModel;
using System.Windows;
using System.Windows.Media;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.App.Views;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App;

public partial class MainWindow : Window
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("MainWindow");
    private readonly AppCompositionRoot? _compositionRoot;
    private readonly MainViewModel _viewModel;

    public MainWindow() : this(new AppCompositionRoot())
    {
    }

    public MainWindow(AppCompositionRoot compositionRoot)
    {
        ArgumentNullException.ThrowIfNull(compositionRoot);
        InitializeComponent();
        _compositionRoot = compositionRoot;
        _viewModel = compositionRoot.MainViewModel;
        InitializeWindow();
    }

    public MainWindow(MainViewModel viewModel)
    {
        InitializeComponent();
        _compositionRoot = null;
        _viewModel = viewModel ?? throw new ArgumentNullException(nameof(viewModel));
        InitializeWindow();
    }

    private void InitializeWindow()
    {
        if (Icon == null)
        {
            try
            {
                Icon = System.Windows.Media.Imaging.BitmapFrame.Create(
                    new Uri("pack://application:,,,/MinecraftServerManager.App;component/assets/icon.ico", UriKind.RelativeOrAbsolute));
            }
            catch
            {
                // 忽略圖示載入例外
            }
        }

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
        int sw = (int)SystemParameters.PrimaryScreenWidth;
        int sh = (int)SystemParameters.PrimaryScreenHeight;
        int ww = (int)ActualWidth;
        int wh = (int)ActualHeight;
        _viewModel.AboutPreferences?.UpdateDisplayInfo(sw, sh, ww, wh);
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

    private void ViewModel_NotificationRequested(string title, string message, NotificationLevel level) => NotificationDialog.Show(this, title, message, level);

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

        // 啟動時自動檢查更新
        if (_viewModel.Settings.IsAutoUpdateEnabled() && _viewModel.UpdateChecker is { } updateChecker && _viewModel.Launcher is { } launcher)
        {
            _ = Task.Run(async () =>
            {
                try
                {
                    var result = await updateChecker.CheckForUpdateAsync().ConfigureAwait(false);
                    if (result.HasUpdate)
                    {
                        await Dispatcher.InvokeAsync(() =>
                        {
                            string cleanedNotes = AboutPreferencesViewModel.CleanReleaseNotes(result.ReleaseNotes);
                            var confirm = MessageBox.Show(
                                this,
                                $"發現新版本 {result.LatestVersion} (目前版本：{result.CurrentVersion})！\n\n更新內容：\n{cleanedNotes}\n\n是否立即前往 GitHub 下載更新？",
                                "發現新版本",
                                MessageBoxButton.YesNo,
                                MessageBoxImage.Information);

                            if (confirm == MessageBoxResult.Yes)
                            {
                                launcher.OpenUrl(result.ReleasePageUrl);
                            }
                        });
                    }
                }
                catch (Exception ex)
                {
                    Logger.Warning("啟動自動檢查更新失敗: {Message}", ex.Message);
                }
            });
        }
    }

    private void MainWindow_Closing(object? sender, CancelEventArgs e)
    {
        Logger.Information("主視窗正在關閉，儲存視窗位置與大小");
        if (_viewModel is not null)
        {
            SaveWindowPosition();
            _viewModel.UnregisterEvents();
        }
        _compositionRoot?.Dispose();
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

    private static void ApplyTheme(bool isLight)
    {
        if (isLight)
        {
            SetBrushColor("WindowBrush", "#F5F6FA");
            SetBrushColor("SidebarBrush", "#FFFFFF");
            SetBrushColor("CardBrush", "#FFFFFF");
            SetBrushColor("BorderBrush", "#D9DEE8");
            SetBrushColor("TextBrush", "#1A1D24");
            SetBrushColor("MutedTextBrush", "#5E6675");
            SetBrushColor("AccentBrush", "#4F6FD8");
            SetBrushColor("AccentHoverBrush", "#3D5CC4");
            SetBrushColor("DangerBrush", "#DC2626");
            SetBrushColor("DangerHoverBrush", "#B91C1C");
            SetBrushColor("SuccessBrush", "#1A7F37");
            SetBrushColor("SuccessHoverBrush", "#1F883D");
            SetBrushColor("NotificationBrush", "#E7EEFF");
            SetBrushColor("ButtonDefaultHoverBrush", "#E2E8F0");
            SetBrushColor("NavButtonHoverBrush", "#E5E7EB");
            SetBrushColor("SubtleButtonHoverBrush", "#E5E7EB");
            SetBrushColor("DataGridGridLineBrush", "#D1D5DB");
            SetBrushColor("TabItemUnderlineBrush", "#4F6FD8");
            SetBrushColor("WarningBrush", "#B45309");

            SetBrushColor("ButtonDisabledBackgroundBrush", "#E2E8F0");
            SetBrushColor("ButtonDisabledForegroundBrush", "#1A1D24");
            SetBrushColor("ButtonDisabledBorderBrush", "#CBD5E1");

            SetBrushColor("ComboBoxPopupBackgroundBrush", "#FFFFFF");
            SetBrushColor("ComboBoxItemHoverBrush", "#EBF0FF");
            SetBrushColor("ComboBoxItemSelectedBrush", "#D6E4FF");
        }
        else
        {
            SetBrushColor("WindowBrush", "#101114");
            SetBrushColor("SidebarBrush", "#17191E");
            SetBrushColor("CardBrush", "#1F2229");
            SetBrushColor("BorderBrush", "#353A45");
            SetBrushColor("TextBrush", "#F3F4F6");
            SetBrushColor("MutedTextBrush", "#A5ACB9");
            SetBrushColor("AccentBrush", "#4F6FD8");
            SetBrushColor("AccentHoverBrush", "#3D5CC4");
            SetBrushColor("DangerBrush", "#B91C1C");
            SetBrushColor("DangerHoverBrush", "#991B1B");
            SetBrushColor("SuccessBrush", "#238636");
            SetBrushColor("SuccessHoverBrush", "#2EA043");
            SetBrushColor("NotificationBrush", "#283A5A");
            SetBrushColor("ButtonDefaultHoverBrush", "#2E3440");
            SetBrushColor("NavButtonHoverBrush", "#2D323E");
            SetBrushColor("SubtleButtonHoverBrush", "#2D323E");
            SetBrushColor("DataGridGridLineBrush", "#3F4552");
            SetBrushColor("TabItemUnderlineBrush", "#4F6FD8");
            SetBrushColor("WarningBrush", "#F59E0B");

            SetBrushColor("ButtonDisabledBackgroundBrush", "#2B2D35");
            SetBrushColor("ButtonDisabledForegroundBrush", "#94A3B8");
            SetBrushColor("ButtonDisabledBorderBrush", "#383C46");

            SetBrushColor("ComboBoxPopupBackgroundBrush", "#1F2229");
            SetBrushColor("ComboBoxItemHoverBrush", "#2E3442");
            SetBrushColor("ComboBoxItemSelectedBrush", "#3B4459");
        }
    }

    private static void SetBrushColor(string resourceKey, string colorText)
    {
        if (ColorConverter.ConvertFromString(colorText) is not Color color)
        {
            return;
        }

        var brush = new SolidColorBrush(color);
        brush.Freeze();
        Application.Current.Resources[resourceKey] = brush;
    }
}
