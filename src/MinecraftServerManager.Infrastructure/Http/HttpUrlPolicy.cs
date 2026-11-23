using System.Net;
using System.Net.Sockets;

namespace MinecraftServerManager.Infrastructure.Http;

/// <summary>HTTP 連線安全原則：只允許 HTTPS 公開位址，連線時再驗證 DNS 解析結果</summary>
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

    // IPv6 採白名單：只允許全球單播 2000::/3，再扣除其中的保留段
    private static readonly IPNetwork GlobalUnicastIPv6 = IPNetwork.Parse("2000::/3");

    private static readonly IPNetwork[] ReservedGlobalUnicastIPv6Networks =
    [
        IPNetwork.Parse("2001::/23"),     // IETF 協定指派（含 Teredo、ORCHID、基準測試）
        IPNetwork.Parse("2001:db8::/32"), // 文件範例
        IPNetwork.Parse("3fff::/20"),     // 文件範例
    ];

    // 公開 NAT64 前綴（RFC 6052）：以內嵌 IPv4 判定
    private static readonly IPNetwork WellKnownNat64 = IPNetwork.Parse("64:ff9b::/96");
    private static readonly IPNetwork SixToFour = IPNetwork.Parse("2002::/16");

    /// <summary><see cref="SocketsHttpHandler.ConnectCallback"/> 的連線進入點</summary>
    public static async ValueTask<Stream> ConnectAsync(
        SocketsHttpConnectionContext context,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(context);
        return await ConnectAsync(context.DnsEndPoint, resolver: null, cancellationToken).ConfigureAwait(false);
    }

    /// <summary>解析主機並只連線至公開位址</summary>
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
            Socket? socket = null;
            using var attemptCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            attemptCts.CancelAfter(PerAddressConnectTimeout);
            try
            {
                // 啟用 NoDelay，與 SocketsHttpHandler 預設一致
                socket = new Socket(address.AddressFamily, SocketType.Stream, ProtocolType.Tcp) { NoDelay = true };
                await socket.ConnectAsync(new IPEndPoint(address, endpoint.Port), attemptCts.Token).ConfigureAwait(false);
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

    /// <summary>靜態檢查：HTTPS、無帳密、非 localhost、非私有 IP</summary>
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

    /// <summary>解析主機並確認所有位址皆為公開位址，否則擲出</summary>
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
                // DNS 失敗屬暫時性網路錯誤，交由重試邏輯處理，不視為安全違規
                throw new HttpRequestException($"無法解析主機名稱：{host}", exception);
            }
        }

        if (addresses.Length == 0 || !Array.TrueForAll(addresses, IsPublicAddress))
        {
            throw new HttpSecurityException("URL hostname 解析至非公開位址");
        }

        return addresses;
    }

    private static bool IsLocalhostName(string host) =>
        host.Equals("localhost", StringComparison.OrdinalIgnoreCase)
        || host.EndsWith(".localhost", StringComparison.OrdinalIgnoreCase);

    /// <summary>是否為可路由的公開位址</summary>
    internal static bool IsPublicAddress(IPAddress address)
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
            return !ContainsAny(PrivateIPv4Networks, normalized);
        }

        // NAT64 與 6to4 內嵌 IPv4，以內嵌位址判定
        if (WellKnownNat64.Contains(normalized))
        {
            return IsPublicAddress(new IPAddress(span.Slice(12, 4)));
        }

        if (SixToFour.Contains(normalized))
        {
            return IsPublicAddress(new IPAddress(span.Slice(2, 4)));
        }

        return GlobalUnicastIPv6.Contains(normalized) && !ContainsAny(ReservedGlobalUnicastIPv6Networks, normalized);
    }

    private static bool ContainsAny(IPNetwork[] networks, IPAddress address)
    {
        foreach (IPNetwork network in networks)
        {
            if (network.Contains(address))
            {
                return true;
            }
        }

        return false;
    }
}
