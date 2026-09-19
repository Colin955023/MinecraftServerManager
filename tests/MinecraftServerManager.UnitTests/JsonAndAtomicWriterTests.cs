using System.Text.Json;
using MinecraftServerManager.Infrastructure.Utilities;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class JsonAndAtomicWriterTests
{
    [Fact]
    public void JsonCodecReadsTheOriginalBytesAndDocument()
    {
        var directory = Directory.CreateTempSubdirectory("msm-json-");
        try
        {
            string file = Path.Combine(directory.FullName, "settings.json");
            const string content = "{\"enabled\":true}";
            File.WriteAllText(file, content);

            using var result = JsonCodec.ReadJsonWithBytes(file);

            Assert.NotNull(result);
            Assert.Equal(content, System.Text.Encoding.UTF8.GetString(result!.RawBytes));
            Assert.True(result.Document.RootElement.GetProperty("enabled").GetBoolean());
        }
        finally
        {
            directory.Delete(true);
        }
    }

    [Fact]
    public void JsonCodecRejectsInvalidAndOversizedJson()
    {
        var directory = Directory.CreateTempSubdirectory("msm-json-");
        try
        {
            string invalid = Path.Combine(directory.FullName, "invalid.json");
            string oversized = Path.Combine(directory.FullName, "oversized.json");
            File.WriteAllText(invalid, "not-json");
            File.WriteAllText(oversized, "{}xxxxx");

            Assert.Null(JsonCodec.ReadJson(invalid));
            Assert.Null(JsonCodec.ReadJson(oversized, maxBytes: 2));
        }
        finally
        {
            directory.Delete(true);
        }
    }

    [Fact]
    public void AtomicFileWriterWritesJsonAndSkipsUnchangedContent()
    {
        var directory = Directory.CreateTempSubdirectory("msm-atomic-");
        try
        {
            string file = Path.Combine(directory.FullName, "settings.json");
            Assert.True(AtomicFileWriter.WriteJson(file, new { enabled = true }));
            var before = File.GetLastWriteTimeUtc(file);
            Assert.True(AtomicFileWriter.WriteJson(file, new { enabled = true }, skipIfUnchanged: true));
            Assert.Equal(before, File.GetLastWriteTimeUtc(file));
            Assert.True(JsonDocument.Parse(File.ReadAllBytes(file)).RootElement.GetProperty("enabled").GetBoolean());
        }
        finally
        {
            directory.Delete(true);
        }
    }
}
