using MinecraftServerManager.Core.Ports;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>伺服器清單的備份狀態、相對時間與記憶體顯示文字</summary>
internal static class ServerStatusFormatter
{
    /// <summary>將備份摘要格式化為清單顯示文字</summary>
    public static string FormatBackupStatus(ServerBackupSummary summary)
    {
        ArgumentNullException.ThrowIfNull(summary);
        return summary.Status switch
        {
            ServerBackupSummaryStatus.NotConfigured => "未設定外部備份",
            ServerBackupSummaryStatus.DirectoryMissing => "備份資料夾不存在",
            ServerBackupSummaryStatus.NoBackups => "尚無備份",
            ServerBackupSummaryStatus.HasBackups when summary.LatestWriteTime is { } latest =>
                $"{summary.Count} 個備份（{FormatRelativeTime(latest)}）",
            ServerBackupSummaryStatus.HasBackups => $"{summary.Count} 個備份",
            _ => "讀取備份失敗",
        };
    }

    /// <summary>將時間格式化為相對時間描述</summary>
    public static string FormatRelativeTime(DateTimeOffset timestamp)
    {
        var span = DateTimeOffset.Now - timestamp;
        if (span < TimeSpan.Zero)
        {
            span = TimeSpan.Zero;
        }

        return span.TotalMinutes switch
        {
            < 1 => "剛剛",
            < 60 => $"{(int)span.TotalMinutes} 分鐘前",
            _ => span.TotalHours < 24
                ? $"{(int)span.TotalHours} 小時前"
                : $"{(int)span.TotalDays} 天前"
        };
    }

    internal static string FormatMemoryDisplay(int? minMb, int maxMb) =>
        minMb is { } min && min > 0
            ? $"{min} MB ~ {maxMb} MB"
            : $"{maxMb} MB";
}
