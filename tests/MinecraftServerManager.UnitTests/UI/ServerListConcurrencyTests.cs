using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ServerListConcurrencyTests : IDisposable
{
    private readonly TempDirectory _root = new("msm-server-list-concurrency-");

    public void Dispose() => _root.Dispose();

    [Fact]
    public async Task RefreshServersAsync_LimitsSnapshotConcurrencyAndPreservesOrder()
    {
        var settings = TestDependencies.CreateSettings(_root.FullName);
        var serverManager = TestServerManagers.Create(_root.FullName);
        string[] serverNames = Enumerable.Range(0, 12).Select(static index => $"server-{index:D2}").ToArray();
        foreach (string name in serverNames)
        {
            await serverManager.CreateVanillaServerAsync(name, cancellationToken: TestContext.Current.CancellationToken);
        }
        string[] expectedOrder = (await serverManager.GetAllServersAsync(TestContext.Current.CancellationToken))
            .Select(static server => server.Name.Value)
            .ToArray();

        var backupService = new BlockingBackupSummaryService();
        var runtimeHost = new FakeServerRuntimeHost();
        var ui = NoOpUiService.Instance;
        using var viewModel = new ServerListViewModel(
            settings,
            serverManager,
            backupService,
            runtimeHost,
            new ServerStopCoordinator(ui, runtimeHost),
            new ServerIntegrityService(),
            new ServerDirectorySizeService(TimeSpan.FromSeconds(60), TimeProvider.System),
            new LocalFileSystem(),
            ui,
            static _ => { });

        Task refreshTask = viewModel.RefreshServersAsync();
        await backupService.WaitForFourAsync(TestContext.Current.CancellationToken);
        backupService.Release();
        await refreshTask;

        Assert.Equal(4, backupService.MaximumConcurrency);
        Assert.Equal(expectedOrder, viewModel.Servers.Select(static server => server.Name));
    }

    private sealed class BlockingBackupSummaryService : IServerBackupService
    {
        private readonly TaskCompletionSource _fourStarted = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private readonly TaskCompletionSource _release = new(TaskCreationOptions.RunContinuationsAsynchronously);
        private int _active;
        private int _maximumConcurrency;

        public int MaximumConcurrency => Volatile.Read(ref _maximumConcurrency);

        public async Task<ServerBackupSummary> GetBackupSummaryAsync(
            string serverName,
            string? backupDirectory,
            CancellationToken cancellationToken = default)
        {
            int active = Interlocked.Increment(ref _active);
            UpdateMaximum(active);
            if (active == 4)
            {
                _fourStarted.TrySetResult();
            }

            try
            {
                await _release.Task.WaitAsync(cancellationToken).ConfigureAwait(false);
                return new ServerBackupSummary(ServerBackupSummaryStatus.NotConfigured);
            }
            finally
            {
                Interlocked.Decrement(ref _active);
            }
        }

        public Task WaitForFourAsync(CancellationToken cancellationToken) => _fourStarted.Task.WaitAsync(cancellationToken);

        public void Release() => _release.TrySetResult();

        private void UpdateMaximum(int value)
        {
            int observed;
            do
            {
                observed = Volatile.Read(ref _maximumConcurrency);
                if (value <= observed)
                {
                    return;
                }
            }
            while (Interlocked.CompareExchange(ref _maximumConcurrency, value, observed) != observed);
        }

        public Task<IReadOnlyList<ServerBackupInfo>> ListBackupsAsync(string serverName, string? backupDirectory = null, CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyList<ServerBackupInfo>>([]);

        public Task<ServerBackupInfo> CreateBackupAsync(string serverName, string? destinationPath = null, string? comment = null, IProgress<ServerBackupProgressReport>? progress = null, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<bool> RestoreBackupAsync(string serverName, string backupFileName, string? backupDirectory = null, IProgress<ServerBackupProgressReport>? progress = null, CancellationToken cancellationToken = default) =>
            Task.FromResult(false);

        public Task<bool> DeleteBackupAsync(string serverName, string backupFileName, string? backupDirectory = null, CancellationToken cancellationToken = default) =>
            Task.FromResult(false);

        public Task<string?> ValidateBackupDestinationAsync(string destinationPath, CancellationToken cancellationToken = default) =>
            Task.FromResult<string?>(null);

        public Task<string> PrepareBackupFilePathAsync(string serverName, string destinationDirectory, CancellationToken cancellationToken = default) =>
            Task.FromResult(string.Empty);
    }
}
