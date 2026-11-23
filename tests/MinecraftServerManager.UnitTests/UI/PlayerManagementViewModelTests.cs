using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class PlayerManagementViewModelTests
{
    [Fact]
    public async Task InitializeAsync_BundleExists_InitializesCollections()
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
        var row = Assert.Single(vm.OperatorRows);
        Assert.True(row.IsOp);
        Assert.Empty(vm.Whitelist);
        Assert.False(vm.HasUnsavedChanges);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task Cancel_WhenHasChanges_ClosesOnlyWhenUserConfirms(bool confirmDiscard)
    {
        var fakeStore = new FakePlayerConfigStore(new ServerPlayerConfigBundle([], [], [], [], []));
        var fakeUi = new ManualUiService { ConfirmResult = confirmDiscard };

        var vm = new PlayerManagementViewModel("TestServer", "C:\\fake\\server", fakeStore, fakeUi);
        await vm.InitializeAsync();

        vm.BanIpAddress = "10.0.0.1";
        vm.AddBannedIpCommand.Execute(null);
        Assert.True(vm.HasUnsavedChanges);

        bool? closeResult = null;
        vm.RequestClose += res => closeResult = res;

        vm.CancelCommand.Execute(null);

        if (confirmDiscard)
        {
            Assert.False(closeResult);
        }
        else
        {
            Assert.Null(closeResult);
        }
    }

    [Fact]
    public async Task SaveAsync_Edited_SavesAndClosesWithTrue()
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
    public void PlayerTimeFormatter_Format_ConvertsToLocalTimeZone()
    {
        string expected = new DateTimeOffset(2025, 7, 5, 15, 23, 35, TimeSpan.Zero)
            .ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss", System.Globalization.CultureInfo.InvariantCulture);

        // 名單檔常見格式（尾綴時區偏移）
        Assert.Equal(expected, PlayerTimeFormatter.Format("2025-07-05 23:23:35 +0800"));
        Assert.Equal(expected, PlayerTimeFormatter.Format("2025-07-05 15:23:35 +0000"));

        // ISO 8601
        Assert.Equal(expected, PlayerTimeFormatter.Format("2025-07-05T15:23:35Z"));

        // 無法解析時原樣回傳；空字串或 null 回傳空字串
        Assert.Equal("forever", PlayerTimeFormatter.Format("forever"));
        Assert.Empty(PlayerTimeFormatter.Format(null));
        Assert.Empty(PlayerTimeFormatter.Format("   "));
    }

    [Fact]
    public async Task SaveCommand_LoadFails_IsDisabled()
    {
        var fakeStore = new FakePlayerConfigStore(new ServerPlayerConfigBundle([], [], [], [], [])) { LoadFails = true };
        var vm = new PlayerManagementViewModel("TestServer", "C:\\fake\\server", fakeStore, NoOpUiService.Instance);

        await vm.InitializeAsync();
        await vm.SaveAsync();

        Assert.False(vm.IsLoaded);
        Assert.False(vm.SaveCommand.CanExecute(null));
        Assert.Null(fakeStore.SavedBundle);
    }

    [Fact]
    public async Task AddWhitelist_EmptyUuid_DedupesByName()
    {
        var offline = new ServerUserCacheEntry("Alex", string.Empty, "2026-01-01");
        var fakeStore = new FakePlayerConfigStore(new ServerPlayerConfigBundle(
            UserCache: [offline],
            Operators: [],
            Whitelist: [new ServerWhitelistEntry(string.Empty, "alex")],
            BannedPlayers: [],
            BannedIps: []));
        var vm = new PlayerManagementViewModel("TestServer", "C:\\fake\\server", fakeStore, NoOpUiService.Instance);
        await vm.InitializeAsync();

        vm.SelectedWhitelistCandidate = offline;
        vm.AddWhitelist();

        Assert.Single(vm.Whitelist);
        Assert.False(vm.HasUnsavedChanges);
    }

    private sealed class FakePlayerConfigStore(ServerPlayerConfigBundle bundle) : IServerPlayerConfigStore
    {
        public ServerPlayerConfigBundle? SavedBundle { get; private set; }

        public bool LoadFails { get; init; }

        public Task<ServerPlayerConfigBundle> LoadBundleAsync(string serverPath, CancellationToken cancellationToken = default) =>
            LoadFails ? Task.FromException<ServerPlayerConfigBundle>(new IOException("讀取失敗")) : Task.FromResult(bundle);

        public Task SaveBundleAsync(string serverPath, ServerPlayerConfigBundle bundleToSave, CancellationToken cancellationToken = default)
        {
            SavedBundle = bundleToSave;
            return Task.CompletedTask;
        }
    }
}
