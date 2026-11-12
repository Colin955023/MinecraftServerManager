using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.Mods;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

/// <summary>模組頁子 ViewModel 與共用狀態測試</summary>
public sealed class ModsChildViewModelTests
{
    private static ServerConfig CreateServer(string name = "FabricServer") =>
        new(ServerName.Parse(name), MinecraftVersion.Parse("1.21.4"), LoaderKind.Fabric, "0.16.0", 2048, path: Path.Combine(Path.GetTempPath(), name));

    private static LocalModsViewModel CreateLocal(ModsContext context, ManualUiService? ui = null, IModManager? modManager = null) =>
        new(context, new ModFileService(), new ModListExporter(), ui ?? new ManualUiService(), modManager ?? NoOp.Create<IModManager>(), NoOp.Create<IExternalLauncher>());

    /// <summary>以假模組管理員載入指定模組至本地清單</summary>
    private static async Task<LocalModsViewModel> CreateLoadedLocalAsync(params LocalModInfo[] mods)
    {
        var context = new ModsContext();
        context.SetServer(CreateServer());
        var local = CreateLocal(context, modManager: new FakeModManager(mods));
        await local.LoadLocalModsAsync();
        return local;
    }

    [Fact]
    public async Task ModsContext_RunsChangeHandlersSequentiallyAndRaisesServerChanged()
    {
        var context = new ModsContext();
        var order = new List<int>();
        int serverChanged = 0;
        context.ServerChanged += () => serverChanged++;
        context.RegisterModsChangedHandler(async () => { await Task.Yield(); order.Add(1); });
        context.RegisterModsChangedHandler(() => { order.Add(2); return Task.CompletedTask; });

        context.SetServer(CreateServer());
        await context.NotifyModsChangedAsync();

        Assert.Equal(1, serverChanged);
        Assert.NotNull(context.Server);
        Assert.Equal("fabric", context.LoaderId);
        Assert.Equal("1.21.4", context.MinecraftVersion);
        Assert.Equal([1, 2], order);
    }

    [Fact]
    public async Task LocalMods_LoadDeduplicatesByFileNameAndMapsFields()
    {
        var local = await CreateLoadedLocalAsync(
            new LocalModInfo("a", "Sodium", "sodium.jar", "0.6.0", "1.21.4", "fabric", fileSize: 2048, platform: ModPlatform.Local),
            new LocalModInfo("a2", "Sodium Copy", "SODIUM.jar", "0.6.0", "1.21.4", "fabric"),
            new LocalModInfo("b", "Lithium", "lithium.jar", "", "1.21.4", "fabric", status: ModStatus.Disabled));

        Assert.Equal(2, local.LocalMods.Count);
        Assert.Equal(Core.Utilities.UnitFormatter.FormatBytes(2048), local.LocalMods[0].FileSize);
        Assert.Equal("Modrinth", local.LocalMods[0].SourcePlatform);
        Assert.Equal("-", local.LocalMods[1].Version);
        Assert.False(local.LocalMods[1].IsEnabled);
    }

    [Fact]
    public async Task LocalMods_FilterBySearchTextAndEnabledState()
    {
        var local = await CreateLoadedLocalAsync(
            new LocalModInfo("a", "Sodium", "sodium.jar", "1", "1.21.4", "fabric"),
            new LocalModInfo("b", "Lithium", "lithium.jar", "1", "1.21.4", "fabric", status: ModStatus.Disabled),
            new LocalModInfo("c", "Iris", "iris-sodium-addon.jar", "1", "1.21.4", "fabric"));

        local.LocalSearchText = "sodium";
        Assert.Equal(["Sodium", "Iris"], local.LocalMods.Select(static m => m.Name));

        local.LocalSearchText = string.Empty;
        local.SelectedLocalFilter = "已停用";
        Assert.Equal(["Lithium"], local.LocalMods.Select(static m => m.Name));
    }

