using System.Net;
using System.Net.Sockets;

namespace MinecraftServerManager.Infrastructure.Http;

public static class HttpUrlPolicy
{
    private static readonly IPNetwork[] PrivateIPv4Networks =
    [
        IPNetwork.Parse("0.0.0.0/8"),
        IPNetwork.Parse("10.0.0.0/8"),
        IPNetwork.Parse("100.64.0.0/10"),
        IPNetwork.Parse("127.0.0.0/8"),
        IPNetwork.Parse("169.254.0.0/16"),
        IPNetwork.Parse("172.16.0.0/12"),
        IPNetwork.Parse("192.0.0.0/24"),
        IPNetwork.Parse("192.0.2.0/24"),
        IPNetwork.Parse("192.168.0.0/16"),
        IPNetwork.Parse("198.18.0.0/15"),
        IPNetwork.Parse("198.51.100.0/24"),
        IPNetwork.Parse("203.0.113.0/24"),
        IPNetwork.Parse("224.0.0.0/4"),
    ];

    private static readonly IPNetwork[] PrivateIPv6Networks =
    [
        IPNetwork.Parse("fc00::/7"),
        IPNetwork.Parse("ff00::/8"),
        IPNetwork.Parse("2001:db8::/32"),
        IPNetwork.Parse("100::/64"),
    ];
    public static async ValueTask<Stream> ConnectAsync(
        SocketsHttpConnectionContext context,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(context);
        return await ConnectAsync(context.DnsEndPoint, resolver: null, cancellationToken).ConfigureAwait(false);
    }

    public static async ValueTask<Stream> ConnectAsync(
        DnsEndPoint endpoint,
        Func<string, CancellationToken, Task<IPAddress[]>>? resolver,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(endpoint);
        string host = endpoint.Host.TrimEnd('.');
        if (string.IsNullOrWhiteSpace(host)
            || IsLocalhostName(host)
            || endpoint.Port is < 1 or > 65535)
        {
            throw new HttpSecurityException("連線目標無效或不安全");
        }

        IPAddress[] addresses = await ResolvePublicAddressesAsync(host, resolver, cancellationToken).ConfigureAwait(false);

        SocketException? lastException = null;
        foreach (IPAddress address in addresses)
        {
            var socket = (Socket?)new Socket(address.AddressFamily, SocketType.Stream, ProtocolType.Tcp);
            try
            {
                await socket!.ConnectAsync(new IPEndPoint(address, endpoint.Port), cancellationToken).ConfigureAwait(false);
                var stream = new NetworkStream(socket, ownsSocket: true);
                socket = null;
                return stream;
            }
            catch (SocketException exception)
            {
                lastException = exception;
            }
            finally
            {
                socket?.Dispose();
            }
        }

        throw new HttpRequestException("無法連線至已驗證的公開主機", lastException);
    }

    public static void ValidateStatic(Uri uri)
    {
        ArgumentNullException.ThrowIfNull(uri);
        if (!uri.IsAbsoluteUri || !string.Equals(uri.Scheme, Uri.UriSchemeHttps, StringComparison.OrdinalIgnoreCase))
        {
            throw new HttpSecurityException("只允許 HTTPS URL");
        }

        string host = uri.Host.TrimEnd('.');
        if (string.IsNullOrWhiteSpace(host) || !string.IsNullOrEmpty(uri.UserInfo))
        {
            throw new HttpSecurityException("URL 格式或 credential 不安全");
        }

        if (IsLocalhostName(host))
        {
            throw new HttpSecurityException("拒絕 localhost URL");
        }

        if (uri.Port is < 1 or > 65535)
        {
            throw new HttpSecurityException("URL port 無效");
        }

        if (IPAddress.TryParse(host, out var address) && !IsPublicAddress(address))
        {
            throw new HttpSecurityException("拒絕非公開 IP URL");
        }
    }

