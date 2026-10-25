using MinecraftServerManager.App.ViewModels;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ManageServerViewModelTests
{
    private static ManageServerViewModel CreateTestViewModel(Core.Ports.IExternalLauncher? launcher = null)
    {
        string root = Path.Combine(Path.GetTempPath(), "msm-manage-test-" + Guid.NewGuid().ToString("N"));
        var settings = new Infrastructure.Settings.SettingsManager(root);
        var dirSize = new Infrastructure.Servers.ServerDirectorySizeService();
        var inspector = new Infrastructure.Servers.ServerInspector(dirSize);
        var manager = new Infrastructure.Servers.ServerManager(root, inspector);
        var backupService = new Infrastructure.Servers.ServerBackupService(root);
        var processRunner = new Infrastructure.Process.ProcessRunner();
        var runtime = new Infrastructure.Servers.ServerRuntime(processRunner);
        var launchPlanner = new Infrastructure.Servers.ServerLaunchPlanner();
        var propertiesStore = new Infrastructure.Servers.ServerPropertiesStore(root);
        var playerConfigStore = new Infrastructure.Servers.ServerPlayerConfigStore();
        var integrityService = new Infrastructure.Servers.ServerIntegrityService();

        return new ManageServerViewModel(
            settingsManager: settings,
            serverManager: manager,
            backupService: backupService,
            serverRuntime: runtime,
            serverInspector: inspector,
            launchPlanner: launchPlanner,
            propertiesStore: propertiesStore,
            playerConfigStore: playerConfigStore,
            directorySizeService: dirSize,
            integrityService: integrityService,
            launcher: launcher);
    }

    [Fact]
    public async Task SelectedServerMemory_ShouldUpdateWhenRowMemoryChangesAndRefreshed()
    {
        string root = Path.Combine(Path.GetTempPath(), "msm-manage-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var settings = new Infrastructure.Settings.SettingsManager(root);
            var dirSize = new Infrastructure.Servers.ServerDirectorySizeService();
            var inspector = new Infrastructure.Servers.ServerInspector(dirSize);
            var manager = new Infrastructure.Servers.ServerManager(root, inspector);
            var backupService = new Infrastructure.Servers.ServerBackupService(root);
            var processRunner = new Infrastructure.Process.ProcessRunner();
            var runtime = new Infrastructure.Servers.ServerRuntime(processRunner);
            var launchPlanner = new Infrastructure.Servers.ServerLaunchPlanner();
            var propertiesStore = new Infrastructure.Servers.ServerPropertiesStore(root);
            var playerConfigStore = new Infrastructure.Servers.ServerPlayerConfigStore();
            var integrityService = new Infrastructure.Servers.ServerIntegrityService();

            var vm = new ManageServerViewModel(
                settingsManager: settings,
                serverManager: manager,
                backupService: backupService,
                serverRuntime: runtime,
                serverInspector: inspector,
                launchPlanner: launchPlanner,
                propertiesStore: propertiesStore,
                playerConfigStore: playerConfigStore,
                directorySizeService: dirSize,
                integrityService: integrityService);

            var plan = Domain.Servers.ServerCreationPlan.Create(
                name: Domain.ValueObjects.ServerName.Parse("MemoryServer"),
                minecraftVersion: Domain.ValueObjects.MinecraftVersion.Parse("1.20.4"),
                loaderType: Domain.Servers.LoaderKind.Vanilla,
                memoryMaxMb: 2048,
                memoryMinMb: 1024);

            var created = await manager.CreateServerAsync(plan);
            Assert.True(created.Completed);

            await vm.RefreshServers();
            var server = vm.Servers.FirstOrDefault(s => s.Name == "MemoryServer");
            Assert.NotNull(server);
            vm.SelectedServer = server;

            Assert.Equal("1024 MB ~ 2048 MB", vm.SelectedServerMemory);

            // 模擬伺服器設定修改為 10G ~ 20G
            var updatedConfig = new Domain.Servers.ServerConfig(
                name: Domain.ValueObjects.ServerName.Parse(server.Name),
                minecraftVersion: Domain.ValueObjects.MinecraftVersion.Parse(server.Version),
                loaderType: Domain.Servers.LoaderKind.Vanilla,
                loaderVersion: "",
                memoryMaxMb: 20480,
                memoryMinMb: 10240,
                path: server.Path);
            await manager.UpdateServerAsync(updatedConfig);

            await vm.RefreshAndSelectServerAsync("MemoryServer");

            Assert.Equal("10240 MB ~ 20480 MB", vm.SelectedServerMemory);
            Assert.Contains("10240 MB ~ 20480 MB", vm.SelectedServerInfo);
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    [Fact]
    public void SelectionShouldUpdateActionState()
    {
        var vm = CreateTestViewModel();
        Assert.False(vm.HasSelectedServer);
        Assert.False(vm.StartServerCommand.CanExecute(null));
        Assert.False(vm.StopServerCommand.CanExecute(null));
        Assert.False(vm.MonitorServerCommand.CanExecute(null));
        Assert.False(vm.ConfigureServerCommand.CanExecute(null));
        Assert.False(vm.OpenServerFolderCommand.CanExecute(null));
        Assert.False(vm.BackupServerCommand.CanExecute(null));
        Assert.False(vm.RestoreBackupCommand.CanExecute(null));
        Assert.False(vm.DeleteServerCommand.CanExecute(null));

        var server = new ServerRowItem
        {
            Name = "Survival",
            Version = "1.21.4",
            Loader = "Vanilla",
            Status = "已停止",
            Path = @"C:\servers\Survival"
        };
        vm.SelectedServer = server;

        Assert.True(vm.HasSelectedServer);
        Assert.Contains("Survival", vm.SelectedServerInfo);
        Assert.True(vm.StartServerCommand.CanExecute(null));
        Assert.True(vm.StopServerCommand.CanExecute(null));
        Assert.True(vm.MonitorServerCommand.CanExecute(null));
        Assert.True(vm.ConfigureServerCommand.CanExecute(null));
        Assert.True(vm.OpenServerFolderCommand.CanExecute(null));
        Assert.True(vm.BackupServerCommand.CanExecute(null));
        Assert.True(vm.RestoreBackupCommand.CanExecute(null));
        Assert.True(vm.DeleteServerCommand.CanExecute(null));

        vm.SelectedServer = null;
        Assert.False(vm.HasSelectedServer);
        Assert.False(vm.StartServerCommand.CanExecute(null));
        Assert.False(vm.DeleteServerCommand.CanExecute(null));
    }

    [Fact]
    public async Task OpenBackupFolderWithoutBackupPathShouldNotCreateOrOpenServerInternalBackups()
    {
        string tempDir = Path.Combine(Path.GetTempPath(), "msm-backup-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(tempDir);
        try
        {
            var fakeLauncher = new FakeExternalLauncher();
            var vm = CreateTestViewModel(launcher: fakeLauncher);
            vm.SelectedServer = new ServerRowItem
            {
                Name = "TestServer",
                Version = "1.21.4",
                Loader = "Paper",
                Status = "已停止",
                Path = tempDir,
                BackupPath = string.Empty
            };

            // 執行 OpenBackupFolder，未設定 BackupPath 且在測試中預設不會確認開啟
            await vm.OpenBackupFolderCommand.ExecuteAsync(null);

            string internalBackupDir = Path.Combine(tempDir, "backups");
            Assert.False(Directory.Exists(internalBackupDir));
            Assert.DoesNotContain(internalBackupDir, fakeLauncher.OpenedFolders);
        }
        finally
        {
            try { Directory.Delete(tempDir, true); } catch (Exception ex) { System.Diagnostics.Debug.WriteLine($"測試清理忽略例外: {ex.Message}"); }
        }
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
        vm.SelectedServer = server;

        Assert.True(vm.HasSelectedServer);
        Assert.False(vm.StartServerCommand.CanExecute(null));
        Assert.False(vm.MonitorServerCommand.CanExecute(null));
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
        vm.SelectedServer = server;

        Assert.Equal("4096 MB", vm.SelectedServerMemory);
        Assert.Contains("記憶體配置：4096 MB", vm.SelectedServerInfo);
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
        vm.SelectedServer = server;

        Assert.Equal("2048 MB ~ 4096 MB", vm.SelectedServerMemory);
        Assert.Contains("記憶體配置：2048 MB ~ 4096 MB", vm.SelectedServerInfo);
    }

    private sealed class FakeExternalLauncher : Core.Ports.IExternalLauncher
    {
        public List<string> OpenedFolders { get; } = [];
        public bool OpenFolder(string folderPath, bool isTrusted = false)
        {
            OpenedFolders.Add(folderPath);
            return true;
        }
        public bool ShowInFolder(string filePath, bool isTrusted = false) => !string.IsNullOrEmpty(filePath);
        public bool OpenFile(string filePath, bool isTrusted = false) => !string.IsNullOrEmpty(filePath);
        public bool OpenUrl(string url, bool isTrusted = false) => !string.IsNullOrEmpty(url);
    }
}
