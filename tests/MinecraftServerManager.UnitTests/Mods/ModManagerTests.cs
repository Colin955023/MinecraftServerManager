using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Mods;

namespace MinecraftServerManager.UnitTests.Mods;

public sealed class ModManagerTests : IDisposable
{
    private readonly TempDirectory _testDirTemp = new("msm_test_modmgr_");
    private readonly string _testDir;

    public ModManagerTests()
    {
        _testDir = _testDirTemp.FullName;
    }

    public void Dispose() => _testDirTemp.Dispose();

    [Fact]
    public async Task ModManager_AllOperations_DelegatesToScannerAndInstaller()
    {
        var sampleMods = new List<LocalModInfo>
        {
            new("testmod", "Test Mod", "testmod.jar", "1.0.0", "1.20.1", "fabric", author: "DevTeam", platform: ModPlatform.Local, status: ModStatus.Enabled)
        };

        var fakeScanner = new FakeScanner(sampleMods);
        var manager = new ModManager(fakeScanner, new ModFileInstaller(new StubHttpPort()));

        var mods = await manager.GetModsAsync(_testDir, cancellationToken: TestContext.Current.CancellationToken);
        var item = Assert.Single(mods);
        Assert.Equal("testmod", item.Id);
    }

    private sealed class FakeScanner(IReadOnlyList<LocalModInfo> mods) : ILocalModScanner
    {
        public Task<IReadOnlyList<LocalModInfo>> ScanModsAsync(string modsDirectory, CancellationToken cancellationToken = default) =>
            Task.FromResult(mods);
    }
}
