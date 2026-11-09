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
    public async Task ExecuteImportAsync_WhenSourcePathEmpty_SetsStatusMessageAndFails()
    {
        var fakeServerManager = new FakeServerManager();
        var vm = new ImportServerViewModel(fakeServerManager, NoOpUiService.Instance);

        await vm.ExecuteImportAsync();

        Assert.Contains("請先選取來源目錄", vm.StatusMessage);
        Assert.False(fakeServerManager.ImportCalled);
    }

    [Fact]
    public async Task ExecuteImportAsync_WhenServerNameEmpty_SetsStatusMessageAndFails()
    {
        var fakeServerManager = new FakeServerManager();
        var vm = new ImportServerViewModel(fakeServerManager, NoOpUiService.Instance)
        {
            SourcePath = "C:\\Servers\\MyServer",
            ServerName = "   "
        };

        await vm.ExecuteImportAsync();

        Assert.Contains("請輸入匯入後的伺服器名稱", vm.StatusMessage);
        Assert.False(fakeServerManager.ImportCalled);
    }

    [Fact]
    public async Task ExecuteImportAsync_WhenValidInput_ExecutesImportSuccessfully()
    {
        var fakeServerManager = new FakeServerManager();
        var vm = new ImportServerViewModel(fakeServerManager, NoOpUiService.Instance)
        {
            SourcePath = "C:\\Servers\\MyServer",
            ServerName = "ImportedServer"
        };

        bool success = await vm.ExecuteImportAsync();

        Assert.True(success);
        Assert.True(fakeServerManager.ImportCalled);
        Assert.Equal(ImportTransferMode.Copy, fakeServerManager.LastMode);
        Assert.Equal("ImportedServer", vm.ImportedServerName);
    }

    [Fact]
    public async Task ExecuteImportAsync_WhenMoveModeSelected_PassesMoveModeToServerManager()
    {
        var fakeServerManager = new FakeServerManager();
        var vm = new ImportServerViewModel(fakeServerManager, NoOpUiService.Instance)
        {
            SourcePath = "C:\\Servers\\MyServer",
            ServerName = "MovedServer",
            IsMoveMode = true,
        };

        Assert.False(vm.IsCopyMode);
        Assert.True(vm.IsMoveMode);
        Assert.Equal(ImportTransferMode.Move, vm.TransferMode);

        await vm.ExecuteImportAsync();

        Assert.True(fakeServerManager.ImportCalled);
        Assert.Equal(ImportTransferMode.Move, fakeServerManager.LastMode);
    }

    [Fact]
    public async Task ExecuteImportAsync_WhenFailedResult_SetsStatusAndShowsWarning()
    {
        var fakeServerManager = new FakeServerManager
        {
            ResultToReturn = ServerImportResult.Failed("ImportedServer", "目錄格式不正確")
        };
        var vm = new ImportServerViewModel(fakeServerManager, NoOpUiService.Instance)
        {
            SourcePath = "C:\\Servers\\MyServer",
            ServerName = "ImportedServer"
        };

        bool success = await vm.ExecuteImportAsync();

        Assert.False(success);
        Assert.Contains("目錄格式不正確", vm.StatusMessage);
    }

    [Fact]
    public async Task ExecuteImportAsync_WhenOperationCanceled_SetsCanceledStatus()
    {
        var fakeServerManager = new FakeServerManager
        {
            ThrowOnImport = new OperationCanceledException()
        };
        var vm = new ImportServerViewModel(fakeServerManager, NoOpUiService.Instance)
        {
            SourcePath = "C:\\Servers\\MyServer",
            ServerName = "ImportedServer"
        };

        bool success = await vm.ExecuteImportAsync();

        Assert.False(success);
        Assert.Contains("已取消", vm.StatusMessage);
    }

    private sealed class FakeServerManager : IServerManager
    {
        public bool ImportCalled { get; private set; }
        public ImportTransferMode LastMode { get; private set; }
        public ServerImportResult? ResultToReturn { get; set; }
        public Exception? ThrowOnImport { get; set; }

        public Task<ServerImportResult> ImportServerAsync(
            string sourceDirectory,
            string targetName,
            ImportTransferMode mode = ImportTransferMode.Copy,
            IProgress<ServerImportProgressReport>? progress = null,
            CancellationToken cancellationToken = default)
        {
            ImportCalled = true;
            LastMode = mode;

            if (ThrowOnImport is not null)
            {
                throw ThrowOnImport;
            }

            if (ResultToReturn is not null)
            {
                return Task.FromResult(ResultToReturn);
            }

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
