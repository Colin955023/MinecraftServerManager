using MinecraftServerManager.Core.Servers;

namespace MinecraftServerManager.UnitTests.Servers;

public sealed class ServerPropertiesValidatorTests
{
    [Theory]
    [InlineData("", true)]
    [InlineData("127.0.0.1", true)]
    [InlineData("0.0.0.0", true)]
    [InlineData("192.168.1.100", true)]
    [InlineData("::1", true)]
    [InlineData("localhost", true)]
    [InlineData("invalid ip address!", false)]
    [InlineData("999.999.999.999", false)]
    public void ValidateProperty_ServerIp_ReturnsExpected(string ip, bool expectedValid)
    {
        var (isValid, _) = ServerPropertiesValidator.ValidateProperty("server-ip", ip, "");
        Assert.Equal(expectedValid, isValid);
    }

    [Theory]
    [InlineData("25565", true)]
    [InlineData("1", true)]
    [InlineData("65534", true)]
    [InlineData("65535", false)]
    [InlineData("0", false)]
    [InlineData("-1", false)]
    [InlineData("65536", false)]
    [InlineData("not-a-port", false)]
    public void ValidateProperty_ServerPort_ReturnsExpected(string port, bool expectedValid)
    {
        var (isValid, _) = ServerPropertiesValidator.ValidateProperty("server-port", port, "25565");
        Assert.Equal(expectedValid, isValid);
    }

    [Theory]
    [InlineData("peaceful", true)]
    [InlineData("easy", true)]
    [InlineData("normal", true)]
    [InlineData("hard", true)]
    [InlineData("PEACEFUL", true)]
    [InlineData("invalid_difficulty", false)]
    public void ValidateProperty_Difficulty_ReturnsExpected(string diff, bool expectedValid)
    {
        var (isValid, _) = ServerPropertiesValidator.ValidateProperty("difficulty", diff, "easy");
        Assert.Equal(expectedValid, isValid);
    }

    [Theory]
    [InlineData("survival", true)]
    [InlineData("creative", true)]
    [InlineData("adventure", true)]
    [InlineData("spectator", true)]
    [InlineData("SURVIVAL", true)]
    [InlineData("unknown_mode", false)]
    public void ValidateProperty_Gamemode_ReturnsExpected(string gm, bool expectedValid)
    {
        var (isValid, _) = ServerPropertiesValidator.ValidateProperty("gamemode", gm, "survival");
        Assert.Equal(expectedValid, isValid);
    }

    [Theory]
    [InlineData("true", true)]
    [InlineData("false", true)]
    [InlineData("TRUE", true)]
    [InlineData("FALSE", true)]
    [InlineData("yes", false)]
    [InlineData("1", false)]
    public void ValidateProperty_BooleanProperty_ReturnsExpected(string val, bool expectedValid)
    {
        var (isValid, _) = ServerPropertiesValidator.ValidateProperty("white-list", val, "false");
        Assert.Equal(expectedValid, isValid);
    }

    [Theory]
    [InlineData("20", true)]
    [InlineData("0", true)]
    [InlineData("100", true)]
    [InlineData("-1", false)]
    [InlineData("abc", false)]
    public void ValidateProperty_MaxPlayers_ReturnsExpected(string players, bool expectedValid)
    {
        var (isValid, _) = ServerPropertiesValidator.ValidateProperty("max-players", players, "20");
        Assert.Equal(expectedValid, isValid);
    }

    [Theory]
    [InlineData("2", true)]
    [InlineData("10", true)]
    [InlineData("32", true)]
    [InlineData("1", false)]
    [InlineData("33", false)]
    public void ValidateProperty_ViewDistance_ReturnsExpected(string dist, bool expectedValid)
    {
        var (isValid, _) = ServerPropertiesValidator.ValidateProperty("view-distance", dist, "10");
        Assert.Equal(expectedValid, isValid);
    }

    [Theory]
    [InlineData("true", true)]
    [InlineData("false", true)]
    [InlineData("invalid", false)]
    public void ValidateProperty_EnableCodeOfConduct_ReturnsExpected(string val, bool expectedValid)
    {
        string def = ServerPropertiesMetadata.GetDefault("enable-code-of-conduct");
        Assert.Equal("false", def);
        var (isValid, _) = ServerPropertiesValidator.ValidateProperty("enable-code-of-conduct", val, def);
        Assert.Equal(expectedValid, isValid);
    }
}
