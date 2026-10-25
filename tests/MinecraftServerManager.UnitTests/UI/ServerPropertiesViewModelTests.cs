using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ServerPropertiesViewModelTests
{
    [Fact]
    public async Task LoadPropertiesAsync_LoadsPropertiesSuccessfully()
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
    public async Task SearchText_FiltersDisplayItemsCorrectly()
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
        Assert.False(item.HasError);
    }

    private sealed class FakeServerPropertiesStore(ServerPropertiesSnapshot snapshot) : IServerPropertiesStore
    {
        public ServerPropertiesSnapshot CurrentSnapshot { get; private set; } = snapshot;

        public Task<ServerPropertiesSnapshot> ReadAsync(string serverName, CancellationToken cancellationToken = default) =>
            Task.FromResult(CurrentSnapshot);

        public Task<ServerPropertiesUpdateResult> UpdateAsync(
            string serverName,
            IReadOnlyDictionary<string, string> patches,
            string expectedRevision,
            CancellationToken cancellationToken = default)
        {
            var updated = new Dictionary<string, string>(CurrentSnapshot.Properties);
            foreach (var kv in patches)
            {
                updated[kv.Key] = kv.Value;
            }
            CurrentSnapshot = new ServerPropertiesSnapshot(serverName, ServerPropertiesReadStatus.Ok, "rev-next", updated);
            return Task.FromResult(new ServerPropertiesUpdateResult(true, CurrentSnapshot));
        }

        public Task<ServerPropertiesMigrationPlan> MigrateAsync(
            string serverName,
            string? minecraftVersion = null,
            CancellationToken cancellationToken = default) =>
            Task.FromResult(new ServerPropertiesMigrationPlan(false, [], CurrentSnapshot.Properties));

        public string GetPropertiesFilePath(string serverName) => $@"C:\Servers\{serverName}\server.properties";
    }
}
