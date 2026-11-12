using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ManageServerViewModelTests : IDisposable
{
    private readonly List<TempDirectory> _tempDirectories = [];

    public void Dispose()
    {
        foreach (TempDirectory directory in _tempDirectories)
        {
            directory.Dispose();
        }
    }

    private TempDirectory CreateTemp(string prefix)
    {
        var directory = new TempDirectory(prefix);
        _tempDirectories.Add(directory);
        return directory;
    }

    private ManageServerViewModel CreateTestViewModel(
        Core.Ports.IExternalLauncher? launcher = null,
        IUiService? uiService = null,
        string? customRoot = null)
    {
        string root = customRoot ?? CreateTemp("msm-manage-test-").FullName;
        var settings = new Infrastructure.Settings.SettingsManager(root);
        settings.SetExactServersRoot(root);
        var deps = TestDependencies.Create(root, uiService, launcher, settings);
        return TestDependencies.CreateManagePage(deps);
    }

    [Fact]
    public async Task SelectedServerMemory_ShouldUpdateWhenRowMemoryChangesAndRefreshed()
    {
        string root = CreateTemp("msm-manage-test-").FullName;
        var settings = new Infrastructure.Settings.SettingsManager(root);
        settings.SetExactServersRoot(root);
        var deps = TestDependencies.Create(root, settings: settings);
        var manager = deps.ServerManager;
        var vm = TestDependencies.CreateManagePage(deps);

        var plan = Domain.Servers.ServerCreationPlan.Create(
            name: Domain.ValueObjects.ServerName.Parse("MemoryServer"),
            minecraftVersion: Domain.ValueObjects.MinecraftVersion.Parse("1.20.4"),
            loaderType: Domain.Servers.LoaderKind.Vanilla,
            memoryMaxMb: 2048,
            memoryMinMb: 1024);

        var created = await manager.CreateServerAsync(plan);
        Assert.True(created.Completed);

        await vm.List.RefreshServers();
        var server = vm.List.Servers.FirstOrDefault(s => s.Name == "MemoryServer");
        Assert.NotNull(server);
        vm.List.SelectedServer = server;

        Assert.Equal("1024 MB ~ 2048 MB", vm.List.SelectedServerMemory);

        var updatedConfig = new Domain.Servers.ServerConfig(
            name: Domain.ValueObjects.ServerName.Parse(server.Name),
            minecraftVersion: Domain.ValueObjects.MinecraftVersion.Parse(server.Version),
            loaderType: Domain.Servers.LoaderKind.Vanilla,
            loaderVersion: "",
            memoryMaxMb: 20480,
            memoryMinMb: 10240,
            path: server.Path);
        await manager.UpdateServerAsync(updatedConfig);

        await vm.List.RefreshAndSelectServerAsync("MemoryServer");

        Assert.Equal("10240 MB ~ 20480 MB", vm.List.SelectedServerMemory);
    }

    [Fact]
    public async Task ChangeServersRoot_WhenSubdirectorySelected_ChangesSettingWithoutMigration()
    {
        string root = CreateTemp("msm-change-root-").FullName;
        string subDir = Path.Combine(root, "SubFolder");
        Directory.CreateDirectory(subDir);
        var ui = new ManualUiService { FolderToPick = subDir };
        var vm = CreateTestViewModel(uiService: ui, customRoot: root);

        await vm.ServersRoot.ChangeServersRootCommand.ExecuteAsync(null);

        Assert.Null(ui.LastErrorMessage);
        Assert.True(ui.RestartCalled);
        Assert.Equal(Path.Combine(subDir, "servers"), vm.List.DetectPath);
    }

    [Fact]
    public async Task ChangeServersRoot_WhenHasContentAndUserChoosesMigrate_RelocatesAndRestarts()
    {
        string oldRoot = CreateTemp("msm-old-root-").FullName;
        string newRoot = Path.Combine(CreateTemp("msm-new-root-").FullName, "target");
        string serverDir = Path.Combine(oldRoot, "MyServer");
        Directory.CreateDirectory(serverDir);
        await File.WriteAllTextAsync(Path.Combine(serverDir, "server.jar"), "jar");

        var ui = new ManualUiService
        {
            FolderToPick = newRoot,
            YesNoCancelDecision = true,
        };
        var vm = CreateTestViewModel(uiService: ui, customRoot: oldRoot);

        await vm.ServersRoot.ChangeServersRootCommand.ExecuteAsync(null);

        Assert.True(ui.RestartCalled);
        Assert.Equal(Path.Combine(newRoot, "servers"), vm.List.DetectPath);
        Assert.True(File.Exists(Path.Combine(newRoot, "servers", "MyServer", "server.jar")));
    }

    [Fact]
    public async Task ChangeServersRoot_WhenRestartFails_ReportsRestartFailureNotMigrationFailure()
    {
        string oldRoot = CreateTemp("msm-old-root-").FullName;
        string newRoot = Path.Combine(CreateTemp("msm-new-root-").FullName, "target");
        string serverDir = Path.Combine(oldRoot, "MyServer");
        Directory.CreateDirectory(serverDir);
        await File.WriteAllTextAsync(Path.Combine(serverDir, "server.jar"), "jar");

        var ui = new ManualUiService
        {
            FolderToPick = newRoot,
            YesNoCancelDecision = true,
            RestartException = new IOException("找不到工作目錄"),
        };
        var vm = CreateTestViewModel(uiService: ui, customRoot: oldRoot);

        await vm.ServersRoot.ChangeServersRootCommand.ExecuteAsync(null);

        Assert.NotNull(ui.LastErrorMessage);
        Assert.Contains("手動重新開啟", ui.LastErrorMessage, StringComparison.Ordinal);
        Assert.DoesNotContain("已自動復原", ui.LastErrorMessage, StringComparison.Ordinal);
        Assert.True(File.Exists(Path.Combine(newRoot, "servers", "MyServer", "server.jar")));
    }

    [Fact]
    public void SelectionShouldUpdateActionState()
    {
        var vm = CreateTestViewModel();
        Assert.False(vm.List.HasSelectedServer);
        Assert.False(vm.Lifecycle.StartServerCommand.CanExecute(null));
        Assert.False(vm.Lifecycle.StopServerCommand.CanExecute(null));
        Assert.False(vm.Lifecycle.MonitorServerCommand.CanExecute(null));
        Assert.False(vm.ConfigureServerCommand.CanExecute(null));
        Assert.False(vm.OpenServerFolderCommand.CanExecute(null));
        Assert.False(vm.Backup.BackupServerCommand.CanExecute(null));
        Assert.False(vm.Backup.RestoreBackupCommand.CanExecute(null));
        Assert.False(vm.DeleteServerCommand.CanExecute(null));

        var server = new ServerRowItem
        {
            Name = "Survival",
            Version = "1.21.4",
            Loader = "Vanilla",
            Status = "已停止",
            Path = @"C:\servers\Survival"
        };
        vm.List.SelectedServer = server;

        Assert.True(vm.List.HasSelectedServer);
        Assert.Equal("Survival", vm.List.SelectedServer?.Name);
        Assert.True(vm.Lifecycle.StartServerCommand.CanExecute(null));
        Assert.True(vm.Lifecycle.StopServerCommand.CanExecute(null));
        Assert.True(vm.Lifecycle.MonitorServerCommand.CanExecute(null));
        Assert.True(vm.ConfigureServerCommand.CanExecute(null));
        Assert.True(vm.OpenServerFolderCommand.CanExecute(null));
        Assert.True(vm.Backup.BackupServerCommand.CanExecute(null));
        Assert.True(vm.Backup.RestoreBackupCommand.CanExecute(null));
        Assert.True(vm.DeleteServerCommand.CanExecute(null));

        vm.List.SelectedServer = null;
        Assert.False(vm.List.HasSelectedServer);
        Assert.False(vm.Lifecycle.StartServerCommand.CanExecute(null));
        Assert.False(vm.DeleteServerCommand.CanExecute(null));
    }

    [Fact]
    public async Task OpenBackupFolderWithoutBackupPathShouldNotCreateOrOpenServerInternalBackups()
    {
        string tempDir = CreateTemp("msm-backup-test-").FullName;
        var fakeLauncher = new RecordingLauncher();
        var vm = CreateTestViewModel(launcher: fakeLauncher);
        vm.List.SelectedServer = new ServerRowItem
        {
            Name = "TestServer",
            Version = "1.21.4",
            Loader = "Paper",
            Status = "已停止",
            Path = tempDir,
            BackupPath = string.Empty
        };

        await vm.Backup.OpenBackupFolderCommand.ExecuteAsync(null);

        string internalBackupDir = Path.Combine(tempDir, "backups");
        Assert.False(Directory.Exists(internalBackupDir));
        Assert.DoesNotContain(internalBackupDir, fakeLauncher.OpenedFolders);
    }

    [Fact]
    public void MissingImportantFilesShouldDisableStartAndDisplayDetail()
    {
        var vm = CreateTestViewModel();
        var server = new ServerRowItem
        {
            Name = "BrokenServer",
            Version = "1.21.4",
            Loader = "NeoForge",
            Status = "缺少重要檔案：win_args.txt",
            HasMissingFiles = true,
            Path = @"C:\servers\BrokenServer"
        };
        vm.List.SelectedServer = server;

        Assert.True(vm.List.HasSelectedServer);
        Assert.False(vm.Lifecycle.StartServerCommand.CanExecute(null));
        Assert.False(vm.Lifecycle.MonitorServerCommand.CanExecute(null));
        Assert.Contains("win_args.txt", server.Status);
    }

    [Fact]
    public void SelectedServerMemory_WhenMinMemoryNotSet_ShouldOnlyDisplayMaxMemory()
    {
        var vm = CreateTestViewModel();
        var server = new ServerRowItem
        {
            Name = "ServerNoMin",
            MemoryMaxMb = 4096,
            MemoryMinMb = null,
        };
        vm.List.SelectedServer = server;

        Assert.Equal("4096 MB", vm.List.SelectedServerMemory);
    }

    [Fact]
    public void SelectedServerMemory_WhenMinMemorySet_ShouldDisplayRange()
    {
        var vm = CreateTestViewModel();
        var server = new ServerRowItem
        {
            Name = "ServerWithMin",
            MemoryMaxMb = 4096,
            MemoryMinMb = 2048,
        };
        vm.List.SelectedServer = server;

        Assert.Equal("2048 MB ~ 4096 MB", vm.List.SelectedServerMemory);
    }
}
