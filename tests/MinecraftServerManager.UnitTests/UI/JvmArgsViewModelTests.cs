using MinecraftServerManager.App.ViewModels;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class JvmArgsViewModelTests
{
    [Theory]
    [InlineData(21, "ZGC")]
    [InlineData(17, "G1GC")]
    public void Constructor_SetsExpectedGcDescription(int javaMajor, string expectedGc)
    {
        var vm = new JvmArgsViewModel(javaMajor: javaMajor, memoryMaxMb: 4096);

        Assert.Contains(expectedGc, vm.DescriptionText);
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
    public void GetFinalJvmArgs_ExcludesOptionsThatExecuteExternalCommands()
    {
        var vm = new JvmArgsViewModel(javaMajor: 21, memoryMaxMb: 4096)
        {
            HasCustomArgs = true,
            CustomArgsText = "-Dfoo=bar -XX:OnError=calc.exe -javaagent:authlib.jar",
        };

        var finalArgs = vm.GetFinalJvmArgs();

        Assert.Contains("-Dfoo=bar", finalArgs);
        Assert.Contains("-javaagent:authlib.jar", finalArgs);
        Assert.DoesNotContain("-XX:OnError=calc.exe", finalArgs);
        Assert.Equal("-XX:OnError=calc.exe", Assert.Single(vm.RejectedArgs));
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
