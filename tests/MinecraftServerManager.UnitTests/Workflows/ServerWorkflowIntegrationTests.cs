using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Mods;
using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.UnitTests.Workflows;

public sealed class ServerWorkflowIntegrationTests : IDisposable
{
    private readonly TempDirectory _testRootTemp = new("msm_integration_");
    private readonly string _testRoot;
    private readonly string _serversRoot;

    public ServerWorkflowIntegrationTests()
    {
        _testRoot = _testRootTemp.FullName;
        _serversRoot = Path.Combine(_testRoot, "servers");
        SafeFileSystem.ResolveStableDirectory(_serversRoot, create: true);
    }

    public void Dispose() => _testRootTemp.Dispose();

    [Fact]
    public async Task ServerLifecycle_CreateUpdateDelete_Succeeds()
    {
        var inspector = new ServerInspector();
        var planner = new ServerLaunchPlanner();
        var manager = TestServerManagers.Create(_serversRoot, inspector);

        var plan = ServerCreationPlan.Create(
            name: ServerName.Parse("TestServer"),
            minecraftVersion: MinecraftVersion.Parse("1.20.4"),
            loaderType: LoaderKind.Vanilla,
            loaderVersion: string.Empty,
            memoryMaxMb: 4096,
            memoryMinMb: 2048);

        var createResult = await manager.CreateServerAsync(plan, cancellationToken: TestContext.Current.CancellationToken);
        Assert.True(createResult.Completed);
        Assert.NotNull(createResult.Config);

        string serverDir = Path.Combine(_serversRoot, "TestServer");
        Assert.True(Directory.Exists(serverDir));
        Assert.True(File.Exists(Path.Combine(serverDir, "eula.txt")));
        Assert.True(File.Exists(Path.Combine(serverDir, "server.properties")));

        File.WriteAllText(Path.Combine(serverDir, "server.jar"), "dummy jar");

        var inspection = await inspector.InspectAsync(serverDir, TestContext.Current.CancellationToken);
        Assert.True(inspection.IsCandidate);
        Assert.Equal(LoaderKind.Vanilla, inspection.LoaderType);

        string javaExe = Path.Combine(serverDir, "jre", "bin", "java.exe");
        Directory.CreateDirectory(Path.GetDirectoryName(javaExe)!);
        File.WriteAllText(javaExe, "stub");
        var launchPlan = planner.CreatePlan(createResult.Config, inspection.LaunchTarget.Value, javaExe);
        Assert.Equal(javaExe, launchPlan.JavaExecutable);
        Assert.False(launchPlan.IsScript);
        Assert.Contains("-Xms2048M", launchPlan.Arguments);
        Assert.Contains("-Xmx4096M", launchPlan.Arguments);
        Assert.Contains("server.jar", launchPlan.Arguments);

        var deleteResult = await manager.DeleteServerAsync("TestServer", TestContext.Current.CancellationToken);
        Assert.True(deleteResult.Success);
        Assert.False(Directory.Exists(serverDir));
    }

    [Fact]
    public async Task ServerBackup_CreateAndRestore_Succeeds()
    {
        string serverDir = Path.Combine(_serversRoot, "BackupServer");
        SafeFileSystem.ResolveStableDirectory(serverDir, create: true);

        string dataFile = Path.Combine(serverDir, "world.txt");
        File.WriteAllText(dataFile, "original world data");

        string externalBackupsDir = Path.Combine(_testRoot, "ExternalBackups");
        SafeFileSystem.ResolveStableDirectory(externalBackupsDir, create: true);
        var backupService = new ServerBackupService(_serversRoot, static () => 2, TimeProvider.System);

        var backup1 = await backupService.CreateBackupAsync(
            "BackupServer",
            destinationPath: externalBackupsDir,
            comment: "第一個測試備份",
            cancellationToken: TestContext.Current.CancellationToken);
        Assert.NotNull(backup1);
        Assert.True(File.Exists(backup1.FullPath));

        File.WriteAllText(dataFile, "corrupted world data");
        string extraFile = Path.Combine(serverDir, "temp_corrupt.txt");
        File.WriteAllText(extraFile, "unexpected content");

        bool restoreSuccess = await backupService.RestoreBackupAsync(
            "BackupServer",
            backup1.FileName,
            externalBackupsDir,
            cancellationToken: TestContext.Current.CancellationToken);
        Assert.True(restoreSuccess);

        Assert.Equal("original world data", File.ReadAllText(dataFile));
        Assert.False(File.Exists(extraFile));

        var backup2 = await backupService.CreateBackupAsync(
            "BackupServer",
            destinationPath: externalBackupsDir,
            cancellationToken: TestContext.Current.CancellationToken);
        var backup3 = await backupService.CreateBackupAsync(
            "BackupServer",
            destinationPath: externalBackupsDir,
            cancellationToken: TestContext.Current.CancellationToken);

        var list = await backupService.ListBackupsAsync("BackupServer", externalBackupsDir, TestContext.Current.CancellationToken);
        Assert.Equal(2, list.Count);
        Assert.Contains(list, b => b.FileName == backup3.FileName);
        Assert.Contains(list, b => b.FileName == backup2.FileName);
        Assert.DoesNotContain(list, b => b.FileName == backup1.FileName);
    }

