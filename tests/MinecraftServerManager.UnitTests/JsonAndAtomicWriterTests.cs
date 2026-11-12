using System.Text.Json;
using MinecraftServerManager.Infrastructure.Utilities;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class JsonAndAtomicWriterTests
{
    [Fact]
    public void JsonCodecDeserializesValidBytesAndReturnsDefaultForInvalid()
    {
        var valid = JsonCodec.Deserialize<Infrastructure.Settings.WindowPreferences>("{\"theme_mode\":\"dark\"}"u8);
        Assert.NotNull(valid);
        Assert.Equal("dark", valid!.ThemeMode);

        Assert.Null(JsonCodec.Deserialize<Infrastructure.Settings.WindowPreferences>("not-json"u8));
    }

    [Fact]
    public void ReadRegularFileRejectsOversizedFile()
    {
        using var directory = new TempDirectory("msm-json-");
        string oversized = Path.Combine(directory.FullName, "oversized.json");
        File.WriteAllText(oversized, "{}xxxxx");

        Assert.Throws<IOException>(() => Infrastructure.FileSystem.SafeFileSystem.ReadRegularFile(oversized, maxBytes: 2));
    }

    [Fact]
    public void AtomicFileWriterWritesJsonAndSkipsUnchangedContent()
    {
        using var directory = new TempDirectory("msm-atomic-");
        string file = Path.Combine(directory.FullName, "settings.json");
        var prefs = new Infrastructure.Settings.WindowPreferences { ThemeMode = "dark" };
        Assert.True(AtomicFileWriter.WriteJson(file, prefs));
        var before = File.GetLastWriteTimeUtc(file);
        Assert.True(AtomicFileWriter.WriteJson(file, prefs, skipIfUnchanged: true));
        Assert.Equal(before, File.GetLastWriteTimeUtc(file));
        Assert.True(JsonDocument.Parse(File.ReadAllBytes(file)).RootElement.TryGetProperty("theme_mode", out var prop) && prop.GetString() == "dark");
    }

    [Fact]
    public void AtomicFileWriterHandlesConcurrentWritesCorrectlyWithLockStriping()
    {
        using var directory = new TempDirectory("msm-atomic-concurrency-");
        // 測試 50 個不同路徑的並行寫入
        Parallel.For(0, 50, i =>
        {
            string path = Path.Combine(directory.FullName, $"file_{i}.txt");
            bool success = AtomicFileWriter.WriteText(path, $"content_{i}");
            Assert.True(success);
        });

        // 測試同一路徑的並行寫入競爭
        string sharedPath = Path.Combine(directory.FullName, "shared.txt");
        Parallel.For(0, 20, i =>
        {
            AtomicFileWriter.WriteText(sharedPath, $"val_{i}");
        });

        Assert.True(File.Exists(sharedPath));
        Assert.NotEmpty(File.ReadAllText(sharedPath));
    }
}
