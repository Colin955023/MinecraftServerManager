namespace MinecraftServerManager.Infrastructure.Utilities;

/// <summary>進度回報節流器：當百分比變動或距離上次報告已達指定間隔時才放行</summary>
internal sealed class ProgressThrottle(TimeSpan interval, TimeProvider timeProvider)
{
    private readonly TimeProvider _timeProvider = timeProvider;
    private int _lastPercent = -1;
    private long _lastReportTimestamp;

    /// <summary>判斷距離上次報告是否已達指定間隔；放行時同步更新時間戳記（非執行緒安全）</summary>
    public bool ShouldReport()
    {
        long now = _timeProvider.GetTimestamp();
        if (_lastReportTimestamp != 0 && _timeProvider.GetElapsedTime(_lastReportTimestamp, now) < interval)
        {
            return false;
        }

        _lastReportTimestamp = now;
        return true;
    }

    /// <summary>判斷目前百分比是否應回報進度；放行時同步更新狀態（非執行緒安全）</summary>
    public bool ShouldReport(int percent)
    {
        long now = _timeProvider.GetTimestamp();
        if (percent == _lastPercent && _lastReportTimestamp != 0 && _timeProvider.GetElapsedTime(_lastReportTimestamp, now) < interval)
        {
            return false;
        }

        _lastPercent = percent;
        _lastReportTimestamp = now;
        return true;
    }
}