    [Fact]
    public async Task LocalMods_SelectionUpdatesActionStates()
    {
        var local = await CreateLoadedLocalAsync(
            new LocalModInfo("a", "A", "a.jar", "1", "1.21.4", "fabric"),
            new LocalModInfo("b", "B", "b.jar", "1", "1.21.4", "fabric"));

        local.SetSelectedMods([local.LocalMods[0]]);
        Assert.False(local.CanBatchToggle);
        Assert.True(local.CanCheckUpdates);
        Assert.True(local.DeleteSelectedModCommand.CanExecute(null));
        Assert.Single(local.GetCheckedMods());

        local.SetSelectedMods(local.LocalMods);
        Assert.True(local.CanBatchToggle);
        Assert.True(local.CanCheckUpdates);
        Assert.Equal(2, local.GetCheckedMods().Count);

        local.SetSelectedMods([]);
        Assert.False(local.CanBatchToggle);
        Assert.False(local.CanCheckUpdates);
        Assert.False(local.DeleteSelectedModCommand.CanExecute(null));
    }

    [Fact]
    public void LocalMods_BuildModInfoTextSkipsPlaceholders()
    {
        string text = LocalModsViewModel.BuildModInfoText(new LocalModRowItem
        {
            Name = "Sodium",
            Version = "0.6.0",
            Author = "-",
            FileSize = "1.2 MB",
            IsEnabled = false,
        });

        Assert.Contains("模組名稱: Sodium", text, StringComparison.Ordinal);
        Assert.Contains("狀態: 停用", text, StringComparison.Ordinal);
        Assert.Contains("檔案大小: 1.2 MB", text, StringComparison.Ordinal);
        Assert.DoesNotContain("作者", text, StringComparison.Ordinal);
    }

    [Fact]
    public async Task LocalMods_ExportWithoutServerNotifiesError()
    {
        var ui = new ManualUiService();
        var local = CreateLocal(new ModsContext(), ui);

        await local.ExportModListCommand.ExecuteAsync(null);

        Assert.Single(ui.Notifications);
        Assert.Equal(NotificationType.Warning, ui.Notifications[0].Type);
    }

    [Fact]
    public void OnlineSearch_FilterHintFollowsServerContext()
    {
        var context = new ModsContext();
        var online = new OnlineModSearchViewModel(context, NoOpUiService.Instance, NoOp.Create<IModrinthClient>(), NoOp.Create<IExternalLauncher>());
        Assert.Equal("請先選擇伺服器以篩選相容模組", online.OnlineFilterHint);

        context.SetServer(CreateServer());
        Assert.Contains("Minecraft 1.21.4", online.OnlineFilterHint, StringComparison.Ordinal);
        Assert.Contains("Fabric", online.OnlineFilterHint, StringComparison.Ordinal);

        context.SetServer(null);
        Assert.Equal("請先選擇伺服器以篩選相容模組", online.OnlineFilterHint);
    }

    [Fact]
    public void OnlineSearch_PlatformButtonTextFollowsPlatform()
    {
        var online = new OnlineModSearchViewModel(new ModsContext(), NoOpUiService.Instance, NoOp.Create<IModrinthClient>(), NoOp.Create<IExternalLauncher>());
        Assert.Equal("開啟 Modrinth 頁面", online.OpenPlatformPageButtonText);

        online.SelectedPlatform = "CurseForge";
        Assert.Equal("開啟 CurseForge 頁面", online.OpenPlatformPageButtonText);
    }

    [Fact]
    public void InstallQueue_HintReflectsInstallAndUpdateCounts()
    {
        var queue = new ModInstallQueueViewModel(new ModsContext(), new ModDependencyPlanner(), new ModFileService(), NoOpUiService.Instance, NoOp.Create<IModManager>(), NoOp.Create<IModrinthClient>());
        queue.UpdateInstallQueueHint();
        Assert.Equal("安裝佇列為空", queue.InstallQueueHint);

        queue.InstallQueue.Add(new ModInstallQueueItem { FileName = "a.jar" });
        queue.InstallQueue.Add(new ModInstallQueueItem { FileName = "b.jar", Action = ModInstallAction.Update });
        queue.UpdateInstallQueueHint();
        Assert.Equal("安裝清單：1 個新增，1 個更新", queue.InstallQueueHint);

        queue.ClearInstallQueue();
        Assert.Empty(queue.InstallQueue);
        Assert.Equal("安裝佇列為空", queue.InstallQueueHint);
    }

    [Fact]
    public async Task InstallQueue_InstallWithoutServerNotifies()
    {
        var ui = new ManualUiService();
        var queue = new ModInstallQueueViewModel(new ModsContext(), new ModDependencyPlanner(), new ModFileService(), ui, NoOp.Create<IModManager>(), NoOp.Create<IModrinthClient>());

        await queue.InstallQueuedModsAsync();
        queue.InstallQueue.Add(new ModInstallQueueItem { FileName = "a.jar" });
        await queue.InstallQueuedModsAsync();

        Assert.Equal(["安裝清單目前沒有項目", "請先選擇伺服器"], ui.Notifications.Select(static n => n.Message));
    }

