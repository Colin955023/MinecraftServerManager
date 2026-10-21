using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ModsViewModelTests
{
    [Fact]
    public void PlatformOptionsShouldContainModrinthAndCurseForgeWithModrinthDefault()
    {
        var vm = new ModsViewModel();
        Assert.Equal("Modrinth", vm.SelectedPlatform);
        Assert.Contains("Modrinth", ModsViewModel.PlatformOptions);
        Assert.Contains("CurseForge", ModsViewModel.PlatformOptions);
    }

    [Fact]
    public void SwitchingToCurseForgeShouldClearOnlineModsAndShowHint()
    {
        var vm = new ModsViewModel();
        vm.OnlineMods.Add(new OnlineModRowItem { Title = "TestMod" });
        Assert.NotEmpty(vm.OnlineMods);

        vm.SelectedPlatform = "CurseForge";

        Assert.Empty(vm.OnlineMods);
        Assert.Null(vm.SelectedOnlineMod);
        Assert.Equal("CurseForge 模組搜尋即將推出，敬請期待", vm.OnlineResultHint);
    }

    [Fact]
    public async Task SearchOnlineModsWithCurseForgeShouldNotCallModrinth()
    {
        bool modrinthCalled = false;
        var fakeModrinth = new FakeModrinthClient(() => modrinthCalled = true);
        var vm = new ModsViewModel(modrinthClient: fakeModrinth)
        {
            SelectedPlatform = "CurseForge"
        };

        await vm.SearchOnlineModsCommand.ExecuteAsync(null);

        Assert.False(modrinthCalled);
        Assert.Equal("CurseForge 模組搜尋即將推出，敬請期待", vm.OnlineResultHint);
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
