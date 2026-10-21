using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class ServerPlayerConfigStoreTests : IDisposable
{
    private readonly string _testDir;
    private readonly ServerPlayerConfigStore _store;

    public ServerPlayerConfigStoreTests()
    {
        _testDir = Path.Combine(Path.GetTempPath(), "msm_player_store_tests_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_testDir);
        _store = new ServerPlayerConfigStore();
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
    public async Task LoadBundleAsync_WhenDirectoryHasNoJsonFiles_ReturnsEmptyCollections()
    {
        var bundle = await _store.LoadBundleAsync(_testDir);

        Assert.NotNull(bundle);
        Assert.Empty(bundle.UserCache);
        Assert.Empty(bundle.Operators);
        Assert.Empty(bundle.Whitelist);
        Assert.Empty(bundle.BannedPlayers);
        Assert.Empty(bundle.BannedIps);
    }

    [Fact]
    public async Task SaveBundleAsync_AndLoadBundleAsync_ShouldRoundTripCorrectly()
    {
        var originalBundle = new ServerPlayerConfigBundle(
            UserCache:
            [
                new ServerUserCacheEntry("PlayerA", "11111111-2222-3333-4444-555555555555", "2026-10-18 20:00:00 +0800")
            ],
            Operators:
            [
                new ServerOperatorEntry("11111111-2222-3333-4444-555555555555", "PlayerA", 4, false)
            ],
            Whitelist:
            [
                new ServerWhitelistEntry("11111111-2222-3333-4444-555555555555", "PlayerA")
            ],
            BannedPlayers:
            [
                new ServerBannedPlayerEntry("22222222-3333-4444-5555-666666666666", "GrieferB", "2026-10-18 20:30:00 +0800", "Server", "forever", "Cheat")
            ],
            BannedIps:
            [
                new ServerBannedIpEntry("192.168.1.100", "2026-10-18 20:30:00 +0800", "Server", "forever", "Spam")
            ]);

        await _store.SaveBundleAsync(_testDir, originalBundle);

        var loaded = await _store.LoadBundleAsync(_testDir);

        Assert.Single(loaded.Operators);
        Assert.Equal("PlayerA", loaded.Operators[0].Name);
        Assert.Equal("11111111-2222-3333-4444-555555555555", loaded.Operators[0].Uuid);
        Assert.Equal(4, loaded.Operators[0].Level);
        Assert.False(loaded.Operators[0].BypassesPlayerLimit);

        Assert.Single(loaded.Whitelist);
        Assert.Equal("PlayerA", loaded.Whitelist[0].Name);

        Assert.Single(loaded.BannedPlayers);
        Assert.Equal("GrieferB", loaded.BannedPlayers[0].Name);
        Assert.Equal("Cheat", loaded.BannedPlayers[0].Reason);

        Assert.Single(loaded.BannedIps);
        Assert.Equal("192.168.1.100", loaded.BannedIps[0].Ip);
        Assert.Equal("Spam", loaded.BannedIps[0].Reason);

        // 驗證 ops.json 檔案存在且為合法 JSON 陣列
        string opsPath = Path.Combine(_testDir, "ops.json");
        Assert.True(File.Exists(opsPath));
        string opsJson = await File.ReadAllTextAsync(opsPath);
        Assert.StartsWith("[", opsJson.Trim(), StringComparison.Ordinal);
        Assert.Contains("\"bypassesPlayerLimit\": false", opsJson, StringComparison.Ordinal);
    }
}
