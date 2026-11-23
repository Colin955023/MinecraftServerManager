using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ManageJavaViewModelTests : IDisposable
{
    private readonly TempDirectory _tempDirTemp = new("msm_java_vm_test_");
    private readonly string _tempDir;
    private readonly string _dummyJava17;
    private readonly string _dummyJava21;

    public ManageJavaViewModelTests()
    {
        _tempDir = _tempDirTemp.FullName;
        _dummyJava17 = Path.Combine(_tempDir, "java17.exe");
        _dummyJava21 = Path.Combine(_tempDir, "java21.exe");
        File.WriteAllText(_dummyJava17, "fake binary 17");
    }

    public void Dispose() => _tempDirTemp.Dispose();

    [Fact]
    public async Task InstallWithWinget_WhenTargetMajorAlreadyExistsLocally_TriggersGuardAndSkipsInstall()
    {
        var detector = new FixedJavaRuntimeDetector(
        [
            new JavaRuntimeInfo(_dummyJava17, 17, Is64Bit: true, Vendor: "Microsoft OpenJDK")
        ]);
        var installer = new FakeJavaInstaller();

        using var vm = new ManageJavaViewModel(
            javaDetector: detector,
            javaRequirementService: NoOp.Create<IMinecraftJavaRequirementService>(),
            javaInstaller: installer,
            currentJavaPath: string.Empty,
            minecraftVersion: "1.20.1",
            fileSystem: new Infrastructure.FileSystem.LocalFileSystem(),
            uiService: NoOpUiService.Instance)
        {
            SelectedInstallMajorOption = new JavaMajorOption(17, "Java 17")
        };

        await vm.InstallWithWingetAsync();

        // 驗證防護機制生效：因本機已有 Java 17，絕對不觸發 winget 安裝
        Assert.False(installer.InstallInvoked);
        Assert.NotNull(vm.SelectedJava);
        Assert.Equal(17, vm.SelectedJava.MajorVersion);
        Assert.Equal(_dummyJava17, vm.SelectedJava.ExecutablePath);
        Assert.Contains("本機已有可使用的 Java 17", vm.StatusMessage);
    }

    [Fact]
    public async Task InstallWithWinget_WhenTargetMajorDoesNotExistLocally_ProceedsWithWingetInstall()
    {
        var detector = new FixedJavaRuntimeDetector(
        [
            new JavaRuntimeInfo(_dummyJava17, 17, Is64Bit: true, Vendor: "Microsoft OpenJDK")
        ]);
        var installer = new FakeJavaInstaller
        {
            OnInstall = major =>
            {
                File.WriteAllText(_dummyJava21, "fake binary 21");
                detector.Add(new JavaRuntimeInfo(_dummyJava21, major, Is64Bit: true, Vendor: "Microsoft OpenJDK"));
            }
        };

        using var vm = new ManageJavaViewModel(
            javaDetector: detector,
            javaRequirementService: NoOp.Create<IMinecraftJavaRequirementService>(),
            javaInstaller: installer,
            currentJavaPath: string.Empty,
            minecraftVersion: "1.20.5",
            fileSystem: new Infrastructure.FileSystem.LocalFileSystem(),
            uiService: NoOpUiService.Instance)
        {
            SelectedInstallMajorOption = new JavaMajorOption(21, "Java 21")
        };

        await vm.InstallWithWingetAsync();

        // 驗證無既有版本時正常執行 winget 安裝
        Assert.True(installer.InstallInvoked);
        Assert.Equal(21, installer.LastInstalledMajor);
        Assert.NotNull(vm.SelectedJava);
        Assert.Equal(21, vm.SelectedJava.MajorVersion);
        Assert.Equal(_dummyJava21, vm.SelectedJava.ExecutablePath);
        Assert.Contains("成功安裝並選取 Java 21", vm.StatusMessage);
    }

    [Fact]
    public async Task InstallWithWinget_Installing_KeepsBusyUntilFinished()
    {
        var detector = new FixedJavaRuntimeDetector(
        [
            new JavaRuntimeInfo(_dummyJava17, 17, Is64Bit: true, Vendor: "Microsoft OpenJDK")
        ]);
        ManageJavaViewModel? vm = null;
        bool? busyDuringInstall = null;
        var installer = new FakeJavaInstaller
        {
            OnInstall = _ => busyDuringInstall = vm?.IsBusy
        };

        vm = new ManageJavaViewModel(
            javaDetector: detector,
            javaRequirementService: NoOp.Create<IMinecraftJavaRequirementService>(),
            javaInstaller: installer,
            currentJavaPath: string.Empty,
            minecraftVersion: "1.20.5",
            fileSystem: new Infrastructure.FileSystem.LocalFileSystem(),
            uiService: NoOpUiService.Instance)
        {
            SelectedInstallMajorOption = new JavaMajorOption(21, "Java 21")
        };

        await vm.InstallWithWingetAsync();

        // 安裝前先重新載入清單（巢狀忙碌），安裝途中仍須維持忙碌，全部結束後才解除
        Assert.True(busyDuringInstall);
        Assert.False(vm.IsBusy);
    }

    [Fact]
    public void Constructor_RequiredMajor_SelectsItAndShowsSingleVersion()
    {
        using var vm = new ManageJavaViewModel(
            javaDetector: new FixedJavaRuntimeDetector([new JavaRuntimeInfo(_dummyJava17, 17)]),
            javaRequirementService: new FixedJavaRequirementService(17),
            javaInstaller: new FakeJavaInstaller(),
            currentJavaPath: string.Empty,
            minecraftVersion: "1.20.1",
            fileSystem: new Infrastructure.FileSystem.LocalFileSystem(),
            uiService: NoOpUiService.Instance);

        Assert.Equal(17, vm.SelectedInstallMajorOption?.Major);
        Assert.Equal(17, vm.SelectedInstallMajor);
        Assert.Equal("Java 17", vm.RequiredMajorText);
        Assert.Equal("Java 17", Assert.Single(vm.InstalledJavas).DisplayName);
        Assert.True(vm.ApplyCommand.CanExecute(null));
    }

    [Fact]
    public async Task InstallWithWinget_WithoutTargetMajor_DoesNotInstall()
    {
        var installer = new FakeJavaInstaller();
        using var vm = new ManageJavaViewModel(
            javaDetector: new FixedJavaRuntimeDetector([]),
            javaRequirementService: NoOp.Create<IMinecraftJavaRequirementService>(),
            javaInstaller: installer,
            currentJavaPath: string.Empty,
            minecraftVersion: string.Empty,
            fileSystem: new Infrastructure.FileSystem.LocalFileSystem(),
            uiService: NoOpUiService.Instance);

        await vm.InstallWithWingetAsync();

        Assert.False(vm.InstallWithWingetCommand.CanExecute(null));
        Assert.False(installer.InstallInvoked);
        Assert.Equal("請先選擇要安裝的 Java 版本", vm.StatusMessage);
    }

    private sealed class FakeJavaInstaller : IJavaInstaller
    {
        public bool InstallInvoked { get; private set; }
        public int LastInstalledMajor { get; private set; }
        public Action<int>? OnInstall { get; init; }

        public Task<ProcessExitResult> InstallWithWingetAsync(int majorVersion, CancellationToken cancellationToken = default)
        {
            InstallInvoked = true;
            LastInstalledMajor = majorVersion;
            OnInstall?.Invoke(majorVersion);
            return Task.FromResult(new ProcessExitResult(0, false));
        }
    }
}
