using MinecraftServerManager.Core.Utilities;

namespace MinecraftServerManager.UnitTests.Utilities;

public sealed class JvmOptionPolicyTests
{
    [Theory]
    [InlineData("@args.txt")]
    [InlineData("\"@args.txt\"")]
    [InlineData("-XX:VMOptionsFile=evil.txt")]
    [InlineData("-XX:OptionsFile=evil.txt")]
    [InlineData("-XX:Flags=.hotspotrc")]
    [InlineData("-javaagent:authlib.jar")]
    [InlineData("-Xrunjdwp:transport=dt_socket")]
    [InlineData("-XX:\"VMOptions\"File=evil.txt")]
    [InlineData("-java'agent':authlib.jar")]
    [InlineData("\"-Dfoo=bar")]
    [InlineData("-Dfoo='bar")]
    public void IsCommandExecutionOption_BlockedOrUnbalancedArgument_ReturnsTrue(string argument)
    {
        Assert.True(JvmOptionPolicy.IsCommandExecutionOption(argument));
        Assert.True(JvmOptionPolicy.IsRejectedCustomArgument(argument));
    }

    [Theory]
    [InlineData("-Dfoo=bar")]
    [InlineData("-Xmx4G")]
    [InlineData("-XX:+UseZGC")]
    [InlineData("'-Dlog.dir=C:/logs'")]
    [InlineData("-Dmsg=don't")]
    [InlineData("\"-Dmsg=don't\"")]
    public void IsCommandExecutionOption_OrdinaryArgument_ReturnsFalse(string argument) =>
        Assert.False(JvmOptionPolicy.IsCommandExecutionOption(argument));

    [Fact]
    public void NormalizeJvmArgs_QuotedPathWithSpaces_ReturnsSingleUnquotedToken() =>
        Assert.Equal(["-Xmx4G", "-Dlog.dir=C:/my logs"], JvmOptionPolicy.NormalizeJvmArgs("-Xmx4G \"-Dlog.dir=C:/my logs\""));

    [Fact]
    public void NormalizeJvmArgs_UnclosedQuote_KeepsRawTokenThatIsRejected()
    {
        var tokens = JvmOptionPolicy.NormalizeJvmArgs("-Xmx4G -Dfoo=\"bar baz");

        Assert.Equal(["-Xmx4G", "-Dfoo=\"bar baz"], tokens);
        Assert.True(JvmOptionPolicy.IsCommandExecutionOption(tokens[1]));
    }
}
