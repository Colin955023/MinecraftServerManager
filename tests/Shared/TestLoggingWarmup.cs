using System.Runtime.CompilerServices;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.TestSupport;

/// <summary>
/// 測試組件載入時先於單一執行緒初始化記錄管線，避免平行測試同時觸發
/// <see cref="AppLogging"/> 與 SafeFileSystem 靜態初始化的相互等待
/// </summary>
internal static class TestLoggingWarmup
{
    [ModuleInitializer]
    internal static void Initialize() => AppLogging.Initialize();
}
