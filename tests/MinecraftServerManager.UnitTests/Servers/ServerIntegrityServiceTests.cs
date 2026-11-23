using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.UnitTests.Servers;

public sealed class ServerIntegrityServiceTests : IDisposable
{
    private readonly TempDirectory _testDirTemp = new("msm-integrity-tests-");
    private readonly string _testDir;
    private readonly ServerIntegrityService _integrityService;

    public ServerIntegrityServiceTests()
    {
        _testDir = _testDirTemp.FullName;
        _integrityService = new ServerIntegrityService();
    }

    public void Dispose() => _testDirTemp.Dispose();

    [Fact]
    public async Task CheckImportantFiles_NonExistentDirectory_ReturnsMissing()
    {
        string nonExistent = Path.Combine(_testDir, "DoesNotExist");
        var result = await _integrityService.CheckImportantFilesAsync(nonExistent, LoaderKind.Vanilla, TestContext.Current.CancellationToken);

        Assert.True(result.HasMissing);
        Assert.Contains(result.MissingFiles, static m => m.Contains("不存在"));
    }

    [Fact]
    public async Task CheckImportantFiles_VanillaServer_DetectsMissingAndValid()
    {
        // 缺少 server.jar
        var missingResult = await _integrityService.CheckImportantFilesAsync(_testDir, LoaderKind.Vanilla, TestContext.Current.CancellationToken);
        Assert.True(missingResult.HasMissing);
        Assert.Contains("server.jar", missingResult.MissingFiles);

        // 建立 server.jar
        File.WriteAllText(Path.Combine(_testDir, "server.jar"), "dummy");
        var validResult = await _integrityService.CheckImportantFilesAsync(_testDir, LoaderKind.Vanilla, TestContext.Current.CancellationToken);
        Assert.False(validResult.HasMissing);
        Assert.Empty(validResult.MissingFiles);
    }

    [Fact]
    public async Task CheckImportantFiles_PaperServer_DetectsPaperJar()
    {
        // 缺少 paper.jar
        var missingResult = await _integrityService.CheckImportantFilesAsync(_testDir, LoaderKind.Paper, TestContext.Current.CancellationToken);
        Assert.True(missingResult.HasMissing);

        // 建立 paper-1.20.4-496.jar
        File.WriteAllText(Path.Combine(_testDir, "paper-1.20.4-496.jar"), "dummy paper");
        var validResult = await _integrityService.CheckImportantFilesAsync(_testDir, LoaderKind.Paper, TestContext.Current.CancellationToken);
        Assert.False(validResult.HasMissing);
    }

    [Fact]
    public async Task CheckImportantFiles_FabricServer_DetectsLaunchJar()
    {
        // 缺少檔案
        var missingResult = await _integrityService.CheckImportantFilesAsync(_testDir, LoaderKind.Fabric, TestContext.Current.CancellationToken);
        Assert.True(missingResult.HasMissing);
        Assert.Contains("fabric-server-launch.jar", missingResult.MissingFiles);

        // 同時具備啟動 JAR 與原版伺服器 JAR
        File.WriteAllText(Path.Combine(_testDir, "fabric-server-launch.jar"), "dummy fabric");
        File.WriteAllText(Path.Combine(_testDir, "server.jar"), "dummy server");
        var validResult = await _integrityService.CheckImportantFilesAsync(_testDir, LoaderKind.Fabric, TestContext.Current.CancellationToken);
        Assert.False(validResult.HasMissing);
        Assert.Empty(validResult.MissingFiles);
    }

