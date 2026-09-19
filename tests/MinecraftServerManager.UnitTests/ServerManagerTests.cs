using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class ServerManagerTests : IDisposable
{
    private readonly string _testRoot;
    private readonly ServerManager _manager;

    public ServerManagerTests()
    {
        _testRoot = Path.Combine(Path.GetTempPath(), "msm-servermgr-tests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_testRoot);
        _manager = new ServerManager(_testRoot);
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_testRoot))
            {
                Directory.Delete(_testRoot, recursive: true);
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
        }
    }

    [Fact]
    public async Task CreatesServerWithDefaultFilesAndRegistry()
    {
        var plan = ServerCreationPlan.Create(
            name: ServerName.Parse("Survival-1"),
            minecraftVersion: MinecraftVersion.Parse("1.20.4"),
            loaderType: LoaderKind.Vanilla,
            memoryMaxMb: 4096,
            memoryMinMb: 2048);

        var result = await _manager.CreateServerAsync(plan);

        Assert.True(result.Completed);
        Assert.NotNull(result.Config);
        Assert.Equal("Survival-1", result.Config.Name.Value);

        string serverDir = Path.Combine(_testRoot, "Survival-1");
        Assert.True(Directory.Exists(serverDir));
        Assert.True(File.Exists(Path.Combine(serverDir, "eula.txt")));
        Assert.True(File.Exists(Path.Combine(serverDir, "server.properties")));

        var all = await _manager.GetAllServersAsync();
        Assert.Contains(all, s => s.Name.Value == "Survival-1");
    }

    [Fact]
    public async Task RejectsDuplicateServerCreation()
    {
        var plan = ServerCreationPlan.Create(
            name: ServerName.Parse("DuplicateServer"),
            minecraftVersion: MinecraftVersion.Parse("1.20.4"),
            loaderType: LoaderKind.Vanilla,
            memoryMaxMb: 2048);

        var first = await _manager.CreateServerAsync(plan);
        Assert.True(first.Completed);

        var second = await _manager.CreateServerAsync(plan);
        Assert.False(second.Completed);
        Assert.Contains("已存在同名的伺服器", second.Message);
    }

    [Fact]
    public async Task UpdatesServerConfiguration()
    {
        var plan = ServerCreationPlan.Create(
            name: ServerName.Parse("UpdateTarget"),
            minecraftVersion: MinecraftVersion.Parse("1.20.4"),
            loaderType: LoaderKind.Vanilla,
            memoryMaxMb: 2048);

        var creation = await _manager.CreateServerAsync(plan);
        Assert.True(creation.Completed);

        var updatedConfig = new ServerConfig(
            name: creation.Config!.Name,
            minecraftVersion: creation.Config.MinecraftVersion,
            loaderType: creation.Config.LoaderType,
            loaderVersion: "new-loader-ver",
            memoryMaxMb: 8192,
            memoryMinMb: 4096,
            path: creation.Config.Path,
            jvmArgs: ["-XX:+UseG1GC"]);

        var updateResult = await _manager.UpdateServerAsync(updatedConfig);
        Assert.True(updateResult.Success);

        var fetched = await _manager.GetServerAsync("UpdateTarget");
        Assert.NotNull(fetched);
        Assert.Equal(8192, fetched.MemoryMaxMb);
        Assert.Equal(4096, fetched.MemoryMinMb);
        Assert.Contains("-XX:+UseG1GC", fetched.JvmArgs);
    }

    [Fact]
    public async Task DeletesServerSafely()
    {
        var plan = ServerCreationPlan.Create(
            name: ServerName.Parse("ToDelete"),
            minecraftVersion: MinecraftVersion.Parse("1.20.4"),
            loaderType: LoaderKind.Vanilla,
            memoryMaxMb: 2048);

        var creation = await _manager.CreateServerAsync(plan);
        Assert.True(creation.Completed);

        var deleteResult = await _manager.DeleteServerAsync("ToDelete");
        Assert.True(deleteResult.Success);

        var fetched = await _manager.GetServerAsync("ToDelete");
        Assert.Null(fetched);

        string toDeleteDir = Path.Combine(_testRoot, "ToDelete");
        Assert.False(Directory.Exists(toDeleteDir));
    }

    [Fact]
    public async Task ImportsExistingServerDirectory()
    {
        string externalDir = Path.Combine(Path.GetTempPath(), "msm-external-server-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(externalDir);

        File.WriteAllText(Path.Combine(externalDir, "server.jar"), "dummy jar");
        File.WriteAllText(Path.Combine(externalDir, "eula.txt"), "eula=true\n");
        File.WriteAllText(Path.Combine(externalDir, "server.properties"), "server-port=25565\n");

        var importResult = await _manager.ImportServerAsync(externalDir, "ImportedServer", ImportTransferMode.Copy);

        Assert.True(importResult.Completed);
        Assert.NotNull(importResult.Config);
        Assert.Equal("ImportedServer", importResult.Config.Name.Value);

        string importedDir = Path.Combine(_testRoot, "ImportedServer");
        Assert.True(Directory.Exists(importedDir));
        Assert.True(File.Exists(Path.Combine(importedDir, "server.jar")));
    }
}
