using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Servers;
using MinecraftServerManager.Infrastructure.Settings;
using Xunit;

namespace MinecraftServerManager.UnitTests;

/// <summary>
/// 資料遺失與安全性修正的回歸測試：損毀檔案須保留備份、批次檔參數須加引號、記憶體單位須防溢位、尾端讀取須有界
/// </summary>
public sealed class DataSafetyRegressionTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), "msm-safety-" + Guid.NewGuid().ToString("N"));

    public DataSafetyRegressionTests() => Directory.CreateDirectory(_root);

    public void Dispose()
    {
        try
        {
            Directory.Delete(_root, recursive: true);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            // 測試暫存目錄清理失敗不影響結果
        }
    }

    [Fact]
    public void SettingsManager_CorruptFile_IsPreservedAsBadBeforeDefaultsAreWritten()
    {
        string settingsPath = Path.Combine(_root, "user_settings.json");
        File.WriteAllText(settingsPath, "not-json");

        var manager = new SettingsManager(_root);

        Assert.NotNull(manager.Snapshot);
        Assert.Equal("not-json", File.ReadAllText(settingsPath + ".bad"));
    }

    [Fact]
    public void SettingsManager_MissingFile_DoesNotCreateBadBackup()
    {
        _ = new SettingsManager(_root);

        Assert.False(File.Exists(Path.Combine(_root, "user_settings.json.bad")));
    }

    [Fact]
    public async Task ServerManager_CorruptRegistry_IsPreservedAsBad()
    {
        string serversRoot = Path.Combine(_root, "servers");
        Directory.CreateDirectory(serversRoot);
        string registryPath = Path.Combine(serversRoot, ServerDefaults.RegistryFileName);
        File.WriteAllText(registryPath, "{ broken");

        var manager = TestServerManagers.Create(serversRoot);
        var servers = await manager.GetAllServersAsync();

        Assert.Empty(servers);
        Assert.Equal("{ broken", File.ReadAllText(registryPath + ".bad"));
    }

    [Theory]
    [InlineData("-Xmx2g", 2048)]
    [InlineData("-Xmx512m", 512)]
    [InlineData("-Xmx1t", 1_048_576)]
    public void ParseMemorySetting_ValidUnits(string text, int expectedMb) =>
        Assert.Equal(expectedMb, MemoryUtils.ParseMemorySetting(text));

    [Theory]
    [InlineData("-Xmx99999999999g")]
    [InlineData("-Xmx9999999999t")]
    public void ParseMemorySetting_OverflowingValuesAreRejected(string text) =>
        Assert.Null(MemoryUtils.ParseMemorySetting(text));

    [Theory]
    [InlineData("-Xmx2G", "-Xmx2G")]
    [InlineData("-Dpath=C:\\Program Files\\x", "\"-Dpath=C:\\Program Files\\x\"")]
    public void FormatBatchArgument_QuotesOnlyArgumentsContainingWhitespace(string argument, string expected) =>
        Assert.Equal(expected, StartScriptWriter.FormatBatchArgument(argument));

    [Fact]
    public void ReadTailText_LargeFile_ReturnsOnlyTailAndMarksTruncated()
    {
        string file = Path.Combine(_root, "latest.log");
        File.WriteAllText(file, string.Concat(Enumerable.Range(0, 2000).Select(static i => $"line-{i}\n")));

        string tail = SafeFileSystem.ReadTailText(file, 64, out bool truncated);

        Assert.True(truncated);
        Assert.True(tail.Length <= 64);
        Assert.EndsWith("line-1999\n", tail, StringComparison.Ordinal);
    }

    [Fact]
    public void ReadTailText_SmallFile_ReturnsWholeContentNotTruncated()
    {
        string file = Path.Combine(_root, "small.log");
        File.WriteAllText(file, "a\nb\n");

        string tail = SafeFileSystem.ReadTailText(file, 1024, out bool truncated);

        Assert.False(truncated);
        Assert.Equal("a\nb\n", tail);
    }

    [Fact]
    public void LaunchPlanner_RejectsJavaPathThatIsNotAnExistingJavaExecutable()
    {
        string serverDir = Path.Combine(_root, "srv");
        Directory.CreateDirectory(serverDir);
        File.WriteAllText(Path.Combine(serverDir, "server.jar"), "jar");
        var config = new ServerConfig(
            Domain.ValueObjects.ServerName.Parse("Srv"),
            Domain.ValueObjects.MinecraftVersion.Parse("1.21.4"),
            LoaderKind.Vanilla,
            string.Empty,
            2048,
            null,
            path: serverDir);

        Assert.Throws<InvalidOperationException>(() =>
            new ServerLaunchPlanner().CreatePlan(config, "server.jar", Path.Combine(_root, "missing", "java.exe")));
    }
}
