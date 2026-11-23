using MinecraftServerManager.Core.Ports;

namespace MinecraftServerManager.UnitTests.TestSupport;

/// <summary>測試用更新檢查結果工廠</summary>
internal static class TestUpdateResults
{
    public static UpdateCheckResult Create(
        bool hasUpdate = true,
        string currentVersion = "2.0.0",
        string latestVersion = "2.0.1",
        string releaseTitle = "2.0.1",
        string releaseNotes = "測試更新",
        string? downloadUrl = "https://github.com/Colin955023/MinecraftServerManager/releases/download/v2.0.1/MinecraftServerManager-2.0.1.exe",
        string? sha256ChecksumUrl = "https://github.com/Colin955023/MinecraftServerManager/releases/download/v2.0.1/MinecraftServerManager-2.0.1.exe.sha256",
        string releasePageUrl = "https://example.com") =>
        new(
            hasUpdate,
            currentVersion,
            latestVersion,
            releaseTitle,
            releaseNotes,
            downloadUrl,
            sha256ChecksumUrl,
            releasePageUrl);
}
