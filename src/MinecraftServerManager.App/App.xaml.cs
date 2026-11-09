using System.Runtime.InteropServices;
using Microsoft.UI.Xaml;
using Microsoft.Windows.AppLifecycle;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Settings;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.App;

/// <summary>
/// 應用程式進入點與整體生命週期管理
/// </summary>
public partial class App : Application
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(App));
    private static readonly bool s_isSmokeTest = Environment.GetCommandLineArgs().Any(a => string.Equals(a, "--smoke-test", StringComparison.OrdinalIgnoreCase));
    private static Mutex? s_singleInstanceMutex;

    private static int s_unhandledExceptionCount;
    private static long s_lastUnhandledExceptionTicks;
    private const int MaxConsecutiveExceptions = 3;
    private static readonly TimeSpan ExceptionThrottleWindow = TimeSpan.FromSeconds(5);

    private const uint MB_OK = 0x00000000;
    private const uint MB_ICONERROR = 0x00000010;
    private const uint MB_ICONWARNING = 0x00000030;
    private const uint MB_ICONINFORMATION = 0x00000040;

    [LibraryImport("user32.dll", EntryPoint = "MessageBoxW", StringMarshalling = StringMarshalling.Utf16)]
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    private static partial int MessageBox(IntPtr hWnd, string lpText, string lpCaption, uint uType);

    public static MainWindow? MainWindowInstance { get; private set; }
    public static AppCompositionRoot? CompositionRoot { get; private set; }

    public App()
    {
        InitializeComponent();
    }

    public static void ReleaseSingleInstanceLock()
    {
        try
        {
            AppInstance.GetCurrent().UnregisterKey();
        }
        catch (Exception ex)
        {
            Logger.Warning("解除 AppInstance 單一實體註冊異常: {0}", ex.Message);
        }

        if (s_singleInstanceMutex is not null)
        {
            try
            {
                s_singleInstanceMutex.ReleaseMutex();
            }
            catch (ApplicationException ex)
            {
                Logger.Warning("釋放單一實體 Mutex 異常: {0}", ex.Message);
            }
            s_singleInstanceMutex.Dispose();
            s_singleInstanceMutex = null;
        }
    }

    private static void ShowNativeMessageBox(string text, string caption, uint type)
    {
        if (!s_isSmokeTest)
        {
            MessageBox(IntPtr.Zero, text, caption, type);
        }
    }

    protected override async void OnLaunched(LaunchActivatedEventArgs args)
    {
        base.OnLaunched(args);

        // 1. 最先註冊全域未處理例外處理常式
        UnhandledException += App_UnhandledException;
        AppDomain.CurrentDomain.UnhandledException += CurrentDomain_UnhandledException;
        TaskScheduler.UnobservedTaskException += TaskScheduler_UnobservedTaskException;

        // 2. 單一實體防護（順序固定：先 AppInstance 喚醒既有實例，後 Mutex 互斥防範 2.1.x）
        try
        {
            var mainInstance = AppInstance.FindOrRegisterForKey("MinecraftServerManager");
            if (!mainInstance.IsCurrent)
            {
                var activatedArgs = AppInstance.GetCurrent().GetActivatedEventArgs();
                await mainInstance.RedirectActivationToAsync(activatedArgs);
                Environment.Exit(0);
                return;
            }

            s_singleInstanceMutex = new Mutex(true, "MinecraftServerManagerMutex", out bool createdNew);
            if (!createdNew)
            {
                s_singleInstanceMutex.Dispose();
                s_singleInstanceMutex = null;
                ShowNativeMessageBox(
                    $"{AppInfo.AppEnglishName} 已由舊版 (v2.1.x) 執行中，請勿重複啟動。",
                    "提示",
                    MB_OK | MB_ICONINFORMATION);
                Environment.Exit(0);
                return;
            }
        }
        catch (Exception ex)
        {
            ShowNativeMessageBox(
                $"單一實體檢查失敗：\n{ex.Message}",
                "Minecraft Server Manager 啟動錯誤",
                MB_OK | MB_ICONERROR);
            Environment.Exit(1);
            return;
        }

        // 3. 初始化記錄系統管線
        AppLogging.Initialize();
        Logger.Information("Minecraft Server Manager 啟動中 (版本 {0})", AppInfo.Version);

        // 原生層級閃退（WinUI 快速失敗）不會經過受控例外處理常式，改以工作階段標記與 UI 執行緒例外追蹤留下線索
        CrashDiagnostics.Install(Environment.CurrentManagedThreadId);

        try
        {
            var settingsManager = new SettingsManager();

            // 4. 建立主視窗與 WinUiService
            var mainWindow = new MainWindow();
            MainWindowInstance = mainWindow;

            var uiService = new WinUiService(mainWindow.DispatcherQueue);
            uiService.RegisterMainWindow(mainWindow);

            // 5. 伺服器存放目錄檢查與引導
            // 維持於 UI 執行緒繼續，確保後續組合根與 ViewModel 皆於 UI 執行緒建立
            string? serversRoot = await EnsureServersRootConfiguredAsync(settingsManager, uiService).ConfigureAwait(true);
            if (string.IsNullOrWhiteSpace(serversRoot))
            {
                Logger.Information("使用者未選取伺服器目錄或選擇結束，正常關閉應用程式");
                uiService.ShutdownApplication(0);
                return;
            }

            // 6. 建構組合根並載入主畫面
            CompositionRoot = new AppCompositionRoot(serversRoot, uiService, settingsManager);

            uiService.PostToUi(() =>
            {
                mainWindow.InitializeViewModel(CompositionRoot);
                mainWindow.Activate();
                CompositionRoot.StartBackgroundWarmup();

                if (s_isSmokeTest)
                {
                    Logger.Information("偵測到 --smoke-test 參數，將於 2 秒後安全結束以供發佈測試驗證");
                    var timer = mainWindow.DispatcherQueue.CreateTimer();
                    timer.Interval = TimeSpan.FromSeconds(2);
                    timer.Tick += (s, e) =>
                    {
                        timer.Stop();
                        Logger.Information("煙霧測試完成，正常結束");
                        Environment.Exit(0);
                    };
                    timer.Start();
                }
            });
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "應用程式啟動初始化流程發生例外: {0}", ex.Message);
            string logsDir = RuntimePaths.GetLogDir();
            ShowNativeMessageBox(
                $"應用程式啟動失敗：\n\n{ex.Message}\n\n詳細記錄請見：\n{logsDir}",
                "Minecraft Server Manager 啟動錯誤",
                MB_OK | MB_ICONERROR);
            Environment.Exit(1);
        }
    }

    private static async Task<string?> EnsureServersRootConfiguredAsync(SettingsManager settings, WinUiService ui)
    {
        string current = settings.GetServersRoot();
        if (s_isSmokeTest && string.IsNullOrWhiteSpace(current))
        {
            string smokeServers = Path.Combine(RuntimePaths.GetUserDataDir(), "servers");
            settings.SetServersRoot(smokeServers);
            return settings.GetValidatedServersRootPath(create: true);
        }

        if (!string.IsNullOrWhiteSpace(current))
        {
            try
            {
                string validated = settings.GetValidatedServersRootPath(create: true);
                Logger.Information("已驗證既有伺服器存放目錄: {0}", validated);
                return validated;
            }
            catch (Exception ex)
            {
                Logger.Warning("既有伺服器目錄設定無效 ({0})，重新提示選取", ex.Message);
            }
        }

        while (true)
        {
            string? selectedFolder = await ui.PickFolderAsync("請選擇存放所有 Minecraft 伺服器的主資料夾").ConfigureAwait(true);

            if (!string.IsNullOrWhiteSpace(selectedFolder))
            {
                try
                {
                    settings.SetServersRoot(selectedFolder);
                    string validated = settings.GetValidatedServersRootPath(create: true);
                    Logger.Information("使用者成功設定伺服器存放目錄: {0}", validated);
                    return validated;
                }
                catch (Exception ex)
                {
                    Logger.Error(ex, "寫入伺服器目錄設定失敗: {0}", ex.Message);
                    await ui.ShowErrorAsync($"無法寫入設定或建立資料夾：{ex.Message}", "設定錯誤").ConfigureAwait(true);
                }
            }
            else
            {
                bool exitApp = await ui.ConfirmAsync(
                    "未選擇資料夾，是否要結束程式？",
                    "結束程式",
                    UiMessageLevel.Question).ConfigureAwait(true);

                if (exitApp)
                {
                    return null;
                }
            }
        }
    }

    private void App_UnhandledException(object sender, Microsoft.UI.Xaml.UnhandledExceptionEventArgs e)
    {
        Logger.Error(e.Exception, "WinUI 攔截到未處理例外: {0}", e.Exception.Message);

        string logsDir = RuntimePaths.GetLogDir();
        bool shouldTerminate = RecordAndCheckThrottling();

        if (shouldTerminate)
        {
            ShowNativeMessageBox(
                $"應用程式發生頻繁且嚴重的未處理例外：\n\n{e.Exception.Message}\n\n為避免資料損毀，應用程式即將結束。\n詳細堆疊與錯誤資訊已儲存於記錄檔目錄：\n{logsDir}",
                "Minecraft Server Manager 致命錯誤",
                MB_OK | MB_ICONERROR);

            Environment.Exit(1);
            return;
        }

        ShowNativeMessageBox(
            $"應用程式發生未預期的例外：\n\n{e.Exception.Message}\n\n詳細堆疊與錯誤資訊已記錄於記錄檔目錄：\n{logsDir}",
            "Minecraft Server Manager 錯誤",
            MB_OK | MB_ICONWARNING);

        e.Handled = true;
    }

    private static void TaskScheduler_UnobservedTaskException(object? sender, UnobservedTaskExceptionEventArgs e)
    {
        Logger.Error(e.Exception, "TaskScheduler 攔截到未觀察任務例外: {0}", e.Exception.Message);
        e.SetObserved();
    }

    private static void CurrentDomain_UnhandledException(object sender, System.UnhandledExceptionEventArgs e)
    {
        if (e.ExceptionObject is Exception ex)
        {
            Logger.Error(ex, "AppDomain 攔截到致命未處理例外: {0}", ex.Message);

            string logsDir = RuntimePaths.GetLogDir();
            ShowNativeMessageBox(
                $"應用程式發生致命錯誤：\n\n{ex.Message}\n\n詳細堆疊與錯誤資訊已記錄於記錄檔目錄：\n{logsDir}",
                "Minecraft Server Manager 致命錯誤",
                MB_OK | MB_ICONERROR);
        }
    }

    private static bool RecordAndCheckThrottling()
    {
        long nowTicks = DateTime.UtcNow.Ticks;
        long lastTicks = Interlocked.Exchange(ref s_lastUnhandledExceptionTicks, nowTicks);
        if (nowTicks - lastTicks <= ExceptionThrottleWindow.Ticks)
        {
            int count = Interlocked.Increment(ref s_unhandledExceptionCount);
            return count >= MaxConsecutiveExceptions;
        }

        Interlocked.Exchange(ref s_unhandledExceptionCount, 1);
        return false;
    }
}
