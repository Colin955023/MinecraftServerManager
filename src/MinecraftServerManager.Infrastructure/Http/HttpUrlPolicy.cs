using System.Net;
using System.Net.Sockets;

namespace MinecraftServerManager.Infrastructure.Http;

/// <summary>HTTP 連線安全原則：只允許 HTTPS 公開位址，並於連線當下再次驗證 DNS 解析結果（防 DNS rebinding）</summary>
public static class HttpUrlPolicy
{
    /// <summary>單一位址的連線逾時；逾時即改試下一個位址，避免首個位址不通時耗盡整體逾時</summary>
    private static readonly TimeSpan PerAddressConnectTimeout = TimeSpan.FromSeconds(5);

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
        IPNetwork.Parse("192.88.99.0/24"),
        IPNetwork.Parse("192.168.0.0/16"),
        IPNetwork.Parse("198.18.0.0/15"),
        IPNetwork.Parse("198.51.100.0/24"),
        IPNetwork.Parse("203.0.113.0/24"),
        IPNetwork.Parse("224.0.0.0/4"),
        IPNetwork.Parse("240.0.0.0/4"),
    ];

    private static readonly IPNetwork[] PrivateIPv6Networks =
    [
        IPNetwork.Parse("fc00::/7"),
        IPNetwork.Parse("ff00::/8"),
        IPNetwork.Parse("2001:db8::/32"),
        IPNetwork.Parse("2001:10::/28"),
        IPNetwork.Parse("2001:20::/28"),
        IPNetwork.Parse("64:ff9b:1::/48"),
        IPNetwork.Parse("100::/64"),
    ];

    /// <summary>供 <see cref="SocketsHttpHandler.ConnectCallback"/> 使用的連線進入點</summary>
    public static async ValueTask<Stream> ConnectAsync(
        SocketsHttpConnectionContext context,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(context);
        return await ConnectAsync(context.DnsEndPoint, resolver: null, cancellationToken).ConfigureAwait(false);
    }

    /// <summary>解析主機並只連線至公開位址；<paramref name="resolver"/> 為 null 時使用系統 DNS</summary>
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
            // 與 SocketsHttpHandler 預設連線一致啟用 NoDelay，避免小型 API 請求受 Nagle 演算法延遲
            var socket = (Socket?)new Socket(address.AddressFamily, SocketType.Stream, ProtocolType.Tcp) { NoDelay = true };
            using var attemptCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            attemptCts.CancelAfter(PerAddressConnectTimeout);
            try
            {
                await socket!.ConnectAsync(new IPEndPoint(address, endpoint.Port), attemptCts.Token).ConfigureAwait(false);
                var stream = new NetworkStream(socket, ownsSocket: true);
                socket = null;
                return stream;
            }
            catch (SocketException exception)
            {
                lastException = exception;
            }
            catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
            {
                // 單一位址逾時（非呼叫端取消）：改試下一個位址
                lastException = new SocketException((int)SocketError.TimedOut);
            }
            finally
            {
                socket?.Dispose();
            }
        }

        throw new HttpRequestException("無法連線至已驗證的公開主機", lastException);
    }

    /// <summary>不需連線即可判定的靜態檢查：HTTPS、無帳密、非 localhost、非私有 IP 字面值</summary>
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

    /// <summary>解析主機名稱（或 IP 字面值）並確認所有位址皆為公開位址，否則擲出 HttpSecurityException</summary>
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

    /// <summary>判斷位址是否為可路由的公開位址（排除迴路、私有、保留、多點傳送與內嵌私有 IPv4 的轉換位址）</summary>
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
