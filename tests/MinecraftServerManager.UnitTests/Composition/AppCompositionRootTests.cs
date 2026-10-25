using System.Reflection;
using MinecraftServerManager.App;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests.Composition;

public sealed class AppCompositionRootTests : IDisposable
{
    private readonly string _testRoot;

    public AppCompositionRootTests()
    {
        _testRoot = Path.Combine(Path.GetTempPath(), "msm-composition-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_testRoot);
    }

    public void Dispose()
    {
        try
        {
            if (Directory.Exists(_testRoot))
            {
                Directory.Delete(_testRoot, recursive: true);
            }
        }
        catch (Exception ex) { System.Diagnostics.Debug.WriteLine($"測試清理忽略例外: {ex.Message}"); }
    }

    [Fact]
    public async Task ConstructsCompleteObjectGraphSuccessfully()
    {
        await using var root = new AppCompositionRoot(_testRoot);

        Assert.NotNull(root.MainViewModel);
        Assert.NotNull(root.Dependencies);
        Assert.NotNull(root.UiService);
        Assert.NotNull(root.Settings);
        Assert.False(root.IsServerRunning);

        Assert.NotNull(root.Dependencies.ServerManager);
        Assert.NotNull(root.Dependencies.BackupService);
        Assert.NotNull(root.Dependencies.ServerRuntime);
        Assert.NotNull(root.Dependencies.ServerInspector);
        Assert.NotNull(root.Dependencies.LaunchPlanner);
        Assert.NotNull(root.Dependencies.PropertiesStore);
        Assert.NotNull(root.Dependencies.PlayerConfigStore);
        Assert.NotNull(root.Dependencies.DirectorySizeService);
        Assert.NotNull(root.Dependencies.IntegrityService);
        Assert.NotNull(root.Dependencies.DependencyPlanner);
        Assert.NotNull(root.Dependencies.ModListExporter);
    }

    [Fact]
    public async Task EnsuresSingleInstanceOfSharedServicesAcrossConsumers()
    {
        await using var root = new AppCompositionRoot(_testRoot);

        IServerDirectorySizeService sharedSizeService = root.Dependencies.DirectorySizeService;
        IServerInspector inspector = root.Dependencies.ServerInspector;

        Assert.NotNull(sharedSizeService);
        Assert.NotNull(inspector);

        // 驗證 ServerInspector 內部注入的 IServerDirectorySizeService 與組合根共用單一實例相同
        FieldInfo? inspectorField = typeof(Infrastructure.Servers.ServerInspector)
            .GetField("_directorySizeService", BindingFlags.Instance | BindingFlags.NonPublic);
        Assert.NotNull(inspectorField);

        object? inspectorSizeService = inspectorField.GetValue(inspector);
        Assert.Same(sharedSizeService, inspectorSizeService);

        // 驗證 MainViewModel 建立之 ManageServerViewModel 亦共用相同之 DirectorySizeService
        root.MainViewModel.NavigateCommand.Execute("manage");
        ManageServerViewModel manageVm = Assert.IsType<ManageServerViewModel>(root.MainViewModel.CurrentPage);

        FieldInfo? vmField = typeof(ManageServerViewModel)
            .GetField("_directorySizeService", BindingFlags.Instance | BindingFlags.NonPublic);
        Assert.NotNull(vmField);

        object? vmSizeService = vmField.GetValue(manageVm);
        Assert.Same(sharedSizeService, vmSizeService);
    }
}
