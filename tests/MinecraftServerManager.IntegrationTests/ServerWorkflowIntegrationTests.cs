using System.IO.Compression;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Mods;
using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

namespace MinecraftServerManager.IntegrationTests;

/// <summary>
/// 伺服器端對端真實工作流程整合測試
/// </summary>
public sealed class ServerWorkflowIntegrationTests : IDisposable
{
    private readonly string _testRoot;
    private readonly string _serversRoot;

    public ServerWorkflowIntegrationTests()
    {
        _testRoot = Path.Combine(Path.GetTempPath(), "msm_integration_" + Guid.NewGuid().ToString("N"));
        _serversRoot = Path.Combine(_testRoot, "servers");
        SafeFileSystem.ResolveStableDirectory(_serversRoot, create: true);
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
    public async Task ServerLifecycleWorkflowSucceeds()
    {
        var inspector = new ServerInspector();
        var planner = new ServerLaunchPlanner();
        var manager = new ServerManager(_serversRoot, inspector);

        // 1. 建立伺服器
        var plan = ServerCreationPlan.Create(
            name: ServerName.Parse("TestServer"),
            minecraftVersion: MinecraftVersion.Parse("1.20.4"),
            loaderType: LoaderKind.Vanilla,
            loaderVersion: string.Empty,
            memoryMaxMb: 4096,
            memoryMinMb: 2048);

        var createResult = await manager.CreateServerAsync(plan);
        Assert.True(createResult.Completed);
        Assert.NotNull(createResult.Config);

        string serverDir = Path.Combine(_serversRoot, "TestServer");
        Assert.True(Directory.Exists(serverDir));
        Assert.True(File.Exists(Path.Combine(serverDir, "eula.txt")));
        Assert.True(File.Exists(Path.Combine(serverDir, "server.properties")));

        // 建立測試用 server.jar
        File.WriteAllText(Path.Combine(serverDir, "server.jar"), "dummy jar");

        // 2. 檢測伺服器
        var inspection = await inspector.InspectAsync(serverDir);
        Assert.True(inspection.IsCandidate);
        Assert.Equal("vanilla", inspection.LoaderType, ignoreCase: true);

        // 3. 啟動規劃
        var launchPlan = planner.CreatePlan(createResult.Config, inspection, "C:\\Java\\java.exe");
        Assert.Equal("C:\\Java\\java.exe", launchPlan.JavaExecutable);
        Assert.False(launchPlan.IsScript);
        Assert.Contains("-Xms2048M", launchPlan.Arguments);
        Assert.Contains("-Xmx4096M", launchPlan.Arguments);
        Assert.Contains("server.jar", launchPlan.Arguments);

        // 4. 刪除伺服器
        var deleteResult = await manager.DeleteServerAsync("TestServer");
        Assert.True(deleteResult.Success);
        Assert.False(Directory.Exists(serverDir));
    }

    [Fact]
    public async Task ServerBackupAndTransactionalRestoreWorkflowSucceeds()
    {
        string serverDir = Path.Combine(_serversRoot, "BackupServer");
        SafeFileSystem.ResolveStableDirectory(serverDir, create: true);

        // 建立測試檔案
        string dataFile = Path.Combine(serverDir, "world.txt");
        File.WriteAllText(dataFile, "original world data");

        var backupService = new ServerBackupService(_serversRoot, maxRetentionCount: 2);

        // 1. 建立備份
        var backup1 = await backupService.CreateBackupAsync("BackupServer", "第一個測試備份");
        Assert.NotNull(backup1);
        Assert.True(File.Exists(backup1.FullPath));

        // 2. 竄改伺服器內容
        File.WriteAllText(dataFile, "corrupted world data");
        string extraFile = Path.Combine(serverDir, "temp_corrupt.txt");
        File.WriteAllText(extraFile, "unexpected content");

        // 3. 交易式安全還原
        bool restoreSuccess = await backupService.RestoreBackupAsync("BackupServer", backup1.FileName);
        Assert.True(restoreSuccess);

        // 驗證原本資料已完全復原
        Assert.Equal("original world data", File.ReadAllText(dataFile));
        Assert.False(File.Exists(extraFile));

        // 4. 驗證 Retention 清理政策 (maxRetentionCount = 2)
        var backup2 = await backupService.CreateBackupAsync("BackupServer");
        var backup3 = await backupService.CreateBackupAsync("BackupServer");

        var list = await backupService.ListBackupsAsync("BackupServer");
        Assert.Equal(2, list.Count);
        Assert.Contains(list, b => b.FileName == backup3.FileName);
        Assert.Contains(list, b => b.FileName == backup2.FileName);
        Assert.DoesNotContain(list, b => b.FileName == backup1.FileName);
    }

    [Fact]
    public async Task ServerImportDirectoryAndZipWorkflowSucceeds()
    {
        var manager = new ServerManager(_serversRoot);

        // 1. 測試資料夾匯入
        string externalDir = Path.Combine(_testRoot, "ExternalServerDir");
        Directory.CreateDirectory(externalDir);
        File.WriteAllText(Path.Combine(externalDir, "server.jar"), "jar");
        File.WriteAllText(Path.Combine(externalDir, "server.properties"), "motd=Imported Folder\nserver-port=25565");

        var importDirResult = await manager.ImportServerAsync(externalDir, "ImportedFolderServer", ImportTransferMode.Copy);
        Assert.True(importDirResult.Completed);
        Assert.True(Directory.Exists(Path.Combine(_serversRoot, "ImportedFolderServer")));

        // 2. 測試 ZIP 壓縮檔匯入
        string zipSource = Path.Combine(_testRoot, "OldServer.zip");
        using (var zipStream = new FileStream(zipSource, FileMode.Create))
        using (var archive = new ZipArchive(zipStream, ZipArchiveMode.Create))
        {
            var jarEntry = archive.CreateEntry("server.jar");
            using (var writer = new StreamWriter(jarEntry.Open()))
            {
                writer.Write("zip jar content");
            }

            var propEntry = archive.CreateEntry("server.properties");
            using (var writer = new StreamWriter(propEntry.Open()))
            {
                writer.Write("motd=Imported Zip\nserver-port=25566");
            }
        }

        var importZipResult = await manager.ImportServerAsync(zipSource, "ImportedZipServer");
        Assert.True(importZipResult.Completed);
        Assert.True(Directory.Exists(Path.Combine(_serversRoot, "ImportedZipServer")));
        Assert.True(File.Exists(Path.Combine(_serversRoot, "ImportedZipServer", "server.jar")));
    }

    [Fact]
    public async Task ModManagementWorkflowSucceeds()
    {
        string serverDir = Path.Combine(_serversRoot, "ModServer");
        string modsDir = Path.Combine(serverDir, "mods");
        SafeFileSystem.ResolveStableDirectory(modsDir, create: true);

        // 建立測試 JAR 模組
        string dummyModSource = Path.Combine(_testRoot, "testmod-1.0.0.jar");
        using (var zipStream = new FileStream(dummyModSource, FileMode.Create))
        using (var archive = new ZipArchive(zipStream, ZipArchiveMode.Create))
        {
            var entry = archive.CreateEntry("fabric.mod.json");
            using var writer = new StreamWriter(entry.Open());
            writer.Write("{\"id\":\"testmod\",\"name\":\"Test Mod\",\"version\":\"1.0.0\"}");
        }

        var persistence = new ModIndexPersistence(_serversRoot);
        var scanner = new LocalModScanner(persistence);
        var installer = new ModFileInstaller(new DummyHttpPort());
        var modManager = new ModManager(scanner, installer);

        // 1. 匯入模組
        var importResult = await modManager.ImportModAsync(serverDir, dummyModSource);
        Assert.True(importResult.Completed);
        Assert.True(File.Exists(Path.Combine(modsDir, "testmod-1.0.0.jar")));

        // 2. 掃描模組
        var mods = await modManager.GetModsAsync(serverDir);
        Assert.Single(mods);
        Assert.Equal("testmod", mods[0].Id);
        Assert.Equal("Test Mod", mods[0].Name);

        // 3. 切換停用狀態
        var toggleResult = await modManager.SetModStateAsync(serverDir, "testmod", enable: false);
        Assert.True(toggleResult.Completed);
        Assert.True(File.Exists(Path.Combine(modsDir, "testmod-1.0.0.jar.disabled")));

        // 4. 匯出模組清單
        string txtExport = await modManager.ExportModListAsync(serverDir, "text");
        Assert.Contains("Test Mod", txtExport);
        string jsonExport = await modManager.ExportModListAsync(serverDir, "json");
        Assert.Contains("Test Mod", jsonExport);

        // 5. 刪除模組
        var deleteResult = await modManager.DeleteModsAsync(serverDir, ["testmod"]);
        Assert.True(deleteResult.Completed);
        Assert.False(File.Exists(Path.Combine(modsDir, "testmod-1.0.0.jar.disabled")));
    }

    private sealed class DummyHttpPort : IHttpPort
    {
        public Task<HttpResult> DownloadAsync(
            Uri uri,
            string targetPath,
            IProgress<HttpProgress>? progress = null,
            string? expectedHash = null,
            string expectedHashAlgorithm = "sha256",
            CancellationToken cancellationToken = default)
        {
            File.WriteAllText(targetPath, "dummy download");
            return Task.FromResult(new HttpResult(true, null, 14));
        }

        public Task<HttpJsonResponse<T>> GetJsonAsync<T>(Uri uri, CancellationToken cancellationToken = default) => Task.FromResult(new HttpJsonResponse<T>(404, default, "Not Found"));

        public Task<string?> GetTextAsync(Uri uri, CancellationToken cancellationToken = default) => Task.FromResult<string?>(null);

        public Task<string?> PostJsonAsync(Uri uri, string jsonPayload, CancellationToken cancellationToken = default) => Task.FromResult<string?>(null);
    }
}
