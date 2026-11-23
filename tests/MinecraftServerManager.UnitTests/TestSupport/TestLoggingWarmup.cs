using System.Runtime.CompilerServices;

namespace MinecraftServerManager.UnitTests.TestSupport;

/// <summary>測試組件載入時先將使用者資料目錄導向專屬暫存目錄，再初始化記錄管線</summary>
internal static class TestLoggingWarmup
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        var userDataRoot = new TempDirectory("msm-unittest-data-");
        Environment.SetEnvironmentVariable("MSM_USER_DATA_DIR", userDataRoot.FullName);
        AppDomain.CurrentDomain.ProcessExit += (_, _) =>
        {
            // 先釋放記錄檔鎖定，暫存目錄才能刪除
            AppLogging.Shutdown();
            userDataRoot.Dispose();
        };
        AppLogging.Initialize();
    }
}
