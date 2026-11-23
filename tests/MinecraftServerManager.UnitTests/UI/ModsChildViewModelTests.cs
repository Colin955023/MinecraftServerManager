using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Mods;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ModsChildViewModelTests : IDisposable
{
    private readonly TempDirectory _serversRoot = new("msm-mods-child-");

    public void Dispose() => _serversRoot.Dispose();

    private ServerConfig CreateServer(string name = "FabricServer") =>
        TestServerConfigs.Create(name, loader: LoaderKind.Fabric, loaderVersion: "0.16.0", path: _serversRoot.Combine(name));

    private static LocalModsViewModel CreateLocal(ModsContext context, ManualUiService? ui = null, IModManager? modManager = null) =>
        new(context, new ModFileService(), new ModListExporter(), ui ?? new ManualUiService(), modManager ?? NoOp.Create<IModManager>(), NoOp.Create<IExternalLauncher>());

    /// <summary>以假模組管理員載入指定模組至本地清單</summary>
    private async Task<LocalModsViewModel> CreateLoadedLocalAsync(params LocalModInfo[] mods) =>
        (await CreateLoadedLocalWithFakesAsync(mods)).Local;

    /// <summary>載入指定模組並回傳可檢查呼叫紀錄的 UI 與模組管理員替身</summary>
    private async Task<(LocalModsViewModel Local, ManualUiService Ui, FakeModManager Manager)> CreateLoadedLocalWithFakesAsync(params LocalModInfo[] mods)
    {
        var context = new ModsContext();
        context.SetServer(CreateServer());
        var ui = new ManualUiService();
        var manager = new FakeModManager(mods);
        var local = CreateLocal(context, ui, manager);
        await local.LoadLocalModsAsync();
        return (local, ui, manager);
    }

    [Fact]
    public async Task ModsContext_ServerSetAndModsChanged_RunsHandlersInOrder()
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
        Assert.Equal(LoaderKind.Fabric, context.LoaderType);
        Assert.Equal("1.21.4", context.MinecraftVersion);
        Assert.Equal([1, 2], order);
    }

    [Fact]
    public async Task LoadLocalModsAsync_DuplicateFileNames_DeduplicatesAndMapsFields()
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
    public async Task LocalMods_SearchAndStateFilter_FiltersRows()
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
    public async Task SetSelectedMods_SelectionChanged_UpdatesActionStates()
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
    public async Task BatchToggle_SelectedMods_TogglesEachAndReportsFailures()
    {
        var (local, ui, manager) = await CreateLoadedLocalWithFakesAsync(
            new LocalModInfo("a", "A", "a.jar", "1", "1.21.4", "fabric"),
            new LocalModInfo("b", "B", "b.jar", "1", "1.21.4", "fabric"));
        manager.FailingIds.Add("b.jar");
        local.SetSelectedMods(local.LocalMods);

        await local.BatchToggleCommand.ExecuteAsync(null);

        Assert.Equal([("a.jar", false), ("b.jar", false)], manager.StateChanges);
        Assert.False(local.LocalMods.Single(static m => m.Name == "A").IsEnabled);
        Assert.True(local.LocalMods.Single(static m => m.Name == "B").IsEnabled);
        var (message, type) = Assert.Single(ui.Notifications);
        Assert.Equal(NotificationType.Warning, type);
        Assert.Contains("B：測試失敗", message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ImportMods_PickedFiles_ImportsEachAndSummarizesFailures()
    {
        var (local, ui, manager) = await CreateLoadedLocalWithFakesAsync();
        string ok = _serversRoot.Combine("ok.jar");
        string bad = _serversRoot.Combine("bad.jar");
        ui.FilesToPick = [ok, bad];
        manager.FailingIds.Add(bad);

        await local.ImportModsCommand.ExecuteAsync(null);

        Assert.Equal([ok, bad], manager.Imported);
        var (message, type) = Assert.Single(ui.Notifications);
        Assert.Equal(NotificationType.Warning, type);
        Assert.Contains("已成功匯入 1 個模組，1 個失敗", message, StringComparison.Ordinal);
        Assert.Contains("bad.jar：測試失敗", message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ImportMods_PickerCancelled_DoesNotImport()
    {
        var (local, ui, manager) = await CreateLoadedLocalWithFakesAsync();

        await local.ImportModsCommand.ExecuteAsync(null);

        Assert.Empty(manager.Imported);
        Assert.Empty(ui.Notifications);
    }

    [Fact]
    public async Task DeleteSelectedMod_Confirmed_DeletesByFileNameAndRemovesRows()
    {
        var (local, ui, manager) = await CreateLoadedLocalWithFakesAsync(
            new LocalModInfo("a", "A", "a.jar", "1", "1.21.4", "fabric"),
            new LocalModInfo("b", "B", "b.jar", "1", "1.21.4", "fabric"));
        local.SetSelectedMods(local.LocalMods);

        await local.DeleteSelectedModCommand.ExecuteAsync(null);

        Assert.Equal(["a.jar", "b.jar"], manager.Deleted);
        Assert.Empty(local.LocalMods);
        Assert.Contains("2 個模組", Assert.Single(ui.ConfirmMessages), StringComparison.Ordinal);
        Assert.Equal(("已成功刪除 2 個模組", NotificationType.Success), Assert.Single(ui.Notifications));
    }

    [Fact]
    public async Task DeleteSelectedMod_Declined_KeepsRows()
    {
        var (local, ui, manager) = await CreateLoadedLocalWithFakesAsync(
            new LocalModInfo("a", "A", "a.jar", "1", "1.21.4", "fabric"));
        ui.ConfirmResult = false;
        local.SetSelectedMods(local.LocalMods);

        await local.DeleteSelectedModCommand.ExecuteAsync(null);

        Assert.Empty(manager.Deleted);
        Assert.Single(local.LocalMods);
    }

    [Fact]
    public async Task DeleteSelectedMod_ManagerFails_KeepsRowsAndNotifiesError()
    {
        var (local, ui, manager) = await CreateLoadedLocalWithFakesAsync(
            new LocalModInfo("a", "A", "a.jar", "1", "1.21.4", "fabric"));
        manager.FailingIds.Add("a.jar");
        local.SetSelectedMods(local.LocalMods);

        await local.DeleteSelectedModCommand.ExecuteAsync(null);

        Assert.Single(local.LocalMods);
        Assert.Equal(("刪除失敗：測試失敗", NotificationType.Error), Assert.Single(ui.Notifications));
    }

    [Fact]
    public void BuildModInfoText_PlaceholderFields_SkipsThem()
    {
        string text = LocalModRowMapper.BuildModInfoText(new LocalModRowItem
        {
            Name = "Sodium",
            Version = "0.6.0",
            Author = "-",
            FileSize = "1.2 MB",
            IsEnabled = false,
        });

        Assert.Contains("模組名稱：Sodium", text, StringComparison.Ordinal);
        Assert.Contains("狀態：停用", text, StringComparison.Ordinal);
        Assert.Contains("檔案大小：1.2 MB", text, StringComparison.Ordinal);
        Assert.DoesNotContain("作者", text, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ExportModList_NoServer_NotifiesWarning()
    {
        var ui = new ManualUiService();
        var local = CreateLocal(new ModsContext(), ui);

        await local.ExportModListCommand.ExecuteAsync(null);

        Assert.Single(ui.Notifications);
        Assert.Equal(NotificationType.Warning, ui.Notifications[0].Type);
    }

    [Fact]
    public void OnlineFilterHint_ServerChanged_FollowsContext()
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
    public void PlatformButtonText_PlatformChanged_Follows()
    {
        var online = new OnlineModSearchViewModel(new ModsContext(), NoOpUiService.Instance, NoOp.Create<IModrinthClient>(), NoOp.Create<IExternalLauncher>());
        Assert.Equal("開啟 Modrinth 頁面", online.OpenPlatformPageButtonText);

        online.SelectedPlatform = "CurseForge";
        Assert.Equal("開啟 CurseForge 頁面", online.OpenPlatformPageButtonText);
    }

    [Fact]
    public void InstallQueueHint_InstallAndUpdateItems_ReflectsCounts()
    {
        var queue = new ModInstallQueueViewModel(new ModsContext(), new ModDependencyPlanner(NoOp.Create<IModrinthClient>()), new ModFileService(), NoOpUiService.Instance, NoOp.Create<IModManager>(), NoOp.Create<IModrinthClient>(), NoOp.Create<IServerRuntimeHost>());
        queue.UpdateInstallQueueHint();
        Assert.Equal("安裝清單為空", queue.InstallQueueHint);

        queue.InstallQueue.Add(new ModInstallQueueItem { FileName = "a.jar" });
        queue.InstallQueue.Add(new ModInstallQueueItem { FileName = "b.jar", Action = ModInstallAction.Update });
        queue.UpdateInstallQueueHint();
        Assert.Equal("安裝清單：1 個新增，1 個更新", queue.InstallQueueHint);

        queue.ClearInstallQueue();
        Assert.Empty(queue.InstallQueue);
        Assert.Equal("安裝清單為空", queue.InstallQueueHint);
    }

    [Fact]
    public async Task InstallQueue_NoServer_Notifies()
    {
        var ui = new ManualUiService();
        var queue = new ModInstallQueueViewModel(new ModsContext(), new ModDependencyPlanner(NoOp.Create<IModrinthClient>()), new ModFileService(), ui, NoOp.Create<IModManager>(), NoOp.Create<IModrinthClient>(), NoOp.Create<IServerRuntimeHost>());

        await queue.InstallQueuedModsAsync(TestContext.Current.CancellationToken);
        queue.InstallQueue.Add(new ModInstallQueueItem { FileName = "a.jar" });
        await queue.InstallQueuedModsAsync(TestContext.Current.CancellationToken);

        Assert.Equal(["安裝清單目前沒有項目", "請先選擇伺服器"], ui.Notifications.Select(static n => n.Message));
    }

    [Fact]
    public async Task CheckModUpdates_NoTargetsOrServer_Notifies()
    {
        var ui = new ManualUiService();
        var updates = new ModUpdateViewModel(new ModsContext(), new ModDependencyPlanner(NoOp.Create<IModrinthClient>()), new ModFileService(), ui, NoOp.Create<IModManager>(), NoOp.Create<IModrinthClient>(), NoOp.Create<IServerRuntimeHost>());

        await updates.CheckModUpdatesAsync([], TestContext.Current.CancellationToken);
        await updates.CheckModUpdatesAsync([new LocalModRowItem { Name = "A" }], TestContext.Current.CancellationToken);

        Assert.Equal(["請先選取要檢查更新的模組", "請先選擇伺服器以檢查更新"], ui.Notifications.Select(static n => n.Message));
    }

    private static OnlineModVersion UpdateVersion(string id, string number, string project, params OnlineModDependency[] dependencies) =>
        new(id, number, $"{project} {number}", ["1.21.4"], ["fabric"], "release", "2026-01-01T00:00:00Z",
            [new ModFile($"{project}-{number}.jar", $"https://cdn.modrinth.com/data/{project}/{number}.jar", true, 1000, new Dictionary<string, string> { ["sha512"] = $"hash-{project}-{number}" })],
            dependencies, project);

    private async Task<(ManualUiService Ui, StubModrinthClient Modrinth)> RunUpdateCheckAsync(
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

        var updates = new ModUpdateViewModel(context, new ModDependencyPlanner(modrinth), new ModFileService(), ui, new FakeModManager(installed), modrinth, NoOp.Create<IServerRuntimeHost>());

        await updates.CheckModUpdatesAsync([new LocalModRowItem { Id = "sodium", Name = "Sodium", Version = "1.0.0", CurrentHash = "old", HashAlgorithm = "sha512" }]);
        return (ui, modrinth);
    }

    private static readonly LocalModInfo InstalledSodium = new("sodium", "Sodium", "sodium-1.0.0.jar", "1.0.0", "1.21.4", "fabric");

    [Fact]
    public async Task CheckModUpdates_MissingRequiredDependency_AddsToList()
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
    public async Task CheckModUpdates_UnresolvableDependency_BlocksAndReports()
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
    public async Task CheckModUpdates_ConflictWithInstalled_BlocksAndReports()
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
    public async Task CheckModUpdates_InstalledDependency_TreatsAsSatisfied()
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
    public async Task CheckModUpdates_DependencyMatchedByHash_DoesNotReinstall()
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

    private static ModInstallQueueViewModel CreateQueue(ModsContext context, ManualUiService ui, IServerRuntimeHost? host = null) =>
        new(context, new ModDependencyPlanner(NoOp.Create<IModrinthClient>()), new ModFileService(), ui, new FakeModManager([]), NoOp.Create<IModrinthClient>(), host ?? NoOp.Create<IServerRuntimeHost>());

    [Fact]
    public void InstallQueue_ServerChanged_Clears()
    {
        var context = new ModsContext();
        using var queue = CreateQueue(context, new ManualUiService());
        queue.InstallQueue.Add(new ModInstallQueueItem { FileName = "a.jar" });

        context.SetServer(CreateServer("Other"));

        Assert.Empty(queue.InstallQueue);
    }

    [Fact]
    public async Task InstallQueue_ServerRunning_BlocksInstall()
    {
        var context = new ModsContext();
        context.SetServer(CreateServer());
        var host = new FakeServerRuntimeHost();
        host.GetFake("FabricServer").IsRunning = true;
        var ui = new ManualUiService();
        using var queue = CreateQueue(context, ui, host);
        queue.InstallQueue.Add(new ModInstallQueueItem { Title = "A", FileName = "a.jar", DownloadUrl = "https://cdn.modrinth.com/data/a/a.jar" });

        await queue.InstallQueuedModsAsync(TestContext.Current.CancellationToken);

        Assert.Single(queue.InstallQueue);
        Assert.Contains("請先停止伺服器", ui.LastNotification!.Value.Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task InstallQueue_UnofficialSource_IsSkippedWithWarning()
    {
        var context = new ModsContext();
        context.SetServer(CreateServer());
        var ui = new ManualUiService();
        using var queue = CreateQueue(context, ui);
        queue.InstallQueue.Add(new ModInstallQueueItem { Title = "Evil", FileName = "evil.jar", DownloadUrl = "https://evil.example/evil.jar" });

        await queue.InstallQueuedModsAsync(TestContext.Current.CancellationToken);

        Assert.Single(queue.InstallQueue);
        Assert.Contains(ui.Notifications, static n => n.Type == NotificationType.Warning && n.Message.Contains("非官方", StringComparison.Ordinal));
        Assert.False(queue.IsInstalling);
    }

    [Fact]
    public async Task LocalMods_Toggle_SyncsFileName()
    {
        var local = await CreateLoadedLocalAsync(new LocalModInfo("sodium", "Sodium", "sodium-1.0.0.jar", "1.0.0", "1.21.4", "fabric"));
        var mod = Assert.Single(local.LocalMods);

        await local.ToggleModCommand.ExecuteAsync(mod);
        Assert.False(mod.IsEnabled);
        Assert.Equal("sodium-1.0.0.jar.disabled", mod.FileName);

        await local.ToggleModCommand.ExecuteAsync(mod);
        Assert.Equal("sodium-1.0.0.jar", mod.FileName);
    }

    /// <summary>回傳固定模組清單並記錄異動呼叫；<see cref="FailingIds"/> 內的檔名／路徑回傳失敗</summary>
    private sealed class FakeModManager(IReadOnlyList<LocalModInfo> mods) : IModManager
    {
        private static readonly LocalModMutationResult Done = new(ModOperationStatus.Completed);
        private static readonly LocalModMutationResult Rejected = new(ModOperationStatus.Failed, Message: "測試失敗");

        public HashSet<string> FailingIds { get; } = new(StringComparer.OrdinalIgnoreCase);
        public List<(string ModId, bool Enable)> StateChanges { get; } = [];
        public List<string> Imported { get; } = [];
        public List<string> Deleted { get; } = [];

        public Task<IReadOnlyList<LocalModInfo>> GetModsAsync(string serverDirectory, bool includeDisabled = true, CancellationToken cancellationToken = default) =>
            Task.FromResult(mods);

        public Task<LocalModMutationResult> SetModStateAsync(string serverDirectory, string modId, bool enable, CancellationToken cancellationToken = default)
        {
            StateChanges.Add((modId, enable));
            return Task.FromResult(FailingIds.Contains(modId) ? Rejected : Done);
        }

        public Task<LocalModMutationResult> DeleteModsAsync(string serverDirectory, IReadOnlyList<string> modIds, CancellationToken cancellationToken = default)
        {
            Deleted.AddRange(modIds);
            return Task.FromResult(modIds.Any(FailingIds.Contains) ? Rejected : Done);
        }

        public Task<LocalModMutationResult> ImportModAsync(string serverDirectory, string sourceFilePath, CancellationToken cancellationToken = default)
        {
            Imported.Add(sourceFilePath);
            return Task.FromResult(FailingIds.Contains(sourceFilePath) ? Rejected : Done);
        }

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
