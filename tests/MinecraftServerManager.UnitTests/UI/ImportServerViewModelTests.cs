using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ImportServerViewModelTests
{
    [Fact]
    public async Task ImportAsync_WhenSourcePathEmpty_SetsStatusMessageAndFails()
    {
        var fakeServerManager = new FakeServerManager();
        var vm = new ImportServerViewModel(fakeServerManager, NoOpUiService.Instance);

        await vm.ImportAsync();

        Assert.Contains("請先選取來源目錄", vm.StatusMessage);
        Assert.False(fakeServerManager.ImportCalled);
    }

    [Fact]
    public async Task ImportAsync_WhenValidInput_ExecutesImportSuccessfully()
    {
        var fakeServerManager = new FakeServerManager();
        var vm = new ImportServerViewModel(fakeServerManager, NoOpUiService.Instance)
        {
            SourcePath = "C:\\Servers\\MyServer",
            ServerName = "ImportedServer"
        };

        bool closeRequested = false;
        vm.RequestClose += success => closeRequested = success;

        await vm.ImportAsync();

        Assert.True(fakeServerManager.ImportCalled);
        Assert.Equal("ImportedServer", vm.ImportedServerName);
        Assert.True(closeRequested);
    }

    private sealed class FakeServerManager : IServerManager
    {
        public bool ImportCalled { get; private set; }

        public Task<ServerImportResult> ImportServerAsync(
            string sourceDirectory,
            string targetName,
            ImportTransferMode mode = ImportTransferMode.Copy,
            IProgress<ServerImportProgressReport>? progress = null,
            CancellationToken cancellationToken = default)
        {
            ImportCalled = true;
            var config = new ServerConfig(
                ServerName.Parse(targetName),
                MinecraftVersion.Parse("1.20.4"),
                LoaderKind.Vanilla,
                "",
                2048,
                1024,
                "C:\\Test");
            return Task.FromResult(ServerImportResult.Success(targetName, config));
        }

        public Task<IReadOnlyList<ServerConfig>> GetAllServersAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyList<ServerConfig>>([]);

        public Task<ServerConfig?> GetServerAsync(string name, CancellationToken cancellationToken = default) =>
            Task.FromResult<ServerConfig?>(null);

        public Task<ServerCreationResult> CreateServerAsync(
            ServerCreationPlan plan,
            IProgress<ServerCreationProgressReport>? progress = null,
            CancellationToken cancellationToken = default) =>
            throw new NotImplementedException();

        public Task<ServerOperationResult> DeleteServerAsync(string name, CancellationToken cancellationToken = default) =>
            Task.FromResult(ServerOperationResult.Ok());

        public Task<ServerOperationResult> UpdateServerAsync(ServerConfig config, CancellationToken cancellationToken = default) =>
            Task.FromResult(ServerOperationResult.Ok());

        public Task<ServerScanReport> ScanAndRegisterAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(new ServerScanReport(0, 0, 0, []));
    }
}