    [Fact]
    public async Task ModUpdates_RequireTargetsAndServer()
    {
        var ui = new ManualUiService();
        var updates = new ModUpdateViewModel(new ModsContext(), new ModDependencyPlanner(), new ModFileService(), ui, NoOp.Create<IModManager>(), NoOp.Create<IModrinthClient>());

        await updates.CheckModUpdatesAsync([]);
        await updates.CheckModUpdatesAsync([new LocalModRowItem { Name = "A" }]);

        Assert.Equal(["請先選取要檢查更新的模組", "請先選擇伺服器以檢查更新"], ui.Notifications.Select(static n => n.Message));
    }

    private static OnlineModVersion UpdateVersion(string id, string number, string project, params OnlineModDependency[] dependencies) =>
        new(id, number, $"{project} {number}", ["1.21.4"], ["fabric"], "release", "2026-01-01T00:00:00Z",
            [new ModFile($"{project}-{number}.jar", $"https://cdn.modrinth.com/data/{project}/{number}.jar", true, 1000, new Dictionary<string, string> { ["sha512"] = $"hash-{project}-{number}" })],
            dependencies, project);

    private static async Task<(ManualUiService Ui, StubModrinthClient Modrinth)> RunUpdateCheckAsync(
        IReadOnlyList<LocalModInfo> installed,
        Dictionary<string, IReadOnlyList<OnlineModVersion>> projects,
        Dictionary<string, string>? projectIdsByHash = null)
    {
        var context = new ModsContext();
        context.SetServer(CreateServer());
        var ui = new ManualUiService();
        var modrinth = new StubModrinthClient();
        foreach (var (k, v) in projects)
        {
            modrinth.Versions[k] = v;
            modrinth.Titles[k] = k;
        }

        if (projectIdsByHash is not null)
        {
            foreach (var (hash, projectId) in projectIdsByHash)
            {
                modrinth.HashLookups[hash] = new ModrinthVersionLookupResult("sha512", projectId, UpdateVersion("lookup", "0", projectId));
                modrinth.Titles[projectId] = projectId;
            }
        }

        var updates = new ModUpdateViewModel(context, new ModDependencyPlanner(), new ModFileService(), ui, new FakeModManager(installed), modrinth);

        await updates.CheckModUpdatesAsync([new LocalModRowItem { Id = "sodium", Name = "Sodium", Version = "1.0.0", CurrentHash = "old", HashAlgorithm = "sha512" }]);
        return (ui, modrinth);
    }

    private static readonly LocalModInfo InstalledSodium = new("sodium", "Sodium", "sodium-1.0.0.jar", "1.0.0", "1.21.4", "fabric");

    [Fact]
    public async Task ModUpdates_MissingRequiredDependencyIsAddedToUpdateList()
    {
        var (ui, _) = await RunUpdateCheckAsync(
            [InstalledSodium],
            new()
            {
                ["sodium"] = [UpdateVersion("v2", "2.0.0", "sodium", new OnlineModDependency("dep-lib", ModDependencyType.Required))],
                ["dep-lib"] = [UpdateVersion("d1", "1.0.0", "dep-lib")],
            });

        Assert.Equal(2, ui.ShownModUpdateCandidates.Count);
        Assert.Contains(ui.ShownModUpdateCandidates, static c => c.LocalMod is not null && c.ModName == "Sodium" && c.NewVersion == "2.0.0");
        Assert.Contains(ui.ShownModUpdateCandidates, static c => c.LocalMod is null && c.CurrentVersion == "未安裝" && c.ModName.Contains("Sodium 需要", StringComparison.Ordinal));
        Assert.DoesNotContain(ui.Notifications, static n => n.Type == NotificationType.Warning);
    }

