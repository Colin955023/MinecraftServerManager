using System.IO.Compression;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests.Servers;

public sealed class ServerScanAndImportTests : IDisposable
{
    private readonly TempDirectory _temp = new("msm-scan-import-");
    private readonly ServerManager _manager;

    public ServerScanAndImportTests() => _manager = TestServerManagers.Create(_temp.FullName);

    public void Dispose() => _temp.Dispose();

    private static string CreateServerFolder(string parent, string name)
    {
        string dir = Path.Combine(parent, name);
        Directory.CreateDirectory(dir);
        File.WriteAllText(Path.Combine(dir, "server.jar"), "jar");
        File.WriteAllText(Path.Combine(dir, "eula.txt"), "eula=true\n");
        File.WriteAllText(Path.Combine(dir, "server.properties"), "server-port=25565\n");
        return dir;
    }

    [Fact]
    public async Task ScanAndRegister_AddsNewCandidatesAndSkipsEverythingElse()
    {
        CreateServerFolder(_temp.FullName, "Fresh");
        Directory.CreateDirectory(Path.Combine(_temp.FullName, "EmptyFolder"));
        CreateServerFolder(_temp.FullName, ".hidden-server");
        CreateServerFolder(_temp.FullName, "con");

        var report = await _manager.ScanAndRegisterAsync(TestContext.Current.CancellationToken);

        Assert.Equal(1, report.NewlyAdded);
        Assert.Equal(2, report.Skipped);
        Assert.Equal(0, report.AlreadyManaged);
        var registered = Assert.Single(await _manager.GetAllServersAsync(TestContext.Current.CancellationToken));
        Assert.Equal("Fresh", registered.Name.Value);
        Assert.Equal(Path.Combine(_temp.FullName, "Fresh"), registered.Path);
    }

    [Fact]
    public async Task ScanAndRegister_SecondRunCountsExistingAsManagedAndAddsNothing()
    {
        CreateServerFolder(_temp.FullName, "Fresh");
        await _manager.ScanAndRegisterAsync(TestContext.Current.CancellationToken);

        var report = await _manager.ScanAndRegisterAsync(TestContext.Current.CancellationToken);

        Assert.Equal(new ServerScanReport(AlreadyManaged: 1, NewlyAdded: 0, Skipped: 0), report);
    }

    [Fact]
    public async Task Import_FromZipWithSingleWrapperFolder_FlattensAndRegisters()
    {
        string staging = Path.Combine(_temp.FullName, "zip-src");
        CreateServerFolder(staging, "wrapper");
        string zipPath = Path.Combine(_temp.FullName, "server.zip");
        ZipFile.CreateFromDirectory(staging, zipPath);

        var result = await _manager.ImportServerAsync(
            zipPath,
            "FromZip",
            cancellationToken: TestContext.Current.CancellationToken);

        Assert.True(result.Completed);
        Assert.True(File.Exists(Path.Combine(_temp.FullName, "FromZip", "server.jar")));
        Assert.False(Directory.Exists(Path.Combine(_temp.FullName, "FromZip", "wrapper")));
        Assert.NotNull(await _manager.GetServerAsync("FromZip", TestContext.Current.CancellationToken));
        Assert.True(File.Exists(zipPath));
    }

    [Fact]
    public async Task Import_RejectsDirectoryWithoutServerCoreAndLeavesNoTarget()
    {
        string source = Path.Combine(_temp.FullName, "not-a-server");
        Directory.CreateDirectory(source);
        File.WriteAllText(Path.Combine(source, "readme.txt"), "x");

        var result = await _manager.ImportServerAsync(source, "Broken", cancellationToken: TestContext.Current.CancellationToken);

        Assert.False(result.Completed);
        Assert.False(Directory.Exists(Path.Combine(_temp.FullName, "Broken")));
        Assert.Null(await _manager.GetServerAsync("Broken", TestContext.Current.CancellationToken));
        Assert.Empty(Directory.EnumerateDirectories(_temp.FullName, ".import-staging-*"));
    }

    [Fact]
    public async Task Import_RejectsInvalidNameAndDuplicateName()
    {
        string source = CreateServerFolder(Path.Combine(_temp.FullName, "src"), "one");

        var invalid = await _manager.ImportServerAsync(source, "bad/name", cancellationToken: TestContext.Current.CancellationToken);
        Assert.False(invalid.Completed);

        var first = await _manager.ImportServerAsync(source, "Dup", cancellationToken: TestContext.Current.CancellationToken);
        Assert.True(first.Completed);
        var second = await _manager.ImportServerAsync(source, "Dup", cancellationToken: TestContext.Current.CancellationToken);
        Assert.False(second.Completed);
        Assert.Contains("Dup", second.Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Import_RejectsExistingNonEmptyUnregisteredTargetAndKeepsItsContent()
    {
        string source = CreateServerFolder(Path.Combine(_temp.FullName, "src"), "one");
        string existing = Path.Combine(_temp.FullName, "Occupied");
        Directory.CreateDirectory(existing);
        string keepsake = Path.Combine(existing, "world.dat");
        File.WriteAllText(keepsake, "precious");

        var result = await _manager.ImportServerAsync(source, "Occupied", cancellationToken: TestContext.Current.CancellationToken);

        Assert.False(result.Completed);
        Assert.Equal("precious", File.ReadAllText(keepsake));
        Assert.False(File.Exists(Path.Combine(existing, "server.jar")));
        Assert.Null(await _manager.GetServerAsync("Occupied", TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task Import_IntoExistingEmptyTargetSucceeds()
    {
        string source = CreateServerFolder(Path.Combine(_temp.FullName, "src"), "one");
        Directory.CreateDirectory(Path.Combine(_temp.FullName, "Vacant"));

        var result = await _manager.ImportServerAsync(source, "Vacant", cancellationToken: TestContext.Current.CancellationToken);

        Assert.True(result.Completed);
        Assert.True(File.Exists(Path.Combine(_temp.FullName, "Vacant", "server.jar")));
    }

    [Fact]
    public async Task Import_WritesStartScriptAndEula()
    {
        string source = CreateServerFolder(Path.Combine(_temp.FullName, "src"), "one");
        File.Delete(Path.Combine(source, "eula.txt"));

        var result = await _manager.ImportServerAsync(source, "Scripted", cancellationToken: TestContext.Current.CancellationToken);

        Assert.True(result.Completed);
        string target = Path.Combine(_temp.FullName, "Scripted");
        Assert.Contains("eula=true", File.ReadAllText(Path.Combine(target, "eula.txt")), StringComparison.Ordinal);
        Assert.True(File.Exists(Path.Combine(target, ServerDefaults.StartServerBatFileName)));
    }
}
