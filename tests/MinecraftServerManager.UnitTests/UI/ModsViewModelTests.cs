using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ModsViewModelTests
{
    private static ModsViewModel CreateTestViewModel(IModrinthClient? modrinthClient = null)
    {
        return new ModsViewModel(
            new Infrastructure.Mods.ModDependencyPlanner(),
            new Infrastructure.Mods.ModListExporter(),
            new Infrastructure.Mods.ModFileService(),
            NoOpUiService.Instance,
            NoOp.Create<IServerManager>(),
            NoOp.Create<IModManager>(),
            modrinthClient ?? NoOp.Create<IModrinthClient>(),
            NoOp.Create<IExternalLauncher>());
    }

    [Fact]
    public void PlatformOptionsShouldContainModrinthAndCurseForgeWithModrinthDefault()
    {
        var vm = CreateTestViewModel();
        Assert.Equal("Modrinth", vm.Online.SelectedPlatform);
        Assert.Contains("Modrinth", OnlineModSearchViewModel.PlatformOptions);
        Assert.Contains("CurseForge", OnlineModSearchViewModel.PlatformOptions);
    }

    [Fact]
    public void SwitchingToCurseForgeShouldClearOnlineModsAndShowHint()
    {
        var vm = CreateTestViewModel();
        vm.Online.OnlineMods.Add(new OnlineModRowItem { Title = "TestMod" });
        Assert.NotEmpty(vm.Online.OnlineMods);

        vm.Online.SelectedPlatform = "CurseForge";

        Assert.Empty(vm.Online.OnlineMods);
        Assert.Null(vm.Online.SelectedOnlineMod);
        Assert.Equal("CurseForge 模組搜尋即將推出，敬請期待", vm.Online.OnlineResultHint);
    }

    [Fact]
    public async Task SearchOnlineModsWithCurseForgeShouldNotCallModrinth()
    {
        bool modrinthCalled = false;
        var fakeModrinth = new FakeModrinthClient(() => modrinthCalled = true);
        var vm = CreateTestViewModel(modrinthClient: fakeModrinth);
        vm.Online.SelectedPlatform = "CurseForge";

        await vm.Online.SearchOnlineModsCommand.ExecuteAsync(null);

        Assert.False(modrinthCalled);
        Assert.Equal("CurseForge 模組搜尋即將推出，敬請期待", vm.Online.OnlineResultHint);
    }

    private sealed class FakeModrinthClient(Action onSearchCalled) : IModrinthClient
    {
        public Task<IReadOnlyList<OnlineModInfo>> SearchModsAsync(
            string query,
            string? loader = null,
            string? minecraftVersion = null,
            int limit = 20,
            int offset = 0,
            string index = "relevance",
            CancellationToken cancellationToken = default)
        {
            onSearchCalled();
            return Task.FromResult<IReadOnlyList<OnlineModInfo>>([]);
        }

        public Task<IReadOnlyList<OnlineModVersion>> GetProjectVersionsAsync(
            string projectIdOrSlug,
            string? loader = null,
            string? minecraftVersion = null,
            CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyList<OnlineModVersion>>([]);

        public Task<IReadOnlyDictionary<string, ModrinthVersionLookupResult>> LookupVersionsByHashesAsync(
            IReadOnlyList<string> hashes,
            string algorithm = "sha512",
            CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyDictionary<string, ModrinthVersionLookupResult>>(new Dictionary<string, ModrinthVersionLookupResult>());

        public Task<IReadOnlyDictionary<string, string>> GetProjectTitlesAsync(IReadOnlyCollection<string> projectIdsOrSlugs, CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyDictionary<string, string>>(new Dictionary<string, string>());
    }
}
