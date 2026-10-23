using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests.Servers;

public sealed class ServerIntegrityServiceTests : IDisposable
{
    private readonly string _testDir;
    private readonly ServerIntegrityService _integrityService;

    public ServerIntegrityServiceTests()
    {
        _testDir = Path.Combine(Path.GetTempPath(), "msm-integrity-tests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_testDir);
        _integrityService = new ServerIntegrityService();
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_testDir))
            {
                Directory.Delete(_testDir, recursive: true);
            }
        }
        catch
        {
        }
    }

    [Fact]
    public void CheckImportantFiles_NonExistentDirectory_ReturnsMissing()
    {
        string nonExistent = Path.Combine(_testDir, "DoesNotExist");
        var result = _integrityService.CheckImportantFiles(nonExistent, LoaderKind.Vanilla);

        Assert.True(result.HasMissing);
        Assert.Contains(result.MissingFiles, static m => m.Contains("不存在"));
    }

    [Fact]
    public void CheckImportantFiles_VanillaServer_DetectsMissingAndValid()
    {
        // 缺少 server.jar
        var missingResult = _integrityService.CheckImportantFiles(_testDir, LoaderKind.Vanilla);
        Assert.True(missingResult.HasMissing);
        Assert.Contains("server.jar", missingResult.MissingFiles);

        // 建立 server.jar
        File.WriteAllText(Path.Combine(_testDir, "server.jar"), "dummy");
        var validResult = _integrityService.CheckImportantFiles(_testDir, LoaderKind.Vanilla);
        Assert.False(validResult.HasMissing);
        Assert.Empty(validResult.MissingFiles);
    }

    [Fact]
    public void CheckImportantFiles_PaperServer_DetectsPaperJar()
    {
        // 缺少 paper.jar
        var missingResult = _integrityService.CheckImportantFiles(_testDir, LoaderKind.Paper);
        Assert.True(missingResult.HasMissing);

        // 建立 paper-1.20.4-496.jar
        File.WriteAllText(Path.Combine(_testDir, "paper-1.20.4-496.jar"), "dummy paper");
        var validResult = _integrityService.CheckImportantFiles(_testDir, LoaderKind.Paper);
        Assert.False(validResult.HasMissing);
    }

    [Fact]
    public void CheckImportantFiles_FabricServer_DetectsLaunchJar()
    {
        // 缺少檔案
        var missingResult = _integrityService.CheckImportantFiles(_testDir, LoaderKind.Fabric);
        Assert.True(missingResult.HasMissing);
        Assert.Contains("fabric-server-launch.jar", missingResult.MissingFiles);

        // 同時具備啟動 JAR 與原版伺服器 JAR
        File.WriteAllText(Path.Combine(_testDir, "fabric-server-launch.jar"), "dummy fabric");
        File.WriteAllText(Path.Combine(_testDir, "server.jar"), "dummy server");
        var validResult = _integrityService.CheckImportantFiles(_testDir, LoaderKind.Fabric);
        Assert.False(validResult.HasMissing);
        Assert.Empty(validResult.MissingFiles);
    }

    [Fact]
    public void CheckImportantFiles_ForgeServer_DetectsLegacyOrModernFiles()
    {
        // 空目錄回傳缺少
        var missingResult = _integrityService.CheckImportantFiles(_testDir, LoaderKind.Forge);
        Assert.True(missingResult.HasMissing);

        // 測試舊版 Forge 檔案 (forge*.jar)
        File.WriteAllText(Path.Combine(_testDir, "forge-1.12.2.jar"), "dummy forge jar");
        var legacyResult = _integrityService.CheckImportantFiles(_testDir, LoaderKind.Forge);
        Assert.False(legacyResult.HasMissing);

        // 移除舊版檔案，建立現代版 Forge 結構 (run.bat + forge args.txt)
        File.Delete(Path.Combine(_testDir, "forge-1.12.2.jar"));
        File.WriteAllText(Path.Combine(_testDir, "run.bat"), "dummy script");
        string forgeLibDir = Path.Combine(_testDir, "libraries", "net", "minecraftforge", "forge");
        Directory.CreateDirectory(forgeLibDir);
        File.WriteAllText(Path.Combine(forgeLibDir, "win_args.txt"), "dummy args");

        var modernResult = _integrityService.CheckImportantFiles(_testDir, LoaderKind.Forge);
        Assert.False(modernResult.HasMissing);
        Assert.Empty(modernResult.MissingFiles);
    }
}
