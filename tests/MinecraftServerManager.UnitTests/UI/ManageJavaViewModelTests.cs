using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ManageJavaViewModelTests : IDisposable
{
    private readonly string _tempDir;
    private readonly string _dummyJava17;
    private readonly string _dummyJava21;

    public ManageJavaViewModelTests()
    {
        _tempDir = Path.Combine(Path.GetTempPath(), "msm_java_vm_test_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_tempDir);
        _dummyJava17 = Path.Combine(_tempDir, "java17.exe");
        _dummyJava21 = Path.Combine(_tempDir, "java21.exe");
        File.WriteAllText(_dummyJava17, "fake binary 17");
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_tempDir))
            {
                Directory.Delete(_tempDir, recursive: true);
            }
        }
        catch (Exception ex) { System.Diagnostics.Debug.WriteLine($"測試清理忽略例外: {ex.Message}"); }
    }

    [Fact]
    public async Task InstallWithWinget_WhenTargetMajorAlreadyExistsLocally_TriggersGuardAndSkipsInstall()
    {
        var detector = new FakeJavaDetector(
        [
            new JavaRuntimeInfo(_dummyJava17, 17, Is64Bit: true, Vendor: "Microsoft OpenJDK")
        ]);
        var installer = new FakeJavaInstaller();

        var vm = new ManageJavaViewModel(
            javaDetector: detector,
            javaRequirementService: null,
            javaInstaller: installer,
            currentJavaPath: string.Empty,
            minecraftVersion: "1.20.1",
            loaderName: "Paper")
        {
            SelectedInstallMajor = 17
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
        var detector = new FakeJavaDetector(
        [
            new JavaRuntimeInfo(_dummyJava17, 17, Is64Bit: true, Vendor: "Microsoft OpenJDK")
        ]);
        var installer = new FakeJavaInstaller
        {
            OnInstall = major =>
            {
                File.WriteAllText(_dummyJava21, "fake binary 21");
                detector.AddJava(new JavaRuntimeInfo(_dummyJava21, major, Is64Bit: true, Vendor: "Microsoft OpenJDK"));
            }
        };

        var vm = new ManageJavaViewModel(
            javaDetector: detector,
            javaRequirementService: null,
            javaInstaller: installer,
            currentJavaPath: string.Empty,
            minecraftVersion: "1.20.5",
            loaderName: "Paper")
        {
            SelectedInstallMajor = 21
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

    private sealed class FakeJavaDetector(IEnumerable<JavaRuntimeInfo> initial) : IJavaRuntimeDetector
    {
        private readonly List<JavaRuntimeInfo> _list = [.. initial];

        public void AddJava(JavaRuntimeInfo info) => _list.Add(info);

        public Task<IReadOnlyList<JavaRuntimeInfo>> DetectAsync(bool forceRefresh = false, CancellationToken cancellationToken = default) => Task.FromResult<IReadOnlyList<JavaRuntimeInfo>>(_list.AsReadOnly());

        public Task<JavaRuntimeInfo?> FindBestMatchAsync(int targetMajor, CancellationToken cancellationToken = default)
        {
            var match = _list.FirstOrDefault(j => j.MajorVersion == targetMajor);
            return Task.FromResult(match);
        }
    }

    private sealed class FakeJavaInstaller : IJavaInstaller
    {
        public bool InstallInvoked { get; private set; }
        public int LastInstalledMajor { get; private set; }
        public Action<int>? OnInstall { get; init; }

        public Task<bool> IsWingetAvailableAsync(CancellationToken cancellationToken = default) => Task.FromResult(true);

        public Task<ProcessExitResult> InstallWithWingetAsync(int majorVersion, CancellationToken cancellationToken = default)
        {
            InstallInvoked = true;
            LastInstalledMajor = majorVersion;
            OnInstall?.Invoke(majorVersion);
            return Task.FromResult(new ProcessExitResult(0, false));
        }
    }
}
