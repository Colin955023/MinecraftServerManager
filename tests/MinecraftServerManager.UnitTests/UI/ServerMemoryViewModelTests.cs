using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.UnitTests.UI;

public sealed class ServerMemoryViewModelTests
{
    private static ServerConfig CreateSampleConfig(int maxMb = 2048, int? minMb = 1024) =>
        TestServerConfigs.Create("TestServer", minecraftVersion: "1.20.4", memoryMaxMb: maxMb, memoryMinMb: minMb, path: "C:\\Servers\\TestServer");

    [Fact]
    public void SystemMemoryText_FractionalGigabytes_Rounds()
    {
        var vm = new ServerMemoryViewModel(CreateSampleConfig(), static (_, _) => Task.FromResult(true), NoOpUiService.Instance, systemMemoryMb: 16303);

        Assert.Contains("（16 GB）", vm.SystemMemoryText, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("-100", "1024", "大於 0 的整數")]
    [InlineData("2048", "4096", "最小記憶體不可大於最大記憶體")]
    public async Task SaveAsync_WhenInvalid_SetsErrorMessageAndDoesNotInvokeCallback(string maxMb, string minMb, string expectedError)
    {
        bool callbackInvoked = false;
        var config = CreateSampleConfig();
        var vm = new ServerMemoryViewModel(
            config,
            (max, min) =>
            {
                callbackInvoked = true;
                return Task.FromResult(true);
            },
            systemMemoryMb: 16384,
            uiService: NoOpUiService.Instance)
        {
            MaxMemoryMb = maxMb,
            MinMemoryMb = minMb
        };

        Assert.False(await vm.SaveAsync());

        Assert.False(callbackInvoked);
        Assert.Contains(expectedError, vm.ErrorMessage);
    }

    [Fact]
    public async Task SaveAsync_WhenValid_InvokesCallbackAndCloses()
    {
        int savedMax = 0;
        int? savedMin = null;

        var config = CreateSampleConfig();
        var vm = new ServerMemoryViewModel(
            config,
            (max, min) =>
            {
                savedMax = max;
                savedMin = min;
                return Task.FromResult(true);
            },
            systemMemoryMb: 16384,
            uiService: NoOpUiService.Instance)
        {
            MaxMemoryMb = "4096",
            MinMemoryMb = "2048"
        };

        bool closed = await vm.SaveAsync();

        Assert.Equal(4096, savedMax);
        Assert.Equal(2048, savedMin);
        Assert.True(closed);
        Assert.Empty(vm.ErrorMessage);
    }

    [Fact]
    public async Task SaveAsync_WhenCallbackFails_KeepsDialogOpenWithErrorMessage()
    {
        var vm = new ServerMemoryViewModel(
            CreateSampleConfig(),
            static (_, _) => Task.FromResult(false),
            systemMemoryMb: 16384,
            uiService: NoOpUiService.Instance)
        {
            MaxMemoryMb = "4096",
        };

        Assert.False(await vm.SaveAsync());
        Assert.Contains("儲存記憶體設定失敗", vm.ErrorMessage);
    }
}
