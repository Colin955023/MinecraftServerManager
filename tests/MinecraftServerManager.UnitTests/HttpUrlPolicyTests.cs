using System.Net;
using MinecraftServerManager.Infrastructure.Http;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class HttpUrlPolicyTests
{
    [Theory]
    [InlineData("8.8.8.8")]
    [InlineData("1.1.1.1")]
    [InlineData("2606:4700:4700::1111")]
    [InlineData("2002:0808:0808::1")]
    [InlineData("64:ff9b::808:808")]
    public void IsPublicAddress_PublicAddresses_ReturnsTrue(string text) =>
        Assert.True(HttpUrlPolicy.IsPublicAddress(IPAddress.Parse(text)));

    [Theory]
    [InlineData("127.0.0.1")]
    [InlineData("10.0.0.1")]
    [InlineData("192.168.1.1")]
    [InlineData("169.254.169.254")]
    [InlineData("::1")]
    [InlineData("fc00::1")]
    [InlineData("fe80::1")]
    [InlineData("2002:0a00:0001::1")]
    [InlineData("64:ff9b::a00:1")]
    [InlineData("::ffff:127.0.0.1")]
    public void IsPublicAddress_NonPublicAddresses_ReturnsFalse(string text) =>
        Assert.False(HttpUrlPolicy.IsPublicAddress(IPAddress.Parse(text)));
}