    [Fact]
    public async Task CheckImportantFiles_ForgeServer_DetectsLegacyOrModernFiles()
    {
        // 空目錄回傳缺少
        var missingResult = await _integrityService.CheckImportantFilesAsync(_testDir, LoaderKind.Forge, TestContext.Current.CancellationToken);
        Assert.True(missingResult.HasMissing);

        // 安裝器不算伺服器 jar
        File.WriteAllText(Path.Combine(_testDir, "forge-1.12.2-installer.jar"), "dummy installer");
        Assert.True((await _integrityService.CheckImportantFilesAsync(_testDir, LoaderKind.Forge, TestContext.Current.CancellationToken)).HasMissing);

        // 測試舊版 Forge 檔案 (forge*.jar)
        File.WriteAllText(Path.Combine(_testDir, "forge-1.12.2.jar"), "dummy forge jar");
        var legacyResult = await _integrityService.CheckImportantFilesAsync(_testDir, LoaderKind.Forge, TestContext.Current.CancellationToken);
        Assert.False(legacyResult.HasMissing);

        // 移除舊版檔案，建立現代版 Forge 結構 (run.bat + forge args.txt)
        File.Delete(Path.Combine(_testDir, "forge-1.12.2.jar"));
        File.WriteAllText(Path.Combine(_testDir, "run.bat"), "dummy script");
        string forgeLibDir = Path.Combine(_testDir, "libraries", "net", "minecraftforge", "forge");
        Directory.CreateDirectory(forgeLibDir);
        File.WriteAllText(Path.Combine(forgeLibDir, "win_args.txt"), "dummy args");

        var modernResult = await _integrityService.CheckImportantFilesAsync(_testDir, LoaderKind.Forge, TestContext.Current.CancellationToken);
        Assert.False(modernResult.HasMissing);
        Assert.Empty(modernResult.MissingFiles);
    }

    [Fact]
    public async Task CheckImportantFiles_QuiltServer_RequiresLaunchJarAndServerJar()
    {
        // 缺少檔案
        var missingResult = await _integrityService.CheckImportantFilesAsync(_testDir, LoaderKind.Quilt, TestContext.Current.CancellationToken);
        Assert.True(missingResult.HasMissing);
        Assert.Contains("quilt-server-launch.jar", missingResult.MissingFiles);

        // 與 Fabric 相同，僅有啟動 JAR 仍缺原版 server.jar
        File.WriteAllText(Path.Combine(_testDir, "quilt-server-launch.jar"), "dummy quilt");
        var partialResult = await _integrityService.CheckImportantFilesAsync(_testDir, LoaderKind.Quilt, TestContext.Current.CancellationToken);
        Assert.Equal(["server.jar"], partialResult.MissingFiles);

        File.WriteAllText(Path.Combine(_testDir, "server.jar"), "dummy server");
        var validResult = await _integrityService.CheckImportantFilesAsync(_testDir, LoaderKind.Quilt, TestContext.Current.CancellationToken);
        Assert.False(validResult.HasMissing);
        Assert.Empty(validResult.MissingFiles);
    }

    [Fact]
    public async Task CheckImportantFiles_NeoForgeServer_DetectsScriptAndArgs()
    {
        // 空目錄回傳缺少腳本與參數檔
        var missingResult = await _integrityService.CheckImportantFilesAsync(_testDir, LoaderKind.NeoForge, TestContext.Current.CancellationToken);
        Assert.True(missingResult.HasMissing);
        Assert.Contains("start_server.bat / run.bat", missingResult.MissingFiles);
        Assert.Contains("win_args.txt", missingResult.MissingFiles);

        // 建立 start_server.bat 與 NeoForge args.txt
        File.WriteAllText(Path.Combine(_testDir, "start_server.bat"), "dummy script");
        string neoForgeLibDir = Path.Combine(_testDir, "libraries", "net", "neoforged", "neoforge");
        Directory.CreateDirectory(neoForgeLibDir);
        File.WriteAllText(Path.Combine(neoForgeLibDir, "win_args.txt"), "dummy neoforge args");

        var validResult = await _integrityService.CheckImportantFilesAsync(_testDir, LoaderKind.NeoForge, TestContext.Current.CancellationToken);
        Assert.False(validResult.HasMissing);
        Assert.Empty(validResult.MissingFiles);
    }

    [Fact]
    public async Task CheckImportantFiles_UnknownLoader_DetectsAnyJarOrScript()
    {
        // 空目錄回傳缺少 server.jar
        var missingResult = await _integrityService.CheckImportantFilesAsync(_testDir, (LoaderKind)999, TestContext.Current.CancellationToken);
        Assert.True(missingResult.HasMissing);
        Assert.Contains("server.jar", missingResult.MissingFiles);

        // 建立任一 JAR 檔
        File.WriteAllText(Path.Combine(_testDir, "custom-core.jar"), "dummy jar");
        var validResult = await _integrityService.CheckImportantFilesAsync(_testDir, (LoaderKind)999, TestContext.Current.CancellationToken);
        Assert.False(validResult.HasMissing);
        Assert.Empty(validResult.MissingFiles);
    }
}
