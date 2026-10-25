using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ModVersionPickerViewModelTests
{
    [Fact]
    public async Task LoadVersionsAsync_WhenVersionsFound_SelectsFirstVersion()
    {
        var versions = new List<OnlineModVersion>
        {
            new(
                versionId: "v1",
                versionNumber: "1.0.0",
                displayName: "Version 1.0",
                gameVersions: ["1.20.4"],
                loaders: ["fabric"],
                files: [new ModFile("test-1.0.0.jar", "https://example.com/test.jar", IsPrimary: true)])
        };

        var client = new FakeModrinthClient(versions);
        var vm = new ModVersionPickerViewModel(client, "proj-1", "Test Mod", loader: "fabric", minecraftVersion: "1.20.4");

        await vm.LoadVersionsAsync();

        var selected = Assert.Single(vm.Versions);
        Assert.Equal("v1", selected.VersionId);
        Assert.Equal("1.0.0", selected.VersionNumber);
        Assert.Same(selected, vm.SelectedVersion);
        Assert.Contains("共 1 個相容版本", vm.StatusMessage);
    }

    [Fact]
    public async Task LoadVersionsAsync_WhenNoVersions_SetsEmptyStatusMessage()
    {
        var client = new FakeModrinthClient([]);
        var vm = new ModVersionPickerViewModel(client, "proj-empty", "Empty Mod");

        await vm.LoadVersionsAsync();

        Assert.Empty(vm.Versions);
        Assert.Null(vm.SelectedVersion);
        Assert.Contains("無相容版本", vm.StatusMessage);
    }

    [Fact]
    public async Task InstallCommand_SetsQueuedVersionAndFlags()
    {
        var versions = new List<OnlineModVersion>
        {
            new(
                versionId: "v1",
                versionNumber: "1.0.0",
                displayName: "Version 1.0",
                files: [new ModFile("test.jar", "https://example.com/test.jar", IsPrimary: true)])
        };

        var client = new FakeModrinthClient(versions);
        var vm = new ModVersionPickerViewModel(client, "proj-1", "Test Mod");
        await vm.LoadVersionsAsync();

        bool closed = false;
        vm.RequestClose += success => closed = success;

        vm.Install();

        Assert.True(closed);
        Assert.True(vm.InstallImmediately);
        Assert.NotNull(vm.QueuedVersion);
        Assert.Equal("v1", vm.QueuedVersion.VersionId);
    }

    private sealed class FakeModrinthClient(IReadOnlyList<OnlineModVersion> versions) : IModrinthClient
    {
        public Task<IReadOnlyList<OnlineModInfo>> SearchModsAsync(
            string query,
            string? loader = null,
            string? minecraftVersion = null,
            int limit = 20,
            int offset = 0,
            string index = "relevance",
            CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyList<OnlineModInfo>>([]);

        public Task<IReadOnlyList<OnlineModVersion>> GetProjectVersionsAsync(
            string projectIdOrSlug,
            string? loader = null,
            string? minecraftVersion = null,
            CancellationToken cancellationToken = default) =>
            Task.FromResult(versions);

        public Task<ModrinthVersionLookupResult?> LookupVersionByHashAsync(
            string hash,
            string algorithm = "sha512",
            CancellationToken cancellationToken = default) =>
            Task.FromResult<ModrinthVersionLookupResult?>(null);

        public Task<IReadOnlyDictionary<string, ModrinthVersionLookupResult>> LookupVersionsByHashesAsync(
            IReadOnlyList<string> hashes,
            string algorithm = "sha512",
            CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyDictionary<string, ModrinthVersionLookupResult>>(new Dictionary<string, ModrinthVersionLookupResult>());
    }
}
