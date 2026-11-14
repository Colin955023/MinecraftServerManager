using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.UnitTests.Utilities;

public sealed class ProgressMappingTests
{
    [Theory]
    [InlineData(0, 100, 10)]
    [InlineData(50, 100, 32)]
    [InlineData(100, 100, 55)]
    [InlineData(250, 100, 55)]
    public void Map_ScalesIntoRangeAndClamps(long completed, long total, int expected) =>
        Assert.Equal(expected, ProgressMapping.Map(completed, total, 10, 55));

    [Fact]
    public void Map_WithUnknownTotal_ReturnsFallback()
    {
        Assert.Equal(10, ProgressMapping.Map(5, 0, 10, 55));
        Assert.Equal(35, ProgressMapping.Map(5, 0, 10, 55, unknown: 35));
    }
}
