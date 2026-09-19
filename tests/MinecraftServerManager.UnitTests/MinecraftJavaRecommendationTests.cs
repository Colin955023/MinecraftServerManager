using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.ValueObjects;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class MinecraftJavaRecommendationTests
{
    [Theory]
    [InlineData("1.12.2", 8)]
    [InlineData("1.16.5", 8)]
    [InlineData("1.7.10", 8)]
    [InlineData("1.17", 16)]
    [InlineData("1.17.1", 16)]
    [InlineData("1.18", 17)]
    [InlineData("1.18.2", 17)]
    [InlineData("1.19.4", 17)]
    [InlineData("1.20.1", 17)]
    [InlineData("1.20.4", 17)]
    [InlineData("1.20.5", 21)]
    [InlineData("1.20.6", 21)]
    [InlineData("1.21", 21)]
    [InlineData("1.21.1", 21)]
    [InlineData("1.21.4", 21)]
    public void RecommendsCorrectJavaMajorForOfficialReleases(string version, int expectedMajor)
    {
        Assert.Equal(expectedMajor, MinecraftJavaRecommendation.GetRecommendedMajor(version));

        var domainVersion = MinecraftVersion.Parse(version);
        Assert.Equal(expectedMajor, MinecraftJavaRecommendation.GetRecommendedMajor(domainVersion));
    }

    [Theory]
    [InlineData("24w14a", 21)]
    [InlineData("24w33a", 21)]
    [InlineData("23w45a", 17)]
    [InlineData("22w16a", 17)]
    [InlineData("21w37a", 17)]
    [InlineData("21w19a", 16)]
    [InlineData("20w14a", 8)]
    public void RecommendsCorrectJavaMajorForSnapshots(string snapshot, int expectedMajor) => Assert.Equal(expectedMajor, MinecraftJavaRecommendation.GetRecommendedMajor(snapshot));

    [Fact]
    public void HandlesEmptyOrNullWithDefaultMajor()
    {
        Assert.Equal(21, MinecraftJavaRecommendation.GetRecommendedMajor(string.Empty));
        Assert.Equal(21, MinecraftJavaRecommendation.GetRecommendedMajor(null));
    }
}
