using System.Windows;
using System.Windows.Threading;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App;

public partial class App : Application
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("App");

    protected override void OnStartup(StartupEventArgs e)
    {
        AppLogging.Initialize();
        Logger.Information("Minecraft Server Manager 啟動中 (版本 2.0.0)");

        base.OnStartup(e);

        DispatcherUnhandledException += App_DispatcherUnhandledException;
        AppDomain.CurrentDomain.UnhandledException += CurrentDomain_UnhandledException;
    }

    protected override void OnExit(ExitEventArgs e)
    {
        Logger.Information("Minecraft Server Manager 正在結束 (結束代碼: {ExitCode})", e.ApplicationExitCode);
        AppLogging.Shutdown();
        base.OnExit(e);
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
