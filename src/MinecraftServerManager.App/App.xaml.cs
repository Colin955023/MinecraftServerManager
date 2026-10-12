using System.Windows;
using System.Windows.Threading;
using Microsoft.Win32;
using MinecraftServerManager.App.Views;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.App;

public partial class App : Application
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("App");
    private static Mutex? _singleInstanceMutex;

    protected override void OnStartup(StartupEventArgs e)
    {
        // 1. 最先註冊未處理例外事件，確保啟動初期之任何錯誤均被記錄
        DispatcherUnhandledException += App_DispatcherUnhandledException;
        AppDomain.CurrentDomain.UnhandledException += CurrentDomain_UnhandledException;

        // 2. 單一實體檢查
        _singleInstanceMutex = new Mutex(true, "MinecraftServerManagerMutex", out bool createdNew);
        if (!createdNew)
        {
            _singleInstanceMutex.Dispose();
            _singleInstanceMutex = null;
            MessageBox.Show(
                "Minecraft Server Manager 已在執行中，請勿重複啟動。",
                "提示",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
            Shutdown(0);
            return;
        }

        // 3. 設定為顯式關閉模式，杜絕初次啟動路徑引導對話方塊關閉時觸發自動關閉
        ShutdownMode = ShutdownMode.OnExplicitShutdown;

        // 4. 初始化記錄系統
        AppLogging.Initialize();
        Logger.Information("Minecraft Server Manager 啟動中 (版本 2.0.0)");

        base.OnStartup(e);

        try
        {
            // 5. 檢查並引導伺服器存放目錄
            var settingsManager = new SettingsManager();
            string serversRoot = EnsureServersRootConfigured(settingsManager);
            if (string.IsNullOrWhiteSpace(serversRoot))
            {
                Logger.Information("使用者未選取伺服器目錄或選擇結束，正常關閉應用程式");
                Shutdown(0);
                return;
            }

            // 6. 建構組合根與主視窗
            var compositionRoot = new AppCompositionRoot(serversRoot, settingsManager);
            var mainWindow = new MainWindow(compositionRoot);
            MainWindow = mainWindow;

            // 7. 切換為主視窗關閉模式，呈現主視窗
            ShutdownMode = ShutdownMode.OnMainWindowClose;
            mainWindow.Show();

            // 8. 啟動背景非同步預熱
            compositionRoot.StartBackgroundWarmup();
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "應用程式啟動初始化流程發生例外: {Message}", ex.Message);
            MessageBox.Show(
                $"應用程式啟動失敗：\n\n{ex.Message}\n\n堆疊追蹤：\n{ex.StackTrace}",
                "Minecraft Server Manager 啟動錯誤",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
            Shutdown(1);
        }
    }

    private static string EnsureServersRootConfigured(SettingsManager settings)
    {
        string current = settings.GetServersRoot();
        if (!string.IsNullOrWhiteSpace(current))
        {
            try
            {
                string validated = settings.GetValidatedServersRootPath(create: true);
                Logger.Information("已驗證既有伺服器存放目錄: {Path}", validated);
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

            var dialog = new OpenFolderDialog
            {
                Title = "選擇存放 Minecraft 伺服器的主資料夾",
                Multiselect = false,
            };

            if (dialog.ShowDialog() == true && !string.IsNullOrWhiteSpace(dialog.FolderName))
            {
                try
                {
                    settings.SetServersRoot(dialog.FolderName.Trim());
                    string validated = settings.GetValidatedServersRootPath(create: true);
                    Logger.Information("使用者成功設定伺服器存放目錄: {Path}", validated);
                    return validated;
                }
                catch (Exception ex)
                {
                    Logger.Error(ex, "寫入伺服器目錄設定失敗: {Message}", ex.Message);
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
                    return string.Empty;
                }
            }
        }
    }

    protected override void OnExit(ExitEventArgs e)
    {
        try
        {
            Logger.Information("Minecraft Server Manager 正在結束 (結束代碼: {ExitCode})", e.ApplicationExitCode);
            AppLogging.Shutdown();
        }
        finally
        {
            if (_singleInstanceMutex is not null)
            {
                try
                {
                    _singleInstanceMutex.ReleaseMutex();
                }
                catch
                {
                }

                _singleInstanceMutex.Dispose();
                _singleInstanceMutex = null;
            }

            base.OnExit(e);
        }
    }

    private static void App_DispatcherUnhandledException(object sender, DispatcherUnhandledExceptionEventArgs e)
    {
        Logger.Error(e.Exception, "Dispatcher 攔截到未處理例外: {Message}", e.Exception.Message);

        MessageBox.Show(
            $"應用程式發生未預期的例外：\n\n{e.Exception.Message}\n\n堆疊追蹤：\n{e.Exception.StackTrace}",
            "Minecraft Server Manager 錯誤",
            MessageBoxButton.OK,
            MessageBoxImage.Error);

        e.Handled = true;
    }

    private static void CurrentDomain_UnhandledException(object sender, UnhandledExceptionEventArgs e)
    {
        if (e.ExceptionObject is Exception ex)
        {
            Logger.Error(ex, "AppDomain 攔截到致命未處理例外: {Message}", ex.Message);

            MessageBox.Show(
                $"應用程式發生致命錯誤：\n\n{ex.Message}\n\n堆疊追蹤：\n{ex.StackTrace}",
                "Minecraft Server Manager 致命錯誤",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
        }
    }
}
