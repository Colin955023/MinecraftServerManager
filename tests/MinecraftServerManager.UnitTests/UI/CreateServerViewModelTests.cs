using MinecraftServerManager.App.ViewModels;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class CreateServerViewModelTests
{
    [Fact]
    public void MemoryValidationShouldCatchInvalidValues()
    {
        var vm = new CreateServerViewModel(systemMemoryMb: 16384)
        {
            MinMemoryMb = "4096",
            MaxMemoryMb = "2048"
        };
        Assert.True(vm.IsMemoryError);
        Assert.Contains("最小記憶體必須小於最大記憶體", vm.MemoryWarningText);

        vm.MinMemoryMb = "1024";
        vm.MaxMemoryMb = "32768";
        Assert.True(vm.IsMemoryError);
        Assert.Contains("超過系統總記憶體", vm.MemoryWarningText);

        vm.MinMemoryMb = "1024";
        vm.MaxMemoryMb = "12288";
        Assert.False(vm.IsMemoryError);
        Assert.True(vm.IsMemoryWarning);
        Assert.Contains("超過系統記憶體的一半", vm.MemoryWarningText);

        vm.MinMemoryMb = "1024";
        vm.MaxMemoryMb = "4096";
        Assert.False(vm.IsMemoryError);
        Assert.False(vm.IsMemoryWarning);
        Assert.Empty(vm.MemoryWarningText);
    }

    [Fact]
    public void ResetFormShouldRestoreDefaults()
    {
        var vm = new CreateServerViewModel
        {
            ServerName = "自訂伺服器",
            SelectedLoader = "Fabric",
            MaxMemoryMb = "8192"
        };

        vm.ResetFormCommand.Execute(null);

        Assert.Equal($"Vanilla {vm.SelectedMinecraftVersion}", vm.ServerName);
        Assert.Equal("Vanilla", vm.SelectedLoader);
        Assert.Equal("2048", vm.MaxMemoryMb);
    }
}

public sealed class CreateServerSynchronizationTests
{
    [Fact]
    public void ServerNameShouldSynchronizeWithLoaderAndVersion()
    {
        var vm = new CreateServerViewModel
        {
            // 初始切換 loader
            SelectedLoader = "Fabric"
        };
        Assert.Equal("Fabric 1.21.4", vm.ServerName);

        // 切換版本
        vm.SelectedMinecraftVersion = "1.20.1";
        Assert.Equal("Fabric 1.20.1", vm.ServerName);

        // 帶後綴切換
        vm.ServerName = "Fabric 1.20.1 - 冒險伺服器";
        vm.SelectedLoader = "Forge";
        Assert.Equal("Forge 1.20.1 - 冒險伺服器", vm.ServerName);

        // 完全自訂名稱不覆蓋
        vm.ServerName = "SuperServer";
        vm.SelectedLoader = "NeoForge";
        Assert.Equal("SuperServer", vm.ServerName);
    }

    [Fact]
    public void IsNotDetectingJavaShouldInvertIsDetectingJava()
    {
        var vm = new CreateServerViewModel();
        Assert.True(vm.IsNotDetectingJava);

        vm.IsDetectingJava = true;
        Assert.False(vm.IsNotDetectingJava);

        vm.IsDetectingJava = false;
        Assert.True(vm.IsNotDetectingJava);
    }
}
