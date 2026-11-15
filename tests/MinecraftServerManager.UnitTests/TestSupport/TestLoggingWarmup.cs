using System.Runtime.CompilerServices;

namespace MinecraftServerManager.UnitTests.TestSupport;

/// <summary>測試組件載入時先初始化記錄管線，避免平行初始化互相等待</summary>
internal static class TestLoggingWarmup
{
    [ModuleInitializer]
    internal static void Initialize() => AppLogging.Initialize();
}
