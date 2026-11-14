using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;

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
        var fakeModrinth = new StubModrinthClient { OnSearchCalled = () => modrinthCalled = true };
        var vm = CreateTestViewModel(modrinthClient: fakeModrinth);
        vm.Online.SelectedPlatform = "CurseForge";

        await vm.Online.SearchOnlineModsCommand.ExecuteAsync(null);

        Assert.False(modrinthCalled);
        Assert.Equal("CurseForge 模組搜尋即將推出，敬請期待", vm.Online.OnlineResultHint);
    }
}
