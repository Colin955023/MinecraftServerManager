using MinecraftServerManager.Domain.Mods;
using Xunit;

namespace MinecraftServerManager.UnitTests.Mods;

public sealed class FlexVersionTests
{
    [Theory]
    // 實務案例 1：Fabric API 當前 0.102.0+1.21 vs 線上前版 0.101.2+1.21
    [InlineData("0.102.0+1.21", "0.101.2+1.21", 1)]
    // 實務案例 2：Jade 當前 15.1.5+fabric vs 線上前版 15.1.4+fabric
    [InlineData("15.1.5+fabric", "15.1.4+fabric", 1)]
    // 實務案例 3：FerriteCore 當前 7.0.0 vs 線上 7.0.0-fabric (正式版優於預發布版)
    [InlineData("7.0.0", "7.0.0-fabric", 1)]
    // 實務案例 4：Lithium 當前 0.13.1 vs 線上新版 mc1.21.1-0.15.2-fabric
    [InlineData("mc1.21.1-0.15.2-fabric", "0.13.1", 1)]
    // 忽略建置中繼資料 (+ 號後忽略)
    [InlineData("1.0.0+fabric", "1.0.0+forge", 0)]
    // 標準語意版本
    [InlineData("1.10.0", "1.9.0", 1)]
    [InlineData("2.0.0", "1.99.99", 1)]
    // 前導零消除
    [InlineData("1.01.0", "1.1.0", 0)]
    // v 前綴正規化
    [InlineData("v1.2.3", "1.2.3", 0)]
    // 預發布版本小於正式版
    [InlineData("1.0.0-alpha", "1.0.0", -1)]
    [InlineData("1.0.0-beta.2", "1.0.0-beta.1", 1)]
    public void ComparesVersionsCorrectly(string v1, string v2, int expectedSign)
    {
        int result = FlexVersion.Compare(v1, v2);
        int actualSign = Math.Sign(result);
        Assert.Equal(expectedSign, actualSign);
    }

    [Fact]
    public void ComparesNullAndEmptySafely()
    {
        Assert.Equal(0, FlexVersion.Compare(null, null));
        Assert.Equal(0, FlexVersion.Compare(string.Empty, null));
        Assert.True(FlexVersion.Compare("1.0.0", null) > 0);
        Assert.True(FlexVersion.Compare(null, "1.0.0") < 0);
    }

    [Fact]
    public void FindsMaximumCompatibleVersionFromList()
    {
        string[] versions = ["1.0.0", "1.2.0-beta", "1.1.5", "1.2.0", "1.0.9"];
        string? max = null;
        foreach (string v in versions)
        {
            if (max is null || FlexVersion.Compare(v, max) > 0)
            {
                max = v;
            }
        }

        Assert.Equal("1.2.0", max);
    }
}
