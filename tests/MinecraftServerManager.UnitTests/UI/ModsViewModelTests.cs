using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ModsViewModelTests
{
    private static ModsViewModel CreateTestViewModel(IModrinthClient? modrinthClient = null)
    {
        modrinthClient ??= NoOp.Create<IModrinthClient>();
        var ui = NoOpUiService.Instance;
        var planner = new Infrastructure.Mods.ModDependencyPlanner(modrinthClient);
        var fileService = new Infrastructure.Mods.ModFileService();
        var modManager = NoOp.Create<IModManager>();
        var launcher = NoOp.Create<IExternalLauncher>();
        var runtimeHost = NoOp.Create<IServerRuntimeHost>();
        var context = new ModsContext();
        return new ModsViewModel(
            context,
            new LocalModsViewModel(context, fileService, new Infrastructure.Mods.ModListExporter(), ui, modManager, launcher),
            new OnlineModSearchViewModel(context, ui, modrinthClient, launcher),
            new ModInstallQueueViewModel(context, planner, fileService, ui, modManager, modrinthClient, runtimeHost),
            new ModUpdateViewModel(context, planner, fileService, ui, modManager, modrinthClient, runtimeHost),
            NoOp.Create<IServerManager>(),
            ui);
    }

    [Fact]
    public void PlatformOptions_Default_ContainsBothWithModrinthSelected()
    {
        var vm = CreateTestViewModel();
        Assert.Equal("Modrinth", vm.Online.SelectedPlatform);
        Assert.Contains("Modrinth", vm.Online.PlatformOptions);
        Assert.Contains("CurseForge", vm.Online.PlatformOptions);
    }

    [Fact]
    public void SelectedPlatform_CurseForge_ClearsResultsAndShowsHint()
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
    public async Task SearchOnlineMods_CurseForge_DoesNotCallModrinth()
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
