using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class PlayerManagementViewModelTests
{
    [Fact]
    public async Task InitializeAsync_LoadsBundleAndInitializesCollections()
    {
        var fakeStore = new FakePlayerConfigStore(new ServerPlayerConfigBundle(
            UserCache: [new ServerUserCacheEntry("Steve", "1111-2222", "2026-01-01")],
            Operators: [new ServerOperatorEntry("1111-2222", "Steve", 4, false)],
            Whitelist: [],
            BannedPlayers: [],
            BannedIps: []));

        var vm = new PlayerManagementViewModel("TestServer", "C:\\fake\\server", fakeStore, NoOpUiService.Instance);
        await vm.InitializeAsync();

        Assert.Single(vm.FilteredUserCache);
        Assert.Single(vm.Operators);
        Assert.Empty(vm.Whitelist);
        Assert.False(vm.HasUnsavedChanges);
        Assert.Equal("Steve", vm.SelectedOpCandidate?.Name);
    }

    [Fact]
    public async Task AddOperator_WhenValidCandidate_AddsAndSetsHasUnsavedChanges()
    {
        var fakeStore = new FakePlayerConfigStore(new ServerPlayerConfigBundle(
            UserCache: [new ServerUserCacheEntry("Alex", "aaaa-bbbb", "2026-01-01")],
            Operators: [],
            Whitelist: [],
            BannedPlayers: [],
            BannedIps: []));

        var vm = new PlayerManagementViewModel("TestServer", "C:\\fake\\server", fakeStore, NoOpUiService.Instance);
        await vm.InitializeAsync();

        vm.SelectedOpCandidate = vm.AvailableCandidates[0];
        vm.SelectedOpLevel = vm.OpLevelOptions[1]; // Level 3
        vm.OpBypassesPlayerLimit = true;

        vm.AddOperatorCommand.Execute(null);

        var item = Assert.Single(vm.Operators);
        Assert.Equal("Alex", item.Name);
        Assert.Equal(3, vm.Operators[0].Level);
        Assert.True(vm.Operators[0].BypassesPlayerLimit);
        Assert.True(vm.HasUnsavedChanges);
    }

    [Fact]
    public async Task AddOperator_WhenAlreadyExists_DoesNotDuplicate()
    {
        var fakeStore = new FakePlayerConfigStore(new ServerPlayerConfigBundle(
            UserCache: [new ServerUserCacheEntry("Alex", "aaaa-bbbb", "2026-01-01")],
            Operators: [new ServerOperatorEntry("aaaa-bbbb", "Alex", 4, false)],
            Whitelist: [],
            BannedPlayers: [],
            BannedIps: []));

        var vm = new PlayerManagementViewModel("TestServer", "C:\\fake\\server", fakeStore, NoOpUiService.Instance);
        await vm.InitializeAsync();

        vm.SelectedOpCandidate = vm.AvailableCandidates[0];
        vm.AddOperatorCommand.Execute(null);

        Assert.Single(vm.Operators);
        Assert.Contains("已在管理員名單中", vm.StatusMessage);
    }

    [Fact]
    public async Task RemoveOperator_RemovesEntryAndSetsHasUnsavedChanges()
    {
        var op = new ServerOperatorEntry("aaaa-bbbb", "Alex", 4, false);
        var fakeStore = new FakePlayerConfigStore(new ServerPlayerConfigBundle(
            UserCache: [],
            Operators: [op],
            Whitelist: [],
            BannedPlayers: [],
            BannedIps: []));

        var vm = new PlayerManagementViewModel("TestServer", "C:\\fake\\server", fakeStore, NoOpUiService.Instance);
        await vm.InitializeAsync();

        vm.RemoveOperatorCommand.Execute(vm.Operators[0]);

        Assert.Empty(vm.Operators);
        Assert.True(vm.HasUnsavedChanges);
    }

    [Fact]
    public async Task Cancel_WhenHasChangesAndUserDeclinesDiscard_DoesNotClose()
    {
        var fakeStore = new FakePlayerConfigStore(new ServerPlayerConfigBundle([], [], [], [], []));
        var fakeUi = new ConfirmingUiService(confirmResult: false);

        var vm = new PlayerManagementViewModel("TestServer", "C:\\fake\\server", fakeStore, fakeUi);
        await vm.InitializeAsync();

        // 觸發變更
        vm.BanIpAddress = "10.0.0.1";
        vm.AddBannedIpCommand.Execute(null);
        Assert.True(vm.HasUnsavedChanges);

        bool closeInvoked = false;
        vm.RequestClose += _ => closeInvoked = true;

        vm.CancelCommand.Execute(null);

        Assert.False(closeInvoked);
    }

    [Fact]
    public async Task Cancel_WhenHasChangesAndUserConfirmsDiscard_ClosesWithFalse()
    {
        var fakeStore = new FakePlayerConfigStore(new ServerPlayerConfigBundle([], [], [], [], []));
        var fakeUi = new ConfirmingUiService(confirmResult: true);

        var vm = new PlayerManagementViewModel("TestServer", "C:\\fake\\server", fakeStore, fakeUi);
        await vm.InitializeAsync();

        vm.BanIpAddress = "10.0.0.1";
        vm.AddBannedIpCommand.Execute(null);

        bool? closeResult = null;
        vm.RequestClose += res => closeResult = res;

        vm.CancelCommand.Execute(null);

        Assert.False(closeResult);
    }

    [Fact]
    public async Task SaveAsync_SavesBundleAndClosesWithTrue()
    {
        var fakeStore = new FakePlayerConfigStore(new ServerPlayerConfigBundle([], [], [], [], []));
        var vm = new PlayerManagementViewModel("TestServer", "C:\\fake\\server", fakeStore, NoOpUiService.Instance);
        await vm.InitializeAsync();

        vm.BanIpAddress = "192.168.1.50";
        vm.AddBannedIpCommand.Execute(null);

        bool? closeResult = null;
        vm.RequestClose += res => closeResult = res;

        await vm.SaveCommand.ExecuteAsync(null);

        Assert.True(closeResult);
        Assert.False(vm.HasUnsavedChanges);
        Assert.NotNull(fakeStore.SavedBundle);
        var item = Assert.Single(fakeStore.SavedBundle.BannedIps);
        Assert.Equal("192.168.1.50", item.Ip);
    }

    [Theory]
    [InlineData("invalid-ip-format")]
    [InlineData("0.0.0.0")]
    [InlineData("::")]
    [InlineData("127.0.0.1")]
    [InlineData("::1")]
    [InlineData("255.255.255.255")]
    public async Task AddBannedIp_InvalidOrReservedIps_AreRejected(string ipToTest)
    {
        var fakeStore = new FakePlayerConfigStore(new ServerPlayerConfigBundle([], [], [], [], []));
        var vm = new PlayerManagementViewModel("TestServer", "C:\\fake\\server", fakeStore, NoOpUiService.Instance);
        await vm.InitializeAsync();

        vm.BanIpAddress = ipToTest;
        vm.AddBannedIpCommand.Execute(null);

        Assert.Empty(vm.BannedIps);
        Assert.False(vm.HasUnsavedChanges);
    }

    [Fact]
    public async Task OperatorRows_ToggleAndSave_OnlySavesActiveOperators()
    {
        var fakeStore = new FakePlayerConfigStore(new ServerPlayerConfigBundle(
            UserCache: [
                new ServerUserCacheEntry("PlayerA", "uuid-a", "2026-01-01"),
                new ServerUserCacheEntry("PlayerB", "uuid-b", "2026-01-01")
            ],
            Operators: [
                new ServerOperatorEntry("uuid-a", "PlayerA", 4, false)
            ],
            Whitelist: [],
            BannedPlayers: [],
            BannedIps: []));

        var vm = new PlayerManagementViewModel("TestServer", "C:\\fake\\server", fakeStore, NoOpUiService.Instance);
        await vm.InitializeAsync();

        Assert.Equal(2, vm.OperatorRows.Count);
        var rowA = vm.OperatorRows.First(r => r.Uuid == "uuid-a");
        var rowB = vm.OperatorRows.First(r => r.Uuid == "uuid-b");

        Assert.True(rowA.IsOp);
        Assert.False(rowB.IsOp);

        // 取消 A 的管理員，將 B 設為管理員 (Level 3, BypassesPlayerLimit = true)
        rowA.IsOp = false;
        rowB.IsOp = true;
        rowB.Level = 3;
        rowB.BypassesPlayerLimit = true;

        Assert.True(vm.HasUnsavedChanges);

        await vm.SaveCommand.ExecuteAsync(null);

        Assert.NotNull(fakeStore.SavedBundle);
        var item = Assert.Single(fakeStore.SavedBundle.Operators);
        Assert.Equal("uuid-b", item.Uuid);
        Assert.Equal(3, fakeStore.SavedBundle.Operators[0].Level);
        Assert.True(fakeStore.SavedBundle.Operators[0].BypassesPlayerLimit);
    }

    [Fact]
    public async Task ApplyUserCacheFilter_OnlyFiltersByName_NotByUuid()
    {
        var fakeStore = new FakePlayerConfigStore(new ServerPlayerConfigBundle(
            UserCache: [
                new ServerUserCacheEntry("Steve", "1111-2222-3333", "2026-01-01 12:00:00 +0800"),
                new ServerUserCacheEntry("Alex", "4444-5555-6666", "2026-01-01 12:00:00 +0800")
            ],
            Operators: [],
            Whitelist: [],
            BannedPlayers: [],
            BannedIps: []));

        var vm = new PlayerManagementViewModel("TestServer", "C:\\fake\\server", fakeStore, NoOpUiService.Instance);
        await vm.InitializeAsync();

        // 搜尋玩家名稱
        vm.PlayerSearchText = "Ste";
        var item = Assert.Single(vm.FilteredUserCache);
        Assert.Equal("Steve", item.Name);

        // 搜尋 UUID（以前會匹配，現在僅搜尋 Name，故不匹配）
        vm.PlayerSearchText = "1111";
        Assert.Empty(vm.FilteredUserCache);
    }

    [Fact]
    public void ServerPlayerTimeFormatter_FormatsToGmt8WithoutOffset()
    {
        // 台灣時區 GMT+8 格式（原本尾綴有 +0800）
        string formatted1 = ServerPlayerTimeFormatter.FormatToGmt8("2025-07-05 23:23:35 +0800");
        Assert.Equal("2025-07-05 23:23:35", formatted1);

        // UTC 時間轉換至 GMT+8
        string formatted2 = ServerPlayerTimeFormatter.FormatToGmt8("2025-07-05 15:23:35 +0000");
        Assert.Equal("2025-07-05 23:23:35", formatted2);

        // ISO 8601
        string formatted3 = ServerPlayerTimeFormatter.FormatToGmt8("2025-07-05T15:23:35Z");
        Assert.Equal("2025-07-05 23:23:35", formatted3);

        // 空字串或 null
        Assert.Empty(ServerPlayerTimeFormatter.FormatToGmt8(null));
        Assert.Empty(ServerPlayerTimeFormatter.FormatToGmt8("   "));
    }

    private sealed class FakePlayerConfigStore(ServerPlayerConfigBundle bundle) : IServerPlayerConfigStore
    {
        public ServerPlayerConfigBundle? SavedBundle { get; private set; }

        public Task<ServerPlayerConfigBundle> LoadBundleAsync(string serverPath, CancellationToken cancellationToken = default) =>
            Task.FromResult(bundle);

        public Task SaveBundleAsync(string serverPath, ServerPlayerConfigBundle bundleToSave, CancellationToken cancellationToken = default)
        {
            SavedBundle = bundleToSave;
            return Task.CompletedTask;
        }
    }

    private sealed class ConfirmingUiService(bool confirmResult) : NoOpUiService
    {
        public override bool Confirm(string message, string title, UiMessageLevel level = UiMessageLevel.Question) =>
            confirmResult;
    }
}
