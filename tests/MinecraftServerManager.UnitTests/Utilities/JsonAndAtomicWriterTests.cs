using System.Text.Json;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.UnitTests.Utilities;

public sealed class JsonAndAtomicWriterTests
{
    [Fact]
    public void JsonCodecDeserialize_ValidOrInvalidBytes_ReturnsValueOrDefault()
    {
        var valid = JsonCodec.Deserialize<Infrastructure.Settings.WindowPreferences>("{\"theme_mode\":\"dark\"}"u8);
        Assert.NotNull(valid);
        Assert.Equal("dark", valid!.ThemeMode);

        Assert.Null(JsonCodec.Deserialize<Infrastructure.Settings.WindowPreferences>("not-json"u8));
    }

    [Fact]
    public void ReadRegularFile_OversizedFile_Rejects()
    {
        using var directory = new TempDirectory("msm-json-");
        string oversized = Path.Combine(directory.FullName, "oversized.json");
        File.WriteAllText(oversized, "{}xxxxx");

        Assert.Throws<IOException>(() => Infrastructure.FileSystem.SafeFileSystem.ReadRegularFile(oversized, maxBytes: 2));
    }

    [Fact]
    public void WriteJson_UnchangedContent_SkipsWrite()
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
    public void WriteText_ConcurrentWrites_KeepsFilesIntact()
    {
        using var directory = new TempDirectory("msm-atomic-concurrency-");
        // 50 個不同路徑並行寫入：每個檔案內容皆須正確
        bool[] results = new bool[50];
        Parallel.For(0, results.Length, i =>
            results[i] = AtomicFileWriter.WriteText(Path.Combine(directory.FullName, $"file_{i}.txt"), $"content_{i}"));

        Assert.All(results, Assert.True);
        for (int i = 0; i < results.Length; i++)
        {
            Assert.Equal($"content_{i}", File.ReadAllText(Path.Combine(directory.FullName, $"file_{i}.txt")));
        }

        // 同一路徑並行競爭：最終內容須完整等於其中一次寫入，不得交錯或截斷
        string sharedPath = Path.Combine(directory.FullName, "shared.txt");
        string[] candidates = [.. Enumerable.Range(0, 20).Select(static i => $"val_{i}")];
        Parallel.ForEach(candidates, value => AtomicFileWriter.WriteText(sharedPath, value));

        Assert.Contains(File.ReadAllText(sharedPath), candidates);
        Assert.Equal(results.Length + 1, Directory.GetFiles(directory.FullName).Length);
    }
}
