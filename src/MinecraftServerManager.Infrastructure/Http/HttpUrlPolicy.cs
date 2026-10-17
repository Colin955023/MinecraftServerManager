using System.Net;
using System.Net.Sockets;

namespace MinecraftServerManager.Infrastructure.Http;

public static class HttpUrlPolicy
{
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
            || host.Equals("localhost", StringComparison.OrdinalIgnoreCase)
            || host.EndsWith(".localhost", StringComparison.OrdinalIgnoreCase)
            || endpoint.Port is < 1 or > 65535)
        {
            throw new HttpSecurityException("連線目標無效或不安全");
        }

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

        if (host.Equals("localhost", StringComparison.OrdinalIgnoreCase)
            || host.EndsWith(".localhost", StringComparison.OrdinalIgnoreCase))
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
        string host = uri.Host.TrimEnd('.');
        if (IPAddress.TryParse(host, out var literal))
        {
            if (!IsPublicAddress(literal))
            {
                throw new HttpSecurityException("拒絕非公開 IP URL");
            }

            return;
        }

        Func<string, CancellationToken, Task<IPAddress[]>> resolve = resolver
            ?? (static (h, token) => Dns.GetHostAddressesAsync(h, token));
        IPAddress[] addresses;
        try
        {
            addresses = await resolve(host, cancellationToken).ConfigureAwait(false);
        }
        catch (SocketException exception)
        {
            throw new HttpSecurityException("URL hostname 無法解析", exception);
        }

        if (addresses.Length == 0 || addresses.Any(static address => !IsPublicAddress(address)))
        {
            throw new HttpSecurityException("URL hostname 解析至非公開位址");
        }
    }

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
            return !(span[0] == 0
                || span[0] == 10
                || (span[0] == 100 && span[1] is >= 64 and <= 127)
                || span[0] == 127
                || (span[0] == 169 && span[1] == 254)
                || (span[0] == 172 && span[1] is >= 16 and <= 31)
                || (span[0] == 192 && span[1] == 0 && (span[2] == 0 || span[2] == 2))
                || (span[0] == 192 && span[1] == 168)
                || (span[0] == 198 && span[1] is >= 18 and <= 19)
                || (span[0] == 198 && span[1] == 51 && span[2] == 100)
                || (span[0] == 203 && span[1] == 0 && span[2] == 113)
                || span[0] >= 224);
        }

        if (IsIPv4Compatible(span))
        {
            var ipv4 = new IPAddress(span.Slice(12, 4));
            return IsPublicAddress(ipv4);
        }

        return !normalized.IsIPv6LinkLocal
            && !normalized.IsIPv6SiteLocal
            && !normalized.IsIPv6Teredo
            && (span[0] & 0xFE) != 0xFC
            && span[0] != 0xFF
            && !(span[0] == 0x20 && span[1] == 0x01 && span[2] == 0x0D && span[3] == 0xB8)
            && !(span[0] == 0x01 && span[1] == 0x00);
    }

    private static bool IsIPv4Compatible(ReadOnlySpan<byte> bytes)
    {
        if (bytes.Length != 16)
        {
            return false;
        }

        for (int i = 0; i < 12; i++)
        {
            if (bytes[i] != 0)
            {
                return false;
            }
        }

        return !(bytes[12] == 0 && bytes[13] == 0 && bytes[14] == 0 && bytes[15] <= 1);
    }
}
