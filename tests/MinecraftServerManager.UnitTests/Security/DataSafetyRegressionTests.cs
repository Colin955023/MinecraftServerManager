using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Servers;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.UnitTests.Security;

/// <summary>資料遺失與安全性修正的回歸測試</summary>
public sealed class DataSafetyRegressionTests : IDisposable
{
    private readonly TempDirectory _temp = new("msm-safety-");
    private readonly string _root;

    public DataSafetyRegressionTests() => _root = _temp.FullName;

    public void Dispose() => _temp.Dispose();

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
        var servers = await manager.GetAllServersAsync(TestContext.Current.CancellationToken);

        Assert.Empty(servers);
        Assert.Equal("{ broken", File.ReadAllText(registryPath + ".bad"));
    }

    [Theory]
    [InlineData("-Xmx2g", 2048)]
    [InlineData("-Xmx512m", 512)]
    [InlineData("-Xmx1t", 1_048_576)]
    public void ParseMemorySetting_ValidUnits_ReturnsMegabytes(string text, int expectedMb) =>
        Assert.Equal(expectedMb, MemoryHelpers.ParseMemorySetting(text));

    [Theory]
    [InlineData("-Xmx99999999999g")]
    [InlineData("-Xmx9999999999t")]
    public void ParseMemorySetting_OverflowingValue_Rejects(string text) =>
        Assert.Null(MemoryHelpers.ParseMemorySetting(text));

    [Theory]
    [InlineData("-Xmx2G", "-Xmx2G")]
    [InlineData("-Dpath=C:\\Program Files\\x", "\"-Dpath=C:\\Program Files\\x\"")]
    public void FormatBatchArgument_ContainsWhitespace_QuotesArgument(string argument, string expected) =>
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
    public void LaunchPlanner_JavaPathNotJavaExecutable_Rejects()
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

    [Theory]
    [InlineData("server.jar")]
    [InlineData("run.bat")]
    public void LaunchPlanner_CommandExecutionJvmArgs_Rejects(string launchTarget)
    {
        string serverDir = Path.Combine(_root, "srv-jvm");
        Directory.CreateDirectory(serverDir);
        File.WriteAllText(Path.Combine(serverDir, "server.jar"), "jar");
        File.WriteAllText(Path.Combine(serverDir, "run.bat"), "@echo off\r\n");
        var config = new ServerConfig(
            Domain.ValueObjects.ServerName.Parse("SrvJvm"),
            Domain.ValueObjects.MinecraftVersion.Parse("1.20.1"),
            LoaderKind.Forge,
            string.Empty,
            2048,
            null,
            path: serverDir,
            jvmArgs: ["-XX:OnError=calc.exe"]);

        var ex = Assert.Throws<InvalidOperationException>(() => new ServerLaunchPlanner().CreatePlan(config, launchTarget));

        Assert.Contains("-XX:OnError", ex.Message);
        Assert.False(File.Exists(Path.Combine(serverDir, ServerDefaults.UserJvmArgsFileName)));
    }
}
