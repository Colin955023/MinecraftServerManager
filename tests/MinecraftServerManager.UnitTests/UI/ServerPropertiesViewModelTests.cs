using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ServerPropertiesViewModelTests
{
    [Fact]
    public async Task LoadPropertiesAsync_FileExists_LoadsProperties()
    {
        var store = new FakeServerPropertiesStore(new ServerPropertiesSnapshot(
            "TestServer",
            ServerPropertiesReadStatus.Ok,
            "rev-1",
            new Dictionary<string, string>
            {
                ["server-port"] = "25565",
                ["difficulty"] = "easy",
                ["online-mode"] = "true"
            }));

        var vm = new ServerPropertiesViewModel(store, "TestServer", NoOpUiService.Instance);
        await vm.LoadPropertiesAsync();

        Assert.Contains(vm.DisplayItems, item => item.Key == "server-port" && item.Value == "25565");
        Assert.Contains(vm.DisplayItems, item => item.Key == "difficulty" && item.Value == "easy");
        Assert.Contains(vm.DisplayItems, item => item.Key == "online-mode" && item.BoolValue);
    }

    [Fact]
    public async Task SearchText_Changed_FiltersDisplayItems()
    {
        var store = new FakeServerPropertiesStore(new ServerPropertiesSnapshot(
            "TestServer",
            ServerPropertiesReadStatus.Ok,
            "rev-1",
            new Dictionary<string, string>
            {
                ["server-port"] = "25565",
                ["difficulty"] = "easy",
                ["online-mode"] = "true"
            }));

        var vm = new ServerPropertiesViewModel(store, "TestServer", NoOpUiService.Instance);
        await vm.LoadPropertiesAsync();

        vm.SearchText = "online-mode";
        var item = Assert.Single(vm.DisplayItems);
        Assert.Equal("online-mode", item.Key);
    }

    [Fact]
    public async Task HasUnsavedChanges_FalseAfterLoad_AndSaveWritesOnlyEditedKeys()
    {
        var store = new FakeServerPropertiesStore(new ServerPropertiesSnapshot(
            "TestServer",
            ServerPropertiesReadStatus.Ok,
            "rev-1",
            new Dictionary<string, string> { ["server-port"] = "25565" }));
        var vm = new ServerPropertiesViewModel(store, "TestServer", NoOpUiService.Instance);
        await vm.LoadPropertiesAsync();

        Assert.True(vm.IsLoaded);
        Assert.False(vm.HasUnsavedChanges);

        vm.DisplayItems.First(static i => i.Key == "server-port").Value = "25570";
        Assert.True(vm.HasUnsavedChanges);
        await vm.SaveCommand.ExecuteAsync(null);

        var patch = Assert.Single(store.LastPatches!);
        Assert.Equal("server-port", patch.Key);
        Assert.Equal("25570", patch.Value);
    }

    [Fact]
    public void PropertyEditItem_ValueChange_ValidatesImmediately()
    {
        var item = new PropertyEditItem("server-port", "25565", "網路與安全", "埠號", "25565", PropertyEditorType.Text)
        {
            Value = "abc",
        };

        Assert.False(string.IsNullOrEmpty(item.ErrorMessage));
    }

    [Fact]
    public async Task SelectedCategory_Null_ResetsToAllWithoutClearingList()
    {
        var store = new FakeServerPropertiesStore(new ServerPropertiesSnapshot(
            "TestServer",
            ServerPropertiesReadStatus.Ok,
            "rev-1",
            new Dictionary<string, string> { ["server-port"] = "25565" }));
        var vm = new ServerPropertiesViewModel(store, "TestServer", NoOpUiService.Instance);
        await vm.LoadPropertiesAsync();
        int count = vm.DisplayItems.Count;

        vm.SelectedCategory = null!;

        Assert.Equal("全部", vm.SelectedCategory);
        Assert.Equal(count, vm.DisplayItems.Count);
    }

    [Fact]
    public void Commands_BeforeLoad_AreDisabled()
    {
        var vm = new ServerPropertiesViewModel(new PendingServerPropertiesStore(), "TestServer", NoOpUiService.Instance);

        Assert.False(vm.SaveCommand.CanExecute(null));
        Assert.False(vm.ResetAllToDefaultCommand.CanExecute(null));
    }

    private sealed class PendingServerPropertiesStore : IServerPropertiesStore
    {
        public Task<ServerPropertiesSnapshot> ReadAsync(string serverName, CancellationToken cancellationToken = default) =>
            new TaskCompletionSource<ServerPropertiesSnapshot>().Task;

        public Task<ServerPropertiesUpdateResult> UpdateAsync(string serverName, IReadOnlyDictionary<string, string> patches, string expectedRevision, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();
    }

    [Fact]
    public void PropertyEditItem_ResetToDefault_UpdatesValueCorrectly()
    {
        var item = new PropertyEditItem(
            key: "server-port",
            value: "25577",
            category: "網路與安全",
            description: "埠號",
            defaultValue: "25565",
            editorType: PropertyEditorType.Text);

        Assert.Equal("25577", item.Value);
        item.ResetToDefault();
        Assert.Equal("25565", item.Value);
        Assert.True(string.IsNullOrEmpty(item.ErrorMessage));
    }

    private sealed class FakeServerPropertiesStore(ServerPropertiesSnapshot snapshot) : IServerPropertiesStore
    {
        public ServerPropertiesSnapshot CurrentSnapshot { get; private set; } = snapshot;

        public IReadOnlyDictionary<string, string>? LastPatches { get; private set; }

        public Task<ServerPropertiesSnapshot> ReadAsync(string serverName, CancellationToken cancellationToken = default) =>
            Task.FromResult(CurrentSnapshot);

        public Task<ServerPropertiesUpdateResult> UpdateAsync(
            string serverName,
            IReadOnlyDictionary<string, string> patches,
            string expectedRevision,
            CancellationToken cancellationToken = default)
        {
            LastPatches = patches;
            var updated = new Dictionary<string, string>(CurrentSnapshot.Properties);
            foreach (var kv in patches)
            {
                updated[kv.Key] = kv.Value;
            }
            CurrentSnapshot = new ServerPropertiesSnapshot(serverName, ServerPropertiesReadStatus.Ok, "rev-next", updated);
            return Task.FromResult(new ServerPropertiesUpdateResult(true, CurrentSnapshot));
        }
    }
}
