using MinecraftServerManager.App.ViewModels;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class JvmArgsViewModelTests
{
    [Fact]
    public void Constructor_WhenJava21_SetsZgcDescription()
    {
        var vm = new JvmArgsViewModel(javaMajor: 21, memoryMaxMb: 4096);

        Assert.Contains("ZGC", vm.DescriptionText);
        Assert.NotEmpty(vm.RecommendedArgs);
    }

    [Fact]
    public void Constructor_WhenJava17_SetsG1gcDescription()
    {
        var vm = new JvmArgsViewModel(javaMajor: 17, memoryMaxMb: 4096);

        Assert.Contains("G1GC", vm.DescriptionText);
        Assert.NotEmpty(vm.RecommendedArgs);
    }

    [Fact]
    public void Constructor_WithCustomArgs_ExtractsCustomArgsSeparately()
    {
        var existing = new List<string> { "-Dcustom.flag=true", "-XX:+UseG1GC" };
        var vm = new JvmArgsViewModel(javaMajor: 17, memoryMaxMb: 4096, existingArgs: existing);

        Assert.True(vm.HasCustomArgs);
        Assert.Contains("-Dcustom.flag=true", vm.CustomArgsText);

        var finalArgs = vm.GetFinalJvmArgs();
        Assert.Contains("-Dcustom.flag=true", finalArgs);
    }

    [Fact]
    public void ResetToDefault_RestoresDefaultState()
    {
        var existing = new List<string> { "-Dcustom.flag=true" };
        var vm = new JvmArgsViewModel(javaMajor: 21, memoryMaxMb: 4096, existingArgs: existing);

        Assert.True(vm.HasCustomArgs);

        vm.ResetToDefault();

        Assert.False(vm.HasCustomArgs);
        Assert.Empty(vm.CustomArgsText);
        Assert.All(vm.RecommendedArgs, item => Assert.True(item.IsChecked));
    }
}