    public static async Task ValidatePublicHostAsync(
        Uri uri,
        Func<string, CancellationToken, Task<IPAddress[]>>? resolver = null,
        CancellationToken cancellationToken = default)
    {
        ValidateStatic(uri);
        await ResolvePublicAddressesAsync(uri.Host.TrimEnd('.'), resolver, cancellationToken).ConfigureAwait(false);
    }

    /// <summary>
    /// 解析主機名稱（或 IP 字面值）並確認所有位址皆為公開位址，否則擲出 HttpSecurityException
    /// </summary>
    private static async Task<IPAddress[]> ResolvePublicAddressesAsync(
        string host,
        Func<string, CancellationToken, Task<IPAddress[]>>? resolver,
        CancellationToken cancellationToken)
    {
        IPAddress[] addresses;
        if (IPAddress.TryParse(host, out var literal))
        {
            addresses = [literal];
        }
        else
        {
            Func<string, CancellationToken, Task<IPAddress[]>> resolve = resolver
                ?? (static (name, token) => Dns.GetHostAddressesAsync(name, token));
            try
            {
                addresses = await resolve(host, cancellationToken).ConfigureAwait(false);
            }
            catch (SocketException exception)
            {
                throw new HttpSecurityException("URL hostname 無法解析", exception);
            }
        }

        if (addresses.Length == 0 || addresses.Any(static address => !IsPublicAddress(address)))
        {
            throw new HttpSecurityException("URL hostname 解析至非公開位址");
        }

        return addresses;
    }

    private static bool IsLocalhostName(string host) =>
        host.Equals("localhost", StringComparison.OrdinalIgnoreCase)
        || host.EndsWith(".localhost", StringComparison.OrdinalIgnoreCase);

    public static bool IsPublicAddress(IPAddress address)
    {
        var normalized = address.IsIPv4MappedToIPv6 ? address.MapToIPv4() : address;
        if (IPAddress.IsLoopback(normalized)
            || normalized.Equals(IPAddress.Any)
            || normalized.Equals(IPAddress.IPv6Any)
            || normalized.Equals(IPAddress.None)
            || normalized.Equals(IPAddress.IPv6None))
        {
            return false;
        }

        Span<byte> bytes = stackalloc byte[16];
        if (!normalized.TryWriteBytes(bytes, out int bytesWritten))
        {
            return false;
        }

        var span = bytes[..bytesWritten];
        if (normalized.AddressFamily == AddressFamily.InterNetwork)
        {
            return !PrivateIPv4Networks.Any(net => net.Contains(normalized));
        }

        if (IsIPv4Compatible(span))
        {
            var ipv4 = new IPAddress(span.Slice(12, 4));
            return IsPublicAddress(ipv4);
        }

        // 6to4（2002::/16）與 NAT64（64:ff9b::/96）內嵌 IPv4，需以內嵌位址判定是否為公開位址
        if (span[0] == 0x20 && span[1] == 0x02)
        {
            return IsPublicAddress(new IPAddress(span.Slice(2, 4)));
        }

        if (span[0] == 0x00 && span[1] == 0x64 && span[2] == 0xFF && span[3] == 0x9B && span[4..12].IndexOfAnyExcept((byte)0) < 0)
        {
            return IsPublicAddress(new IPAddress(span.Slice(12, 4)));
        }

        return !normalized.IsIPv6LinkLocal
            && !normalized.IsIPv6SiteLocal
            && !normalized.IsIPv6Teredo
            && !PrivateIPv6Networks.Any(net => net.Contains(normalized));
    }

    private static bool IsIPv4Compatible(ReadOnlySpan<byte> bytes)
    {
        if (bytes.Length != 16)
        {
            return false;
        }

        return bytes[..12].IndexOfAnyExcept((byte)0) < 0
            && !(bytes[12] == 0 && bytes[13] == 0 && bytes[14] == 0 && bytes[15] <= 1);
    }
}
