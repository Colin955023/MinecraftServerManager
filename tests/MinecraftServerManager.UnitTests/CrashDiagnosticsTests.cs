using System.Globalization;
using MinecraftServerManager.Infrastructure.Logging;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class CrashDiagnosticsTests
{
    // 不可能存在的行程識別碼，避免測試相依於本機行程狀態
    private const int DeadProcessId = int.MaxValue - 1;

    [Fact]
    public void CheckPreviousSession_WithoutMarker_ReturnsNull()
    {
        using var dirTemp = new TempDirectory("msm-crash-");
        string dir = dirTemp.FullName;
        Assert.Null(CrashDiagnostics.CheckPreviousSession(dir));
    }

    [Fact]
    public void CheckPreviousSession_WithLeftoverMarker_ReportsProcessAndLogTail()
    {
        using var dirTemp = new TempDirectory("msm-crash-");
        string dir = dirTemp.FullName;
        string logFile = Path.Combine(dir, "previous.log");
        File.WriteAllLines(logFile, Enumerable.Range(1, 30).Select(static i => $"line {i}"));
        CrashDiagnostics.WriteSessionMarker(dir, DeadProcessId, logFile);

        UncleanExitReport? report = CrashDiagnostics.CheckPreviousSession(dir);

        Assert.NotNull(report);
        Assert.Equal(DeadProcessId.ToString(CultureInfo.InvariantCulture), report.ProcessId);
        Assert.Equal(logFile, report.LogFilePath);
        Assert.Equal(20, report.LogTail.Count);
        Assert.Equal("line 30", report.LogTail[^1]);
    }

    [Fact]
    public void ClearSessionMarker_RemovesMarkerSoNextStartIsClean()
    {
        using var dirTemp = new TempDirectory("msm-crash-");
        string dir = dirTemp.FullName;
        CrashDiagnostics.WriteSessionMarker(dir, DeadProcessId, null);
        CrashDiagnostics.ClearSessionMarker(dir, DeadProcessId);

        Assert.False(File.Exists(Path.Combine(dir, CrashDiagnostics.SessionMarkerFileName)));
        Assert.Null(CrashDiagnostics.CheckPreviousSession(dir));
    }

    [Fact]
    public void ClearSessionMarker_MarkerRewrittenByAnotherProcess_KeepsMarker()
    {
        using var dirTemp = new TempDirectory("msm-crash-");
        string dir = dirTemp.FullName;
        CrashDiagnostics.WriteSessionMarker(dir, DeadProcessId, null);

        CrashDiagnostics.ClearSessionMarker(dir, DeadProcessId + 1);

        Assert.True(File.Exists(Path.Combine(dir, CrashDiagnostics.SessionMarkerFileName)));
    }

    [Fact]
    public void CheckPreviousSession_MarkerOwnerStillAlive_IsNotReportedAsCrash()
    {
        using var dirTemp = new TempDirectory("msm-crash-");
        string dir = dirTemp.FullName;
        CrashDiagnostics.WriteSessionMarker(dir, Environment.ProcessId, null);

        Assert.Null(CrashDiagnostics.CheckPreviousSession(dir));
    }

    [Fact]
    public void IsMarkerOwnerAlive_ProcessIdReusedAfterMarkerWritten_ReturnsFalse()
    {
        string longAgo = new DateTime(2000, 1, 1, 0, 0, 0, DateTimeKind.Local).ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture);

        Assert.False(CrashDiagnostics.IsMarkerOwnerAlive(Environment.ProcessId.ToString(CultureInfo.InvariantCulture), longAgo));
        Assert.False(CrashDiagnostics.IsMarkerOwnerAlive("not-a-pid", longAgo));
    }

    [Fact]
    public void FormatFirstChance_IncludesTypeMessageHResultAndLimitedStack()
    {
        var ex = new InvalidOperationException("測試例外");
        string stack = string.Join('\n', Enumerable.Range(1, 30).Select(static i => $"   at Frame{i}()"));

        string text = CrashDiagnostics.FormatFirstChance(ex, stack);

        Assert.Contains("System.InvalidOperationException: 測試例外", text, StringComparison.Ordinal);
        Assert.Contains("HRESULT 0x", text, StringComparison.Ordinal);
        Assert.Contains("Frame1()", text, StringComparison.Ordinal);
        Assert.DoesNotContain("Frame13()", text, StringComparison.Ordinal);
    }
}
