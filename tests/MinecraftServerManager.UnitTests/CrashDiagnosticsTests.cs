using MinecraftServerManager.Infrastructure.Logging;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class CrashDiagnosticsTests
{
    [Fact]
    public void CheckPreviousSession_WithoutMarker_ReturnsNull()
    {
        string dir = Directory.CreateTempSubdirectory("msm-crash-").FullName;
        try
        {
            Assert.Null(CrashDiagnostics.CheckPreviousSession(dir));
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public void CheckPreviousSession_WithLeftoverMarker_ReportsProcessAndLogTail()
    {
        string dir = Directory.CreateTempSubdirectory("msm-crash-").FullName;
        try
        {
            string logFile = Path.Combine(dir, "previous.log");
            File.WriteAllLines(logFile, Enumerable.Range(1, 30).Select(static i => $"line {i}"));
            CrashDiagnostics.WriteSessionMarker(dir, 4321, logFile);

            UncleanExitReport? report = CrashDiagnostics.CheckPreviousSession(dir);

            Assert.NotNull(report);
            Assert.Equal("4321", report.ProcessId);
            Assert.Equal(logFile, report.LogFilePath);
            Assert.Equal(20, report.LogTail.Count);
            Assert.Equal("line 30", report.LogTail[^1]);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public void ClearSessionMarker_RemovesMarkerSoNextStartIsClean()
    {
        string dir = Directory.CreateTempSubdirectory("msm-crash-").FullName;
        try
        {
            CrashDiagnostics.WriteSessionMarker(dir, 1, null);
            CrashDiagnostics.ClearSessionMarker(dir);

            Assert.False(File.Exists(Path.Combine(dir, CrashDiagnostics.SessionMarkerFileName)));
            Assert.Null(CrashDiagnostics.CheckPreviousSession(dir));
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
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
