using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests.Servers;

public sealed class ServerRegistryStoreTests : IDisposable
{
    private readonly TempDirectory _temp = new("msm-registry-store-");

    public void Dispose() => _temp.Dispose();

    private string RegistryPath => Path.Combine(_temp.FullName, ServerDefaults.RegistryFileName);

    private ServerConfig Create(string name) =>
        new(ServerName.Parse(name), MinecraftVersion.Parse("1.21.4"), LoaderKind.Vanilla, string.Empty, 2048, null, path: Path.Combine(_temp.FullName, name));

    [Fact]
    public void SetFindGetAll_RoundTripsAndIgnoresCase()
    {
        var store = new ServerRegistryStore(_temp.FullName);
        store.Set("Alpha", Create("Alpha"));

        var found = store.Find("alpha");

        Assert.NotNull(found);
        Assert.Equal("Alpha", found.Name.Value);
        Assert.Single(store.GetAll());
        Assert.Equal(Path.Combine(_temp.FullName, "Alpha"), store.FindPath("ALPHA"));

        store.Remove("alpha");
        Assert.Null(store.Find("Alpha"));
        Assert.Empty(store.GetAll());
    }

    [Fact]
    public void UnreadableRegistry_IsPreservedAsBadAndStoreContinuesEmpty()
    {
        File.WriteAllText(RegistryPath, "{ not valid json");
        var store = new ServerRegistryStore(_temp.FullName);

        Assert.Empty(store.GetAll());
        Assert.True(File.Exists(RegistryPath + ".bad"));
        Assert.Equal("{ not valid json", File.ReadAllText(RegistryPath + ".bad"));
    }

    [Fact]
    public void ExternalModification_IsReloaded()
    {
        var store = new ServerRegistryStore(_temp.FullName);
        store.Set("Alpha", Create("Alpha"));
        Assert.Single(store.GetAll());

        var other = new ServerRegistryStore(_temp.FullName);
        other.Set("Beta", Create("Beta"));
        // 確保最後寫入時間與快取不同
        File.SetLastWriteTimeUtc(RegistryPath, DateTime.UtcNow.AddMinutes(1));

        Assert.Equal(2, store.GetAll().Count);
    }

    [Fact]
    public void Update_WritesOnlyOnce()
    {
        var store = new ServerRegistryStore(_temp.FullName);
        store.Set("Seed", Create("Seed"));
        var before = new DateTime(2020, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        File.SetLastWriteTimeUtc(RegistryPath, before);
        var reread = new ServerRegistryStore(_temp.FullName);

        int count = reread.Update(registry =>
        {
            registry["A"] = ServerConfigPayload.FromDomain(Create("A"));
            registry["B"] = ServerConfigPayload.FromDomain(Create("B"));
            return registry.Count;
        });

        Assert.Equal(3, count);
        Assert.Equal(3, reread.GetAll().Count);
        Assert.NotEqual(before, File.GetLastWriteTimeUtc(RegistryPath));
    }
}
