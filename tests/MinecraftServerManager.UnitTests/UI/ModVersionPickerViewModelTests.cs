using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;

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

        var client = new StubModrinthClient { Versions = { ["proj-1"] = versions } };
        using var vm = new ModVersionPickerViewModel(client, "proj-1", "Test Mod", loader: LoaderKind.Fabric, minecraftVersion: "1.20.4");

        await vm.LoadVersionsAsync();

        var selected = Assert.Single(vm.Versions);
        Assert.Equal("v1", selected.VersionId);
        Assert.Equal("1.0.0", selected.VersionNumber);
        Assert.Same(selected, vm.SelectedVersion);
        Assert.Contains("共 1 個相容版本", vm.StatusMessage);
    }

    [Fact]
    public async Task LoadVersionsAsync_MixedDependencies_KeepsOnlyRequired()
    {
        var versions = new List<OnlineModVersion>
        {
            new(
                versionId: "v1",
                versionNumber: "1.0.0",
                displayName: "Version 1.0",
                files: [new ModFile("test.jar", "https://example.com/test.jar", IsPrimary: true)],
                dependencies:
                [
                    new OnlineModDependency("req-lib", ModDependencyType.Required),
                    new OnlineModDependency("opt-lib", ModDependencyType.Optional),
                    new OnlineModDependency("emb-lib", ModDependencyType.Embedded),
                    new OnlineModDependency("bad-lib", ModDependencyType.Incompatible),
                ])
        };

        using var vm = new ModVersionPickerViewModel(new StubModrinthClient { Versions = { ["proj-1"] = versions } }, "proj-1", "Test Mod");
        await vm.LoadVersionsAsync();

        Assert.Equal(["req-lib"], Assert.Single(vm.Versions).Dependencies);
    }

    [Fact]
    public async Task LoadVersionsAsync_WhenNoVersions_SetsEmptyStatusMessage()
    {
        var client = new StubModrinthClient();
        using var vm = new ModVersionPickerViewModel(client, "proj-empty", "Empty Mod");

        await vm.LoadVersionsAsync();

        Assert.Empty(vm.Versions);
        Assert.Null(vm.SelectedVersion);
        Assert.Contains("無相容版本", vm.StatusMessage);
    }

    [Fact]
    public async Task InstallCommand_VersionSelected_SetsQueuedVersionAndFlags()
    {
        var versions = new List<OnlineModVersion>
        {
            new(
                versionId: "v1",
                versionNumber: "1.0.0",
                displayName: "Version 1.0",
                files: [new ModFile("test.jar", "https://example.com/test.jar", IsPrimary: true)])
        };

        var client = new StubModrinthClient { Versions = { ["proj-1"] = versions } };
        using var vm = new ModVersionPickerViewModel(client, "proj-1", "Test Mod");
        await vm.LoadVersionsAsync();

        bool closed = false;
        vm.RequestClose += success => closed = success;

        vm.Install();

        Assert.True(closed);
        Assert.True(vm.InstallImmediately);
        Assert.NotNull(vm.QueuedVersion);
        Assert.Equal("v1", vm.QueuedVersion.VersionId);
    }
}
