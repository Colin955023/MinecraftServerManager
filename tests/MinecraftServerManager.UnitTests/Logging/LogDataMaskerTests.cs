namespace MinecraftServerManager.UnitTests.Logging;

public sealed class LogDataMaskerTests
{
    [Fact]
    public void Mask_PasswordsAndTokens_HidesSecrets()
    {
        string input = "連線字串包含 password=mySecretPassword123 與 token=xyz890 以及 Bearer eyJhbGciOiJIUzI1Ni";
        string masked = LogDataMasker.Mask(input);

        Assert.DoesNotContain("mySecretPassword123", masked, StringComparison.Ordinal);
        Assert.DoesNotContain("xyz890", masked, StringComparison.Ordinal);
        Assert.DoesNotContain("eyJhbGciOiJIUzI1Ni", masked, StringComparison.Ordinal);
        Assert.Contains("password=***", masked, StringComparison.Ordinal);
        Assert.Contains("token=***", masked, StringComparison.Ordinal);
        Assert.Contains("Bearer ***", masked, StringComparison.OrdinalIgnoreCase);
    }
}
