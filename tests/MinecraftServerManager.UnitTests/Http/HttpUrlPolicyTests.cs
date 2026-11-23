using System.Net;
using System.Net.Sockets;
using MinecraftServerManager.Infrastructure.Http;

namespace MinecraftServerManager.UnitTests.Http;

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
    [InlineData("240.0.0.1")]
    [InlineData("255.255.255.255")]
    [InlineData("192.88.99.1")]
    [InlineData("64:ff9b:1::a00:1")]
    [InlineData("2001:10::1")]
    [InlineData("2001:20::1")]
    public void IsPublicAddress_NonPublicAddresses_ReturnsFalse(string text) =>
        Assert.False(HttpUrlPolicy.IsPublicAddress(IPAddress.Parse(text)));

    [Fact]
    public async Task ConnectAsync_MixedPublicAndPrivateAddresses_RejectsEntireBatch()
    {
        var exception = await Assert.ThrowsAsync<HttpSecurityException>(async () =>
            await HttpUrlPolicy.ConnectAsync(
                new DnsEndPoint("mixed.example", 443),
                (_, _) => Task.FromResult(new[]
                {
                    IPAddress.Parse("8.8.8.8"),
                    IPAddress.Parse("10.0.0.1"),
                }),
                TestContext.Current.CancellationToken));

        Assert.Contains("非公開", exception.Message);
    }

    [Fact]
    public async Task ConnectAsync_DnsResolutionFailure_ThrowsRetryableHttpRequestException()
    {
        int attempts = 0;

        var exception = await Assert.ThrowsAsync<HttpRequestException>(async () =>
            await HttpUrlPolicy.ConnectAsync(
                new DnsEndPoint("transient-dns.example", 443),
                (_, _) =>
                {
                    attempts++;
                    throw new SocketException((int)SocketError.TryAgain);
                },
                TestContext.Current.CancellationToken));

        Assert.Equal(1, attempts);
        Assert.IsType<SocketException>(exception.InnerException);
    }
}
