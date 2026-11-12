using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Infrastructure.Loaders;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class MojangVersionCatalogCacheTests
{
    [Fact]
    public void UpdateCachedVersions_NullResult_LeavesFileUntouched()
    {
        using var dirTemp = new TempDirectory("msm-vercache-");
        string path = MojangVersionCatalog.GetVersionsCachePath(dirTemp.FullName);

        var result = MojangVersionCatalog.UpdateCachedVersions(path, static _ => null);

        Assert.Empty(result);
        Assert.False(File.Exists(path));
    }

    [Fact]
    public void UpdateCachedVersions_AppliesChangeToLatestContent()
    {
        using var dirTemp = new TempDirectory("msm-vercache-");
        string path = MojangVersionCatalog.GetVersionsCachePath(dirTemp.FullName);
        MojangVersionCatalog.SaveCachedVersions(path, [new LoaderVersion("1.21", Stable: true, JavaMajor: 21)]);

        MojangVersionCatalog.UpdateCachedVersions(path, static current => [.. current, new LoaderVersion("1.20.1", Stable: true, JavaMajor: 17)]);

        var reloaded = MojangVersionCatalog.LoadCachedVersions(path);
        Assert.Equal(["1.21", "1.20.1"], reloaded.Select(static v => v.Version));
    }

    [Fact]
    public async Task UpdateCachedVersions_ConcurrentUpdates_DoNotLoseEachOther()
    {
        using var dirTemp = new TempDirectory("msm-vercache-");
        string path = MojangVersionCatalog.GetVersionsCachePath(dirTemp.FullName);

        await Task.WhenAll(Enumerable.Range(0, 24).Select(i => Task.Run(() =>
            MojangVersionCatalog.UpdateCachedVersions(path, current => [.. current, new LoaderVersion($"1.{i}", Stable: true)]))));

        var reloaded = MojangVersionCatalog.LoadCachedVersions(path);
        Assert.Equal(24, reloaded.Select(static v => v.Version).Distinct(StringComparer.Ordinal).Count());
    }
}
