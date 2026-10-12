using MinecraftServerManager.Infrastructure.Java;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class JavaVersionParserTests
{
    [Theory]
    [InlineData("java version \"1.8.0_402\"", 8)]
    [InlineData("openjdk version \"21.0.4\" 2024-07-16", 21)]
    [InlineData("openjdk version \"17.0.10\" 2024-01-16 LTS", 17)]
    public void ParsesLegacyAndModernJavaVersions(string output, int expectedMajor) => Assert.Equal(expectedMajor, JavaVersionParser.ParseMajor(output));

    [Fact]
    public void ReturnsNullWhenVersionIsMissing() => Assert.Null(JavaVersionParser.ParseMajor("不是 Java 版本輸出"));

    [Theory]
    [InlineData("openjdk version \"21.0.4\" 2024-07-16\nOpenJDK 64-Bit Server VM Microsoft-9825471", 21, true, "Microsoft")]
    [InlineData("openjdk version \"17.0.10\" 2024-01-16\nOpenJDK 64-Bit Server VM Temurin-17.0.10+7", 17, true, "Eclipse Adoptium")]
    [InlineData("openjdk version \"17.0.9\" 2023-10-17 LTS\nOpenJDK 64-Bit Server VM Zulu17.46+19-CA", 17, true, "Azul Zulu")]
    [InlineData("openjdk version \"21.0.2\" 2024-01-16 LTS\nOpenJDK 64-Bit Server VM Corretto-21.0.2.13.1", 21, true, "Amazon Corretto")]
    [InlineData("java version \"1.8.0_351\"\nJava(TM) SE Runtime Environment (build 1.8.0_351-b10)\nJava HotSpot(TM) 64-Bit Server VM", 8, true, "Oracle")]
    [InlineData("openjdk version \"1.8.0_345\"\nOpenJDK Runtime Environment\nOpenJDK 32-Bit Client VM", 8, false, "OpenJDK")]
    public void ParsesDetailedRuntimeInformation(string output, int expectedMajor, bool expected64Bit, string? expectedVendor)
    {
        var details = JavaVersionParser.ParseDetails(output);
        Assert.NotNull(details);
        Assert.Equal(expectedMajor, details.Value.MajorVersion);
        Assert.Equal(expected64Bit, details.Value.Is64Bit);
        Assert.Equal(expectedVendor, details.Value.Vendor);
    }
}

