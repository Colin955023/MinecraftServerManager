using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Mods;
using Xunit;

namespace MinecraftServerManager.UnitTests;

/// <summary>
/// 模組管理外觀服務測試
/// </summary>
public sealed class ModManagerTests : IDisposable
{
    private readonly string _testDir;

    public ModManagerTests()
    {
        _testDir = Path.Combine(Path.GetTempPath(), "msm_test_modmgr_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_testDir);
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
    public async Task ExportModListAsyncTextFormatShouldIncludeModDetails()
    {
        var sampleMods = new List<LocalModInfo>
        {
            new("testmod", "Test Mod", "testmod.jar", "1.0.0", "1.20.1", "fabric", author: "DevTeam", platform: ModPlatform.Local, status: ModStatus.Enabled)
        };

        var fakeScanner = new FakeScanner(sampleMods);
        var fakeInstaller = new FakeInstaller();
        var manager = new ModManager(fakeScanner, fakeInstaller);

        string text = await manager.ExportModListAsync(_testDir, format: "text");

        Assert.Contains("# 模組清單", text, StringComparison.Ordinal);
        Assert.Contains("Test Mod", text, StringComparison.Ordinal);
        Assert.Contains("DevTeam", text, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ExportModListAsyncCsvFormatShouldIncludeHeadersAndValues()
    {
        var sampleMods = new List<LocalModInfo>
        {
            new("my-mod", "My, Mod", "my-mod.jar", "2.1.0", "1.20.1", "forge", author: "AuthorOne", platform: ModPlatform.Local, status: ModStatus.Enabled)
        };

        var fakeScanner = new FakeScanner(sampleMods);
        var fakeInstaller = new FakeInstaller();
        var manager = new ModManager(fakeScanner, fakeInstaller);

        string csv = await manager.ExportModListAsync(_testDir, format: "csv");

        Assert.Contains("狀態,名稱,版本,MC版本,載入器,作者,檔名", csv, StringComparison.Ordinal);
        Assert.Contains("\"My, Mod\"", csv, StringComparison.Ordinal);
        Assert.Contains("\"2.1.0\"", csv, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ExportModListAsyncJsonFormatShouldBeValidJson()
    {
        var sampleMods = new List<LocalModInfo>
        {
            new("mod", "Mod", "mod.jar", "1.0", "1.20.1", "fabric", platform: ModPlatform.Local, status: ModStatus.Enabled)
        };

        var fakeScanner = new FakeScanner(sampleMods);
        var fakeInstaller = new FakeInstaller();
        var manager = new ModManager(fakeScanner, fakeInstaller);

        string json = await manager.ExportModListAsync(_testDir, format: "json");

        Assert.StartsWith("[", json.Trim(), StringComparison.Ordinal);
        Assert.Contains("\"Id\": \"mod\"", json, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ExportModListAsyncHtmlFormatShouldContainTable()
    {
        var sampleMods = new List<LocalModInfo>
        {
            new("mod", "Mod", "mod.jar", "1.0", "1.20.1", "fabric", platform: ModPlatform.Local, status: ModStatus.Enabled)
        };

        var fakeScanner = new FakeScanner(sampleMods);
        var fakeInstaller = new FakeInstaller();
        var manager = new ModManager(fakeScanner, fakeInstaller);

        string html = await manager.ExportModListAsync(_testDir, format: "html");

        Assert.Contains("<table>", html, StringComparison.Ordinal);
        Assert.Contains("<th>名稱</th>", html, StringComparison.Ordinal);
    }

    private sealed class FakeScanner(IReadOnlyList<LocalModInfo> mods) : ILocalModScanner
    {
        public Task<IReadOnlyList<LocalModInfo>> ScanModsAsync(string modsDirectory, CancellationToken cancellationToken = default) =>
            Task.FromResult(mods);

        public Task<LocalModInfo?> ScanSingleModAsync(string filePath, CancellationToken cancellationToken = default) =>
            Task.FromResult(mods.Count > 0 ? mods[0] : null);
    }

    private sealed class FakeInstaller : IModFileInstaller
    {
        public Task<LocalModMutationResult> SetModStateAsync(string modsDirectory, string modId, bool enable, CancellationToken cancellationToken = default) =>
            Task.FromResult(LocalModMutationResult.Success("狀態變更成功"));

        public Task<LocalModMutationResult> DeleteModsAsync(string modsDirectory, IReadOnlyList<string> modIds, CancellationToken cancellationToken = default) =>
            Task.FromResult(LocalModMutationResult.Success("刪除成功"));

        public Task<LocalModMutationResult> ImportLocalModAsync(string modsDirectory, string sourceFilePath, CancellationToken cancellationToken = default) =>
            Task.FromResult(LocalModMutationResult.Success("匯入成功"));

        public Task<ModFileOperationResult> InstallRemoteModAsync(
            string modsDirectory,
            string downloadUrl,
            string fileName,
            string? expectedHash = null,
            string? hashAlgorithm = null,
            IProgress<int>? progress = null,
            CancellationToken cancellationToken = default) =>
            Task.FromResult(ModFileOperationResult.Success(fileName, "安裝成功"));
    }
}
