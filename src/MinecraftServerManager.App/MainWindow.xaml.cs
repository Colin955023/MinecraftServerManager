using System.ComponentModel;
using System.IO;
using System.Windows;
using System.Windows.Media;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.App.Views;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Http;
using MinecraftServerManager.Infrastructure.Java;
using MinecraftServerManager.Infrastructure.Loaders;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Servers;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.App;

public partial class MainWindow : Window
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("MainWindow");
    private static readonly System.Net.Http.HttpClient SharedHttpClient = new(
        new System.Net.Http.SocketsHttpHandler { PooledConnectionLifetime = TimeSpan.FromMinutes(5) });
    private static readonly Infrastructure.Process.ProcessRunner SharedProcessRunner = new();
    private static readonly ServerRuntime SharedServerRuntime = new(SharedProcessRunner);
    private readonly MainViewModel _viewModel;

    public MainWindow()
    {
        InitializeComponent();

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

        var settings = new SettingsManager();
        string serversRoot = EnsureServersRootConfigured(settings);

        try
        {
            string legacyCache = Path.Combine(serversRoot, ".modcache");
            if (Directory.Exists(legacyCache))
            {
                SafeFileSystem.DeleteWithin(serversRoot, legacyCache);
                Logger.Information("已清理 servers 根目錄殘留的 .modcache: {Path}", legacyCache);
            }
        }
        catch (Exception ex)
        {
            Logger.Warning("清理 servers/.modcache 失敗: {Message}", ex.Message);
        }

        var javaDetector = new JavaRuntimeDetector(SharedProcessRunner);
        var httpPort = new HttpDownloadClient(SharedHttpClient);
        var loaderCatalog = new LoaderCatalogService(httpPort, Infrastructure.Utilities.RuntimePaths.GetVersionCacheDir());
        var loaderInstaller = new LoaderInstallerService(httpPort, SharedProcessRunner, Infrastructure.Utilities.RuntimePaths.GetInstallerCacheDir());
        var serverManager = new ServerManager(serversRoot, loaderInstaller: loaderInstaller);
        var backupService = new ServerBackupService(serversRoot);

        var modScanner = new Infrastructure.Mods.LocalModScanner();
        var modInstaller = new Infrastructure.Mods.ModFileInstaller(httpPort);
        var modManager = new Infrastructure.Mods.ModManager(modScanner, modInstaller);
        var modrinthClient = new Infrastructure.Mods.ModrinthClient(httpPort);
        var updateChecker = new Infrastructure.Services.UpdateCheckerService(httpPort);

        _viewModel = new MainViewModel(
            settings,
            javaDetector,
            serverManager,
            backupService,
            SharedServerRuntime,
            loaderCatalog,
            modManager,
            modrinthClient,
            updateChecker,
            SharedProcessRunner);

        _viewModel.PropertyChanged += ViewModel_PropertyChanged;

        // 背景非同步預熱本機 Java 候選快取
        _ = Task.Run(() => javaDetector.DetectAsync());
        _viewModel.NotificationRequested += ViewModel_NotificationRequested;
        _viewModel.ResetWindowSizeRequested += OnResetWindowSizeRequested;
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

    private void OnResetWindowSizeRequested()
    {
        Logger.Information("收到重設主視窗大小請求，還原為 1350x820 並置中");
        WindowState = WindowState.Normal;
        Width = 1350;
        Height = 820;
        Left = (SystemParameters.PrimaryScreenWidth - Width) / 2;
        Top = (SystemParameters.PrimaryScreenHeight - Height) / 2;
    }

    private static string EnsureServersRootConfigured(SettingsManager settings)
    {
        string current = settings.GetServersRoot();
        if (!string.IsNullOrWhiteSpace(current))
        {
            try
            {
                string validated = settings.GetValidatedServersRootPath(create: true);
                Logger.Information("已驗證伺服器存放目錄: {Path}", validated);
                return validated;
            }
            catch (Exception ex)
            {
                Logger.Warning("既有伺服器目錄設定無效 ({Message})，重新提示選取", ex.Message);
            }
        }

        while (true)
        {
            NotificationDialog.Show(
                null,
                "選擇伺服器資料夾",
                "請選擇要存放所有 Minecraft 伺服器的主資料夾\n(系統會在該資料夾內自動建立 servers 子資料夾)",
                NotificationLevel.Info);

            var dialog = new Microsoft.Win32.OpenFolderDialog
            {
                Title = "選擇存放 Minecraft 伺服器的主資料夾",
                Multiselect = false
            };

            if (dialog.ShowDialog() == true && !string.IsNullOrWhiteSpace(dialog.FolderName))
            {
                try
                {
                    settings.SetServersRoot(dialog.FolderName.Trim());
                    return settings.GetValidatedServersRootPath(create: true);
                }
                catch (Exception ex)
                {
                    NotificationDialog.Show(null, "設定錯誤", $"無法寫入設定或建立資料夾：{ex.Message}", NotificationLevel.Error);
                }
            }
            else
            {
                var res = MessageBox.Show(
                    "未選擇資料夾，是否要結束程式？",
                    "結束程式",
                    MessageBoxButton.YesNo,
                    MessageBoxImage.Question);

                if (res == MessageBoxResult.Yes)
                {
                    Application.Current.Shutdown();
                    Environment.Exit(0);
                }
            }
        }
    }

    private void ViewModel_NotificationRequested(string title, string message, NotificationLevel level) => NotificationDialog.Show(this, title, message, level);

    private void MainWindow_Loaded(object sender, RoutedEventArgs e)
    {
        Logger.Information("主視窗已載入完成，目前主題: {Theme}", _viewModel.IsLightTheme ? "淺色 (Light)" : "深色 (Dark)");
        ApplyTheme(_viewModel.IsLightTheme);
        RestoreWindowPosition();

        int sw = (int)SystemParameters.PrimaryScreenWidth;
        int sh = (int)SystemParameters.PrimaryScreenHeight;
        int ww = (int)ActualWidth;
        int wh = (int)ActualHeight;
        _viewModel.AboutPreferences?.UpdateDisplayInfo(sw, sh, ww, wh);
    }

    private void MainWindow_Closing(object? sender, CancelEventArgs e)
    {
        Logger.Information("主視窗正在關閉，儲存視窗位置與大小");
        SaveWindowPosition();
    }

    private void RestoreWindowPosition()
    {
        var settings = _viewModel.Settings;
        if (!settings.IsRememberSizePositionEnabled())
        {
            if (settings.IsAutoCenterEnabled())
            {
                WindowStartupLocation = WindowStartupLocation.CenterScreen;
            }
            return;
        }

        var winSettings = settings.GetMainWindowSettings();
        if (winSettings.Width > 0 && winSettings.Height > 0)
        {
            Width = Math.Max(MinWidth, winSettings.Width);
            Height = Math.Max(MinHeight, winSettings.Height);
        }

        if (winSettings.X.HasValue && winSettings.Y.HasValue)
        {
            Left = winSettings.X.Value;
            Top = winSettings.Y.Value;
            WindowStartupLocation = WindowStartupLocation.Manual;
        }
        else if (settings.IsAutoCenterEnabled())
        {
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
        }

        if (winSettings.Maximized)
        {
            WindowState = WindowState.Maximized;
        }
    }

    private void SaveWindowPosition()
    {
        var settings = _viewModel.Settings;
        if (!settings.IsRememberSizePositionEnabled())
        {
            return;
        }

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
            SetBrushColor("NotificationBrush", "#E7EEFF");
            SetBrushColor("ButtonDefaultHoverBrush", "#E2E8F0");
            SetBrushColor("NavButtonHoverBrush", "#E5E7EB");
            SetBrushColor("SubtleButtonHoverBrush", "#E5E7EB");
            SetBrushColor("DataGridGridLineBrush", "#D1D5DB");
            SetBrushColor("TabItemUnderlineBrush", "#4F6FD8");
            SetBrushColor("WarningBrush", "#B45309");

            SetBrushColor("ButtonDisabledBackgroundBrush", "#E2E8F0");
            SetBrushColor("ButtonDisabledForegroundBrush", "#64748B");
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
