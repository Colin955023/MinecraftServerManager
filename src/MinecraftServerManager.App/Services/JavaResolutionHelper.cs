using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.Services;

/// <summary>Java 執行檔解析與版本最佳匹配輔助</summary>
public static class JavaResolutionHelper
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(JavaResolutionHelper));

    /// <summary>尋找符合指定 major 版本的最佳 Java 執行環境；版本不相符時回傳 null</summary>
    public static async Task<JavaRuntimeInfo?> FindMatchingJavaAsync(
        IJavaRuntimeDetector detector,
        int targetMajor,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(detector);
        try
        {
            var matched = await detector.FindBestMatchAsync(targetMajor, cancellationToken).ConfigureAwait(false);
            if (matched is not null && matched.MajorVersion == targetMajor)
            {
                return matched;
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "偵測 Java {Major} 執行環境時發生錯誤", targetMajor);
        }

        return null;
    }

    /// <summary>列舉本機已安裝的 Java 主要版本清單字串（例如 "Java 17、Java 21"）</summary>
    public static async Task<string> FormatInstalledJavaVersionsAsync(
        IJavaRuntimeDetector detector,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(detector);
        try
        {
            var all = await detector.DetectAsync(forceRefresh: false, cancellationToken).ConfigureAwait(false);
            if (all.Count > 0)
            {
                return string.Join("、", all.Select(static j => j.MajorVersion).Distinct().Order().Select(static m => $"Java {m}"));
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "列舉本機已安裝 Java 清單失敗");
        }

        return "無";
    }
}