    [Fact]
    public async Task ModUpdates_UnresolvableRequiredDependencyBlocksUpdateAndReports()
    {
        var (ui, _) = await RunUpdateCheckAsync(
            [InstalledSodium],
            new()
            {
                ["sodium"] = [UpdateVersion("v2", "2.0.0", "sodium", new OnlineModDependency("dep-lib", ModDependencyType.Required))],
                ["dep-lib"] = [],
            });

        Assert.Empty(ui.ShownModUpdateCandidates);
        Assert.Contains(ui.Notifications, static n => n.Type == NotificationType.Warning && n.Message.Contains("找不到相容版本", StringComparison.Ordinal) && n.Message.Contains("Sodium", StringComparison.Ordinal));
    }

    [Fact]
    public async Task ModUpdates_ConflictWithInstalledModBlocksUpdateAndReports()
    {
        var (ui, _) = await RunUpdateCheckAsync(
            [InstalledSodium, new LocalModInfo("bad-mod", "Bad Mod", "bad.jar", "1.0.0", "1.21.4", "fabric")],
            new()
            {
                ["sodium"] = [UpdateVersion("v2", "2.0.0", "sodium", new OnlineModDependency("bad-mod", ModDependencyType.Incompatible))],
            });

        Assert.Empty(ui.ShownModUpdateCandidates);
        Assert.Contains(ui.Notifications, static n => n.Type == NotificationType.Warning && n.Message.Contains("衝突", StringComparison.Ordinal));
    }

    [Fact]
    public async Task ModUpdates_InstalledDependencyIsTreatedAsSatisfiedWithoutUpgrade()
    {
        var (ui, modrinth) = await RunUpdateCheckAsync(
            [InstalledSodium, new LocalModInfo("dep-lib", "Dep Lib", "dep-lib-0.5.0.jar", "0.5.0", "1.21.4", "fabric")],
            new()
            {
                ["sodium"] = [UpdateVersion("v2", "2.0.0", "sodium", new OnlineModDependency("dep-lib", ModDependencyType.Required))],
                ["dep-lib"] = [UpdateVersion("d1", "1.0.0", "dep-lib")],
            });

        Assert.Single(ui.ShownModUpdateCandidates);
        Assert.DoesNotContain("dep-lib", modrinth.RequestedProjects);
    }

    [Fact]
    public async Task ModUpdates_InstalledDependencyMatchedByHashProjectIdIsNotReinstalled()
    {
        var (ui, modrinth) = await RunUpdateCheckAsync(
            [InstalledSodium, new LocalModInfo("ConfigLib", "Config Lib", "configlib-1.18.jar", "1.1.8", "1.21.4", "fabric", currentHash: "dep-hash", hashAlgorithm: "sha512")],
            new()
            {
                ["sodium"] = [UpdateVersion("v2", "2.0.0", "sodium", new OnlineModDependency("P1abc2Def", ModDependencyType.Required))],
                ["P1abc2Def"] = [UpdateVersion("d1", "1.1.26", "P1abc2Def")],
            },
            new() { ["dep-hash"] = "P1abc2Def" });

        Assert.Single(ui.ShownModUpdateCandidates);
        Assert.DoesNotContain("P1abc2Def", modrinth.RequestedProjects);
        Assert.DoesNotContain(ui.Notifications, static n => n.Type == NotificationType.Warning);
    }

    private sealed class FakeModManager(IReadOnlyList<LocalModInfo> mods) : IModManager
    {
        private static readonly LocalModMutationResult Done = new(ModOperationStatus.Completed);

        public Task<IReadOnlyList<LocalModInfo>> GetModsAsync(string serverDirectory, bool includeDisabled = true, CancellationToken cancellationToken = default) =>
            Task.FromResult(mods);

        public Task<LocalModMutationResult> SetModStateAsync(string serverDirectory, string modId, bool enable, CancellationToken cancellationToken = default) =>
            Task.FromResult(Done);

        public Task<LocalModMutationResult> DeleteModsAsync(string serverDirectory, IReadOnlyList<string> modIds, CancellationToken cancellationToken = default) =>
            Task.FromResult(Done);

        public Task<LocalModMutationResult> ImportModAsync(string serverDirectory, string sourceFilePath, CancellationToken cancellationToken = default) =>
            Task.FromResult(Done);

        public Task<ModFileOperationResult> InstallOnlineModAsync(
            string serverDirectory,
            string downloadUrl,
            string fileName,
            string? expectedHash = null,
            string? hashAlgorithm = null,
            IProgress<int>? progress = null,
            CancellationToken cancellationToken = default) =>
            Task.FromResult(new ModFileOperationResult(ModOperationStatus.Completed));
    }
}