    [Fact]
    public async Task ServerImport_DirectoryAndZip_Succeeds()
    {
        var inspector = new ServerInspector();
        var manager = TestServerManagers.Create(_serversRoot, inspector);

        string externalDir = Path.Combine(_testRoot, "ExternalServerDir");
        Directory.CreateDirectory(externalDir);
        File.WriteAllText(Path.Combine(externalDir, "server.jar"), "jar");
        File.WriteAllText(Path.Combine(externalDir, "server.properties"), "motd=Imported Folder\nserver-port=25565");
        File.WriteAllText(Path.Combine(externalDir, "version.json"), "{\"id\":\"1.20.1\"}");

        var importDirResult = await manager.ImportServerAsync(
            externalDir,
            "ImportedFolderServer",
            ImportTransferMode.Copy,
            cancellationToken: TestContext.Current.CancellationToken);
        Assert.True(importDirResult.Completed);
        Assert.True(Directory.Exists(Path.Combine(_serversRoot, "ImportedFolderServer")));

        string zipSource = Path.Combine(_testRoot, "OldServer.zip");
        TestZip.Create(
            zipSource,
            ("server.jar", "zip jar content"),
            ("server.properties", "motd=Imported Zip\nserver-port=25566"),
            ("version.json", "{\"id\":\"1.20.1\"}"));

        var importZipResult = await manager.ImportServerAsync(zipSource, "ImportedZipServer", cancellationToken: TestContext.Current.CancellationToken);
        Assert.True(importZipResult.Completed);
        Assert.True(Directory.Exists(Path.Combine(_serversRoot, "ImportedZipServer")));
        Assert.True(File.Exists(Path.Combine(_serversRoot, "ImportedZipServer", "server.jar")));
    }

    [Fact]
    public async Task ModManagement_ImportToggleDelete_Succeeds()
    {
        string serverDir = Path.Combine(_serversRoot, "ModServer");
        string modsDir = Path.Combine(serverDir, "mods");
        SafeFileSystem.ResolveStableDirectory(modsDir, create: true);

        string dummyModSource = Path.Combine(_testRoot, "testmod-1.0.0.jar");
        TestZip.Create(dummyModSource, ("fabric.mod.json", "{\"id\":\"testmod\",\"name\":\"Test Mod\",\"version\":\"1.0.0\"}"));
        var scanner = new LocalModScanner();
        var installer = new ModFileInstaller(new StubHttpPort
        {
            DownloadHandler = request =>
            {
                File.WriteAllText(request.TargetPath, "dummy download");
                return Task.FromResult(new HttpResult(true, null, 14));
            },
        });
        var modManager = new ModManager(scanner, installer);

        var importResult = await modManager.ImportModAsync(serverDir, dummyModSource, TestContext.Current.CancellationToken);
        Assert.True(importResult.Completed);
        Assert.True(File.Exists(Path.Combine(modsDir, "testmod-1.0.0.jar")));

        var mods = await modManager.GetModsAsync(serverDir, cancellationToken: TestContext.Current.CancellationToken);
        var mod = Assert.Single(mods);
        Assert.Equal("testmod", mod.Id);
        Assert.Equal("Test Mod", mod.Name);

        var toggleResult = await modManager.SetModStateAsync(serverDir, "testmod", enable: false, cancellationToken: TestContext.Current.CancellationToken);
        Assert.True(toggleResult.Completed);
        Assert.True(File.Exists(Path.Combine(modsDir, "testmod-1.0.0.jar.disabled")));

        var exporter = new ModListExporter();
        var exportRows = new List<ModListExportRow>
        {
            new(mod.Id, mod.Name, mod.Version, mod.FileName, "1 KiB", mod.Author, mod.LoaderType, mod.MinecraftVersion, "2026-01-01", mod.Description, false)
        };
        string txtExportPath = Path.Combine(serverDir, "mods.txt");
        string jsonExportPath = Path.Combine(serverDir, "mods.json");
        await exporter.ExportAsync(exportRows, ModListExportFormat.Text, txtExportPath, TestContext.Current.CancellationToken);
        await exporter.ExportAsync(exportRows, ModListExportFormat.Json, jsonExportPath, TestContext.Current.CancellationToken);
        string txtContent = await File.ReadAllTextAsync(txtExportPath, TestContext.Current.CancellationToken);
        Assert.Contains("Test Mod", txtContent, StringComparison.Ordinal);
        Assert.Contains("[停用]", txtContent, StringComparison.Ordinal);
        Assert.DoesNotContain("❌", txtContent, StringComparison.Ordinal);
        Assert.DoesNotContain("✅", txtContent, StringComparison.Ordinal);
        Assert.Contains("Test Mod", await File.ReadAllTextAsync(jsonExportPath, TestContext.Current.CancellationToken));

        var deleteResult = await modManager.DeleteModsAsync(serverDir, ["testmod"], TestContext.Current.CancellationToken);
        Assert.True(deleteResult.Completed);
        Assert.False(File.Exists(Path.Combine(modsDir, "testmod-1.0.0.jar.disabled")));
    }

    [Fact]
    public async Task ImportServer_MaliciousZipSlipArchive_IsSafelyRejected()
    {
        var inspector = new ServerInspector();
        var manager = TestServerManagers.Create(_serversRoot, inspector);

        string maliciousZip = Path.Combine(_testRoot, "malicious_zipslip.zip");
        TestZip.Create(maliciousZip, ("server.properties", "motd=Safe motd"), ("../../../evil_escape.txt", "pwned"));

        var result = await manager.ImportServerAsync(maliciousZip, "MaliciousServer", cancellationToken: TestContext.Current.CancellationToken);
        Assert.False(result.Completed);
        Assert.False(File.Exists(Path.Combine(_testRoot, "evil_escape.txt")));
        Assert.False(Directory.Exists(Path.Combine(_serversRoot, "MaliciousServer")));
    }
}
