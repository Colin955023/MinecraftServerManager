using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.Mods;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

/// <summary>
/// 模組頁子 ViewModel 與共用狀態測試
/// </summary>
public sealed class ModsChildViewModelTests
{
    private static ServerConfig CreateServer(string name = "FabricServer") =>
        new(ServerName.Parse(name), MinecraftVersion.Parse("1.21.4"), LoaderKind.Fabric, "0.16.0", 2048, path: Path.Combine(Path.GetTempPath(), name));

    private static LocalModsViewModel CreateLocal(ModsContext context, List<(string Message, NotificationType Type)>? notifications = null, IModManager? modManager = null) =>
        new(context, new ModFileService(), new ModListExporter(), new NotificationCaptureUiService((m, e) => notifications?.Add((m, e))), modManager ?? NoOp.Create<IModManager>(), NoOp.Create<IExternalLauncher>());

    /// <summary>
    /// 以假模組管理員載入指定模組至本地清單
    /// </summary>
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
            new LocalModInfo("a", "Sodium", "sodium.jar", "0.6.0", "1.21.4", "fabric", fileSize: 2048, platform: ModPlatform.Modrinth),
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
    public async Task LocalMods_SelectAllUpdatesActionStates()
    {
        var local = await CreateLoadedLocalAsync(
            new LocalModInfo("a", "A", "a.jar", "1", "1.21.4", "fabric"),
            new LocalModInfo("b", "B", "b.jar", "1", "1.21.4", "fabric"));

        local.ToggleSelectAll();
        Assert.True(local.CanBatchToggle);
        Assert.True(local.CanCheckUpdates);
        Assert.True(local.DeleteSelectedModCommand.CanExecute(null));
        Assert.Equal(2, local.GetCheckedMods().Count);

        local.ToggleSelectAll();
        Assert.False(local.CanBatchToggle);
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
        var notifications = new List<(string Message, NotificationType Type)>();
        var local = CreateLocal(new ModsContext(), notifications);

        await local.ExportModListCommand.ExecuteAsync(null);

        Assert.Single(notifications);
        Assert.Equal(NotificationType.Warning, notifications[0].Type);
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
        var notifications = new List<(string Message, NotificationType Type)>();
        var queue = new ModInstallQueueViewModel(new ModsContext(), new ModDependencyPlanner(), new ModFileService(), new NotificationCaptureUiService((m, e) => notifications.Add((m, e))), NoOp.Create<IModManager>(), NoOp.Create<IModrinthClient>());

        await queue.InstallQueuedModsAsync();
        queue.InstallQueue.Add(new ModInstallQueueItem { FileName = "a.jar" });
        await queue.InstallQueuedModsAsync();

        Assert.Equal(["安裝清單目前沒有項目", "請先選擇伺服器"], notifications.Select(static n => n.Message));
    }

    [Fact]
    public async Task ModUpdates_RequireTargetsAndServer()
    {
        var notifications = new List<(string Message, NotificationType Type)>();
        var updates = new ModUpdateViewModel(new ModsContext(), new ModDependencyPlanner(), new ModFileService(), new NotificationCaptureUiService((m, e) => notifications.Add((m, e))), NoOp.Create<IModManager>(), NoOp.Create<IModrinthClient>());

        await updates.CheckModUpdatesAsync([]);
        await updates.CheckModUpdatesAsync([new LocalModRowItem { Name = "A" }]);

        Assert.Equal(["請先選取要檢查更新的模組", "請先選擇伺服器以檢查更新"], notifications.Select(static n => n.Message));
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
