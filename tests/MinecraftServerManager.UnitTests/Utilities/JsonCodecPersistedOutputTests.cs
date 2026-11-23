using System.Text;
using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Java;
using MinecraftServerManager.Infrastructure.Mods;
using MinecraftServerManager.Infrastructure.Servers;
using MinecraftServerManager.Infrastructure.Services;
using MinecraftServerManager.Infrastructure.Settings;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.UnitTests.Utilities;

/// <summary>鎖定 <see cref="JsonCodec"/> 對各持久化型別的輸出，避免序列化設定異動時悄悄改變檔案內容</summary>
public sealed class JsonCodecPersistedOutputTests
{
    private static string Lf(string text) => text.ReplaceLineEndings("\n");

    [Fact]
    public void Serialize_PersistedTypes_ProducesStableCompactOutput()
    {
        Assert.Equal(
            """{"name":"A","minecraftVersion":"1.21","loaderType":"Vanilla","loaderVersion":"","memoryMaxMb":2048,"memoryMinMb":null,"path":"C:\\s","jvmArgs":["-Da"],"backupPath":""}""",
            JsonCodec.Serialize(new ServerConfigPayload("A", "1.21", "Vanilla", string.Empty, 2048, null, @"C:\s", ["-Da"], string.Empty)));
        Assert.Equal("""{"Version":"1.0","Stable":true}""", JsonCodec.Serialize(new LoaderVersion("1.0")));
        Assert.Equal("""[{"ServerName":"S","Pid":1,"StartTimeUtcTicks":2}]""", JsonCodec.Serialize(new List<TrackedServerProcess> { new("S", 1, 2) }));
        Assert.Equal("""{"tag_name":"v1","name":null,"body":null,"html_url":null,"assets":null}""", JsonCodec.Serialize(new GitHubReleasePayload("v1", null, null, null, null)));
        Assert.Equal("""[["a"],["b"]]""", JsonCodec.Serialize(new[] { new[] { "a" }, ["b"] }));
        Assert.Equal("""{"hashes":["h"],"algorithm":"sha512"}""", JsonCodec.Serialize(new ModrinthVersionFilesRequest(["h"], "sha512")));
        Assert.Equal(
            """{"ServerName":"S","OriginalPath":"P","Timestamp":"2026-01-02T03:04:05","SchemaVersion":1}""",
            JsonCodec.Serialize(new DeleteTombstoneRecord("S", "P", new DateTime(2026, 1, 2, 3, 4, 5, DateTimeKind.Unspecified))));
        Assert.Equal("""[{"name":"n","uuid":"u","expiresOn":null}]""", JsonCodec.Serialize(new List<ServerUserCacheEntry> { new("n", "u", null) }));
        Assert.Equal("""[{"uuid":"u","name":"n","level":4,"bypassesPlayerLimit":false}]""", JsonCodec.Serialize(new List<ServerOperatorEntry> { new("u", "n", 4, false) }));
        Assert.Equal("""[{"uuid":"u","name":"n"}]""", JsonCodec.Serialize(new List<ServerWhitelistEntry> { new("u", "n") }));
        Assert.Equal(
            """[{"uuid":"u","name":"n","created":"c","source":"s","expires":"e","reason":"r"}]""",
            JsonCodec.Serialize(new List<ServerBannedPlayerEntry> { new("u", "n", "c", "s", "e", "r") }));
        Assert.Equal(
            """[{"ip":"i","created":"c","source":"s","expires":"e","reason":"r"}]""",
            JsonCodec.Serialize(new List<ServerBannedIpEntry> { new("i", "c", "s", "e", "r") }));
    }

    [Fact]
    public void Serialize_IndentedAndRelaxed_ProducesStableOutput()
    {
        Assert.Equal(
            Lf("""
            {
              "servers_root": "",
              "auto_update_enabled": true,
              "window_preferences": {
                "main_window": {
                  "width": 1350,
                  "height": 820,
                  "x": null,
                  "y": null,
                  "maximized": false
                },
                "theme_mode": "system",
                "custom_accent_color": null
              },
              "auto_backup_before_start": false,
              "backup_retention_count": 10
            }
            """),
            JsonCodec.Serialize(new UserSettings(), indented: true).ReplaceLineEndings("\n"));
        Assert.Equal(
            Lf("""
            {
              "k": {
                "Metadata": null,
                "Hashes": null,
                "FileSizeBytes": 3,
                "LastWriteTimeUtcTicks": 0
              }
            }
            """),
            Encoding.UTF8.GetString(JsonCodec.SerializeToUtf8Bytes(new Dictionary<string, ModCacheEntry> { ["k"] = new() { FileSizeBytes = 3 } }, indented: true)!).ReplaceLineEndings("\n"));
        Assert.Equal(
            Lf("""
            [
              {
                "enabled": true,
                "name": "中文",
                "version": "1",
                "minecraftVersion": "m",
                "loaderType": "l",
                "author": "a",
                "filename": "f",
                "id": "i",
                "fileSize": "s",
                "modifiedTime": "t",
                "description": "d"
              }
            ]
            """),
            JsonCodec.SerializeRelaxed(new List<ModListExporter.CleanRow> { new(true, "中文", "1", "m", "l", "a", "f", "i", "s", "t", "d") }).ReplaceLineEndings("\n"));
    }

    [Fact]
    public void Deserialize_MixedCaseNested_RoundTrips()
    {
        var settings = JsonCodec.Deserialize<UserSettings>("""{"SERVERS_ROOT":"x","Window_Preferences":{"THEME_MODE":"dark"}}""");
        Assert.NotNull(settings);
        Assert.Equal("x", settings.ServersRoot);
        Assert.Equal("dark", settings.WindowPreferences.ThemeMode);

        var cache = JsonCodec.Deserialize<Dictionary<string, ModCacheEntry>>("""{"k":{"metadata":{"a":"b"},"filesizebytes":7}}""");
        Assert.NotNull(cache);
        Assert.Equal("b", cache["k"].Metadata!["a"]);
        Assert.Equal(7, cache["k"].FileSizeBytes);

        var java = JsonCodec.Deserialize<JavaCachePayload>("""{"candidates":[{"path":"p","major":21}]}""");
        Assert.NotNull(java);
        Assert.Equal(21, Assert.Single(java.Candidates).MajorVersion);
    }

    [Fact]
    public void TryReadFile_VariousFiles_ReturnsValueOrNull()
    {
        using var temp = new TempDirectory("msm-json-");
        string valid = temp.Combine("valid.json");
        File.WriteAllText(valid, """{"a":"b"}""");
        string invalid = temp.Combine("invalid.json");
        File.WriteAllText(invalid, "not-json");

        Assert.Equal("b", JsonCodec.TryReadFile<Dictionary<string, string>>(valid)!["a"]);
        Assert.Null(JsonCodec.TryReadFile<Dictionary<string, string>>(valid, maxBytes: 2));
        Assert.Null(JsonCodec.TryReadFile<Dictionary<string, string>>(invalid));
        Assert.Null(JsonCodec.TryReadFile<Dictionary<string, string>>(temp.Combine("missing.json")));
    }
}
