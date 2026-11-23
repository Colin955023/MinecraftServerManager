using System.Runtime.InteropServices;
using Microsoft.UI.Xaml;
using Microsoft.Windows.AppLifecycle;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Process;
using MinecraftServerManager.Infrastructure.Settings;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.App;

/// <summary>應用程式進入點與整體生命週期管理</summary>
public partial class App : Application
{
    private const int MaxConsecutiveExceptions = 3;
    private const uint MB_OK = 0x00000000;
    private const uint MB_ICONERROR = 0x00000010;
    private const uint MB_ICONWARNING = 0x00000030;

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(App));
    private static readonly bool IsSmokeTest = Environment.GetCommandLineArgs().Any(a => string.Equals(a, "--smoke-test", StringComparison.OrdinalIgnoreCase));
    private static readonly TimeSpan ExceptionThrottleWindow = TimeSpan.FromSeconds(5);

    private static int s_unhandledExceptionCount;
    private static long s_lastUnhandledExceptionTicks;

    public App()
    {
        InitializeComponent();
    }

    private static string SingleInstanceKey => IsSmokeTest ? $"MinecraftServerManager.SmokeTest.{Environment.ProcessId}" : "MinecraftServerManager";

    [LibraryImport("user32.dll", EntryPoint = "MessageBoxW", StringMarshalling = StringMarshalling.Utf16)]
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    private static partial int MessageBox(IntPtr hWnd, string lpText, string lpCaption, uint uType);

    public static void ReleaseSingleInstanceLock()
    {
        try
        {
            AppInstance.GetCurrent().UnregisterKey();
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "解除 AppInstance 單一實體註冊失敗");
        }
    }

    /// <summary>重新啟動失敗時重新註冊單一實體金鑰，避免使用者另開第二個執行個體</summary>
    public static void ReacquireSingleInstanceLock()
    {
        try
        {
            AppInstance.FindOrRegisterForKey(SingleInstanceKey);
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "重新註冊 AppInstance 單一實體失敗");
        }
    }

    private static void ShowNativeMessageBox(string text, string caption, uint type)
    {
        if (!IsSmokeTest)
        {
            MessageBox(IntPtr.Zero, text, caption, type);
        }
    }

    private static void ShowNativeErrorMessageBox(
        string prefix,
        Exception ex,
        string caption = "Minecraft Server Manager 啟動錯誤",
        uint type = MB_OK | MB_ICONERROR,
        string? extraNote = null)
    {
        string logsDir = RuntimePaths.GetLogDir();
        string note = string.IsNullOrWhiteSpace(extraNote) ? string.Empty : $"\n{extraNote}";
        ShowNativeMessageBox(
            $"{prefix}：\n\n{ex.Message}{note}\n\n詳細記錄請見：\n{logsDir}",
            caption,
            type);
    }

    [System.Diagnostics.CodeAnalysis.SuppressMessage("Reliability", "CA2000:Dispose objects before losing scope", Justification = "主視窗生命週期等同應用程式，由視窗關閉流程釋放")]
    protected override async void OnLaunched(LaunchActivatedEventArgs args)
    {
        base.OnLaunched(args);

        // 1. 最先註冊全域未處理例外處理常式
        UnhandledException += OnAppUnhandledException;
        AppDomain.CurrentDomain.UnhandledException += OnCurrentDomainUnhandledException;
        TaskScheduler.UnobservedTaskException += OnUnobservedTaskException;

        // 2. 單一實體防護：AppInstance 喚醒既有執行個體（煙霧測試改用獨立金鑰，避免與既有實例衝突誤判）
        try
        {
            var mainInstance = AppInstance.FindOrRegisterForKey(SingleInstanceKey);
            if (!mainInstance.IsCurrent)
            {
                var activatedArgs = AppInstance.GetCurrent().GetActivatedEventArgs();
                await mainInstance.RedirectActivationToAsync(activatedArgs);
                Environment.Exit(0);
                return;
            }
        }
        catch (OperationCanceledException)
        {
            Logger.Information("單一實體檢查已取消");
        }
        catch (Exception ex)
        {
            ShowNativeErrorMessageBox("單一實體檢查失敗", ex);
            Environment.Exit(1);
            return;
        }

        // 3. 初始化記錄系統管線
        AppLogging.Initialize();
        Logger.Information("Minecraft Server Manager 啟動中（版本 {Version}）", AppInfo.Version);

        // 原生閃退不經受控例外處理，改以工作階段標記與 UI 例外追蹤留線索
        CrashDiagnostics.Install(Environment.CurrentManagedThreadId);

        // 最後註冊：其他結束處理常式寫完記錄後再排清並釋放記錄檔
        AppDomain.CurrentDomain.ProcessExit += static (_, _) => AppLogging.Shutdown();

        try
        {
            var settingsManager = new SettingsManager(RuntimePaths.GetUserDataDir());

            // 4. 先套用強調色再建立視窗，使控制項一開始就解析到可就地更新的筆刷
            var dispatcherQueue = Microsoft.UI.Dispatching.DispatcherQueue.GetForCurrentThread();
            var accentColorService = new AccentColorService(action => dispatcherQueue.TryEnqueue(() => action()));
            accentColorService.ApplyAccentColor(settingsManager.GetCustomAccentColor());

            var mainWindow = new MainWindow();
            var processRunner = new ProcessRunner();
            var uiService = new WinUiService(dispatcherQueue, processRunner, accentColorService);
            uiService.RegisterMainWindow(mainWindow);

            // 再次啟動時由重新導向的啟用事件喚醒既有主視窗，關閉時解除訂閱避免洩漏
            var currentInstance = AppInstance.GetCurrent();
            void OnInstanceActivated(object? sender, AppActivationArguments e) => uiService.ActivateMainWindow();
            currentInstance.Activated += OnInstanceActivated;
            mainWindow.Closed += (_, _) =>
            {
                currentInstance.Activated -= OnInstanceActivated;
                uiService.Dispose();
                accentColorService.Dispose();
            };

            // 5. 先還原位置並啟用主視窗，待內容載入取得 XamlRoot 後才能顯示目錄引導對話框
            mainWindow.PrepareForActivation(settingsManager, uiService);
            mainWindow.Activate();
            await mainWindow.WaitForLoadedAsync();

            string? serversRoot = await EnsureServersRootConfiguredAsync(settingsManager, uiService);
            if (string.IsNullOrWhiteSpace(serversRoot))
            {
                Logger.Information("使用者未選取伺服器目錄或選擇結束，正常關閉應用程式");
                uiService.ShutdownApplication(0);
                return;
            }

            // 6. 建構組合根並載入主畫面
            var compositionRoot = new AppCompositionRoot(serversRoot, uiService, settingsManager, processRunner, new ShellLauncher(ShellLauncher.StartShellProcess), accentColorService);
            mainWindow.InitializeViewModel(compositionRoot);

            if (IsSmokeTest)
            {
                Logger.Information("偵測到 --smoke-test 參數，將於 2 秒後安全結束以供發布測試驗證");
                await Task.Delay(TimeSpan.FromSeconds(2));
                Logger.Information("煙霧測試完成，正常結束");
                Environment.Exit(0);
                return;
            }

            compositionRoot.StartBackgroundWarmup();
        }
        catch (OperationCanceledException)
        {
            Logger.Information("應用程式啟動初始化流程已取消");
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "應用程式啟動初始化流程發生例外");
            ShowNativeErrorMessageBox("應用程式啟動失敗", ex);
            Environment.Exit(1);
        }
    }

    private static async Task<string?> EnsureServersRootConfiguredAsync(SettingsManager settings, WinUiService ui)
    {
        string current = settings.GetServersRoot();
        if (IsSmokeTest && string.IsNullOrWhiteSpace(current))
        {
            string smokeServers = Path.Combine(RuntimePaths.GetUserDataDir(), "servers");
            return await Task.Run(() =>
            {
                settings.SetServersRoot(smokeServers);
                return settings.GetValidatedServersRootPath(create: true);
            });
        }

        if (!string.IsNullOrWhiteSpace(current))
        {
            try
            {
                string validated = await Task.Run(() => settings.GetValidatedServersRootPath(create: true));
                Logger.Information("已驗證既有伺服器存放目錄：{Path}", validated);
                return validated;
            }
            catch (Exception ex)
            {
                Logger.Warning(ex, "既有伺服器目錄設定無效，重新提示選取");
            }
        }

        while (true)
        {
            string? selectedFolder = await ui.PickFolderAsync("請選擇存放所有 Minecraft 伺服器的主資料夾");

            if (!string.IsNullOrWhiteSpace(selectedFolder))
            {
                try
                {
                    string validated = await Task.Run(() =>
                    {
                        settings.SetServersRoot(selectedFolder);
                        return settings.GetValidatedServersRootPath(create: true);
                    });
                    Logger.Information("使用者成功設定伺服器存放目錄：{Path}", validated);
                    return validated;
                }
                catch (Exception ex)
                {
                    Logger.Error(ex, "寫入伺服器目錄設定失敗");
                    await ui.ShowErrorAsync($"無法寫入設定或建立資料夾：{ex.Message}", "設定失敗");
                }
            }
            else
            {
                bool exitApp = await ui.ConfirmAsync(
                    "未選擇資料夾，是否要結束程式？",
                    "結束程式",
                    UiMessageLevel.Question);

                if (exitApp)
                {
                    return null;
                }
            }
        }
    }

    private void OnAppUnhandledException(object sender, Microsoft.UI.Xaml.UnhandledExceptionEventArgs e)
    {
        Logger.Error(e.Exception, "WinUI 攔截到未處理例外");

        bool shouldTerminate = RecordAndCheckThrottling();

        if (shouldTerminate)
        {
            ShowNativeErrorMessageBox(
                "應用程式發生頻繁且嚴重的未處理例外",
                e.Exception,
                "Minecraft Server Manager 致命錯誤",
                MB_OK | MB_ICONERROR,
                "為避免資料損毀，應用程式即將結束。");

            Environment.Exit(1);
            return;
        }

        ShowNativeErrorMessageBox(
            "應用程式發生未預期的例外",
            e.Exception,
            "Minecraft Server Manager 錯誤",
            MB_OK | MB_ICONWARNING);

        e.Handled = true;
    }

    private static void OnUnobservedTaskException(object? sender, UnobservedTaskExceptionEventArgs e)
    {
        Logger.Error(e.Exception, "TaskScheduler 攔截到未觀察任務例外");
        e.SetObserved();
    }

    private static void OnCurrentDomainUnhandledException(object sender, System.UnhandledExceptionEventArgs e)
    {
        if (e.ExceptionObject is Exception ex)
        {
            Logger.Error(ex, "AppDomain 攔截到致命未處理例外");
            ShowNativeErrorMessageBox(
                "應用程式發生致命錯誤",
                ex,
                "Minecraft Server Manager 致命錯誤");
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
