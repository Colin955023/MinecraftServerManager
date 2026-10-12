using MinecraftServerManager.Infrastructure.Mods;
using Xunit;

namespace MinecraftServerManager.UnitTests;

/// <summary>
/// 模組快取索引持久化測試
/// </summary>
public sealed class ModIndexPersistenceTests : IDisposable
{
    private readonly string _testDir;

    public ModIndexPersistenceTests()
    {
        _testDir = Path.Combine(Path.GetTempPath(), "msm_test_mod_index_" + Guid.NewGuid().ToString("N"));
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
    public void CacheMetadataAndRetrieveShouldPersistAcrossInstances()
    {
        var persistence1 = new ModIndexPersistence(_testDir);
        var meta = new Dictionary<string, string>
        {
            ["id"] = "fabric-api",
            ["name"] = "Fabric API",
            ["version"] = "0.92.0"
        };
        persistence1.CacheMetadata("fabric-api.jar", meta);
        persistence1.Flush();

        var persistence2 = new ModIndexPersistence(_testDir);
        var retrieved = persistence2.GetCachedMetadata("fabric-api.jar");

        Assert.NotNull(retrieved);
        Assert.Equal("fabric-api", retrieved["id"]);
        Assert.Equal("Fabric API", retrieved["name"]);
        Assert.Equal("0.92.0", retrieved["version"]);
    }

    [Fact]
    public void CacheHashAndRetrieveShouldWorkCorrectly()
    {
        var persistence = new ModIndexPersistence(_testDir);
        persistence.CacheHash("test-mod.jar", "sha256", "abcdef123456");
        persistence.Flush();

        var persistence2 = new ModIndexPersistence(_testDir);
        string? hash = persistence2.GetCachedHash("test-mod.jar", "sha256");

        Assert.Equal("abcdef123456", hash);
        Assert.Null(persistence2.GetCachedHash("test-mod.jar", "sha512"));
    }

    [Fact]
    public void CleanupStaleEntriesShouldRemoveMissingFiles()
    {
        var persistence = new ModIndexPersistence(_testDir);
        persistence.CacheMetadata("active.jar", new Dictionary<string, string> { ["id"] = "active" });
        persistence.CacheMetadata("stale.jar", new Dictionary<string, string> { ["id"] = "stale" });
        persistence.Flush();

        persistence.CleanupStaleEntries(["active.jar"]);
        persistence.Flush();

        var persistence2 = new ModIndexPersistence(_testDir);
        Assert.NotNull(persistence2.GetCachedMetadata("active.jar"));
        Assert.Null(persistence2.GetCachedMetadata("stale.jar"));
    }

    [Fact]
    public void ClearIndexShouldWipeAllEntries()
    {
        var persistence = new ModIndexPersistence(_testDir);
        persistence.CacheMetadata("mod1.jar", new Dictionary<string, string> { ["id"] = "1" });
        persistence.Flush();

        persistence.ClearIndex();

        var persistence2 = new ModIndexPersistence(_testDir);
        Assert.Null(persistence2.GetCachedMetadata("mod1.jar"));
    }
}
