using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ServersRootViewModelTests : IDisposable
{
    private readonly TempDirectory _temp = new("msm-servers-root-vm-");
    private readonly string _currentRoot;
    private readonly string _pickedRoot;
    private readonly ManualUiService _ui = new();
    private readonly FakeServersRootService _rootService = new();
    private readonly FakeServerRuntimeHost _host = new();
    private readonly SettingsManager _settings;
    private readonly ServerListViewModel _list;
    private readonly ServersRootViewModel _vm;

    public ServersRootViewModelTests()
    {
        _currentRoot = _temp.CreateSubdirectory("current");
        _pickedRoot = _temp.CreateSubdirectory("picked");
        _settings = TestDependencies.CreateSettings(_currentRoot);
        _ui.FolderToPick = _pickedRoot;

        PageServices services = TestDependencies.Create(_temp.FullName, _ui, settings: _settings, runtimeHost: _host);
        _list = new ServerListViewModel(
            services.SettingsManager,
            services.ServerManager,
            services.BackupService,
            services.RuntimeHost,
            services.StopCoordinator,
            services.IntegrityService,
            services.DirectorySizeService,
            services.FileSystem,
            _ui,
            static _ => { });
        _vm = new ServersRootViewModel(_settings, _rootService, _host, services.FileSystem, _list, _ui);
    }

    public void Dispose()
    {
        _list.Dispose();
        _temp.Dispose();
    }

    [Fact]
    public async Task ChangeServersRoot_ServerRunning_BlocksBeforeFolderPick()
    {
        _host.GetFake("Alive").IsRunning = true;

        await _vm.ChangeServersRootCommand.ExecuteAsync(null);

        Assert.Equal(0, _rootService.ValidateCalls);
        Assert.Equal(("目前有伺服器正在執行中，請先停止伺服器後再修改存放路徑。", NotificationType.Warning), _ui.LastNotification);
        Assert.Equal(_currentRoot, _settings.GetServersRoot());
    }

    [Fact]
    public async Task ChangeServersRoot_NoFolderPicked_ReturnsWithoutValidation()
    {
        _ui.FolderToPick = null;

        await _vm.ChangeServersRootCommand.ExecuteAsync(null);

        Assert.Equal(0, _rootService.ValidateCalls);
        Assert.Empty(_ui.Notifications);
        Assert.Equal(_currentRoot, _settings.GetServersRoot());
    }

    [Fact]
    public async Task ChangeServersRoot_TargetIsFile_WarnsAndKeepsSetting()
    {
        _rootService.CheckResult = RelocationPathCheckResult.TargetIsFile;

        await _vm.ChangeServersRootCommand.ExecuteAsync(null);

        Assert.Equal(("所選路徑不是有效的資料夾。", NotificationType.Warning), _ui.LastNotification);
        Assert.Empty(_ui.ChoiceMessages);
        Assert.Equal(_currentRoot, _settings.GetServersRoot());
    }

    [Fact]
    public async Task ChangeServersRoot_SameAsCurrent_ReturnsSilently()
    {
        _rootService.CheckResult = RelocationPathCheckResult.SameAsCurrent;

        await _vm.ChangeServersRootCommand.ExecuteAsync(null);

        Assert.Empty(_ui.Notifications);
        Assert.Empty(_ui.ChoiceMessages);
        Assert.Empty(_rootService.RelocateCalls);
        Assert.Equal(_currentRoot, _settings.GetServersRoot());
    }

    [Fact]
    public async Task ChangeServersRoot_NoStoredContent_UpdatesSettingOnly()
    {
        _rootService.HasContent = false;
        _ui.ChoiceResults.Enqueue(false);

        await _vm.ChangeServersRootCommand.ExecuteAsync(null);

        Assert.Equal(_pickedRoot, _settings.GetServersRoot());
        Assert.Empty(_rootService.RelocateCalls);
        Assert.Single(_ui.ChoiceMessages);
        Assert.Contains("伺服器存放路徑已更新為", _ui.ChoiceMessages[0].Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ChangeServersRoot_SubdirectoryOfCurrent_UpdatesSettingWithoutMigrationPrompt()
    {
        _rootService.CheckResult = RelocationPathCheckResult.SubdirectoryOfCurrent;
        _ui.ChoiceResults.Enqueue(false);

        await _vm.ChangeServersRootCommand.ExecuteAsync(null);

        Assert.Equal(_pickedRoot, _settings.GetServersRoot());
        Assert.Empty(_ui.ConfirmMessages);
        Assert.Empty(_rootService.RelocateCalls);
    }

    [Fact]
    public async Task ChangeServersRoot_MigrationDecisionCancelled_ChangesNothing()
    {
        _ui.YesNoCancelDecision = null;

        await _vm.ChangeServersRootCommand.ExecuteAsync(null);

        Assert.Equal(_currentRoot, _settings.GetServersRoot());
        Assert.Empty(_rootService.RelocateCalls);
        Assert.Empty(_ui.ChoiceMessages);
    }

    [Fact]
    public async Task ChangeServersRoot_MigrationDeclined_UpdatesSettingOnly()
    {
        _ui.YesNoCancelDecision = false;
        _ui.ChoiceResults.Enqueue(false);

        await _vm.ChangeServersRootCommand.ExecuteAsync(null);

        Assert.Equal(_pickedRoot, _settings.GetServersRoot());
        Assert.Empty(_rootService.RelocateCalls);
        Assert.Contains("原路徑資料已保留於原處", _ui.ChoiceMessages[0].Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ChangeServersRoot_MigrationTargetNotEmpty_WarnsWithoutRelocating()
    {
        _rootService.TargetEmpty = false;
        _ui.YesNoCancelDecision = true;

        await _vm.ChangeServersRootCommand.ExecuteAsync(null);

        Assert.Equal(NotificationType.Warning, _ui.LastNotification?.Type);
        Assert.Contains("目標資料夾不是空的", _ui.LastNotification?.Message ?? string.Empty, StringComparison.Ordinal);
        Assert.Empty(_rootService.RelocateCalls);
        Assert.Equal(_currentRoot, _settings.GetServersRoot());
    }

    [Fact]
    public async Task ChangeServersRoot_MigrationSucceeds_RelocatesAndPromptsRestart()
    {
        _ui.YesNoCancelDecision = true;
        _ui.ChoiceResults.Enqueue(true);

        await _vm.ChangeServersRootCommand.ExecuteAsync(null);

        Assert.Equal([(_currentRoot, _pickedRoot)], _rootService.RelocateCalls);
        Assert.Equal(_pickedRoot, _settings.GetServersRoot());
        Assert.True(_ui.RestartCalled);
        Assert.Empty(_ui.ErrorMessages);
    }

    [Fact]
    public async Task ChangeServersRoot_MigrationLeavesLeftovers_ListsThemInRestartPrompt()
    {
        string leftover = Path.Combine(_currentRoot, "locked-server");
        _rootService.Leftovers = [leftover];
        _ui.YesNoCancelDecision = true;
        _ui.ChoiceResults.Enqueue(false);

        await _vm.ChangeServersRootCommand.ExecuteAsync(null);

        Assert.Contains(leftover, _ui.ChoiceMessages[0].Message, StringComparison.Ordinal);
        Assert.False(_ui.RestartCalled);
    }

    [Fact]
    public async Task ChangeServersRoot_MigrationFails_ShowsErrorAndKeepsSetting()
    {
        _rootService.RelocateException = new IOException("磁碟已滿");
        _ui.YesNoCancelDecision = true;

        await _vm.ChangeServersRootCommand.ExecuteAsync(null);

        Assert.Contains("遷移伺服器存放資料失敗", _ui.LastErrorMessage, StringComparison.Ordinal);
        Assert.Contains("磁碟已滿", _ui.LastErrorMessage, StringComparison.Ordinal);
        Assert.Equal(_currentRoot, _settings.GetServersRoot());
        Assert.Empty(_ui.ChoiceMessages);
    }

    private sealed class FakeServersRootService : IServersRootService
    {
        public RelocationPathCheckResult CheckResult { get; set; } = RelocationPathCheckResult.Valid;
        public bool HasContent { get; set; } = true;
        public bool TargetEmpty { get; set; } = true;
        public IReadOnlyList<string> Leftovers { get; set; } = [];
        public Exception? RelocateException { get; set; }
        public int ValidateCalls { get; private set; }
        public List<(string Current, string New)> RelocateCalls { get; } = [];

        public Task<ServersRootCheck> ValidateTargetRootAsync(string? currentRoot, string? newRoot, CancellationToken cancellationToken = default)
        {
            ValidateCalls++;
            return Task.FromResult(new ServersRootCheck(CheckResult, currentRoot!, newRoot!));
        }

        public Task<bool> HasStoredContentAsync(string? currentRoot, CancellationToken cancellationToken = default) =>
            Task.FromResult(HasContent);

        public Task<bool> IsTargetDirectoryEmptyAsync(string? targetRoot, CancellationToken cancellationToken = default) =>
            Task.FromResult(TargetEmpty);

        public Task<IReadOnlyList<string>> RelocateAllContentAsync(
            string currentRoot,
            string newRoot,
            IProgress<(int Percent, string Message)>? progress = null,
            CancellationToken cancellationToken = default)
        {
            RelocateCalls.Add((currentRoot, newRoot));
            if (RelocateException is not null)
            {
                return Task.FromException<IReadOnlyList<string>>(RelocateException);
            }

            return Task.FromResult(Leftovers);
        }
    }
}
