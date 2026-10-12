using System.Net;
using System.Net.Sockets;

namespace MinecraftServerManager.Infrastructure.Http;

public static class HttpUrlPolicy
{
    public static void ValidateStatic(Uri uri)
    {
        ArgumentNullException.ThrowIfNull(uri);
        if (!uri.IsAbsoluteUri || !string.Equals(uri.Scheme, Uri.UriSchemeHttps, StringComparison.OrdinalIgnoreCase))
        {
            throw new HttpSecurityException("只允許 HTTPS URL");
        }

        if (string.IsNullOrWhiteSpace(uri.Host) || !string.IsNullOrEmpty(uri.UserInfo))
        {
            throw new HttpSecurityException("URL 格式或 credential 不安全");
        }

        if (uri.Host.Equals("localhost", StringComparison.OrdinalIgnoreCase)
            || uri.Host.EndsWith(".localhost", StringComparison.OrdinalIgnoreCase))
        {
            throw new HttpSecurityException("拒絕 localhost URL");
        }

        if (uri.Port is < 1 or > 65535)
        {
            throw new HttpSecurityException("URL port 無效");
        }

        if (IPAddress.TryParse(uri.Host, out var address) && !IsPublicAddress(address))
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
        if (IPAddress.TryParse(uri.Host, out var literal))
        {
            if (!IsPublicAddress(literal))
            {
                throw new HttpSecurityException("拒絕非公開 IP URL");
            }

            return;
        }

        Func<string, CancellationToken, Task<IPAddress[]>> resolve = resolver
            ?? ((host, token) => Dns.GetHostAddressesAsync(host, token));
        IPAddress[] addresses;
        try
        {
            addresses = await resolve(uri.Host.TrimEnd('.'), cancellationToken).ConfigureAwait(false);
        }
        catch (SocketException exception)
        {
            throw new HttpSecurityException("URL hostname 無法解析", exception);
        }

        if (addresses.Length == 0 || addresses.Any(address => !IsPublicAddress(address)))
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

        byte[] bytes = normalized.GetAddressBytes();
        if (normalized.AddressFamily == AddressFamily.InterNetwork)
        {
            return !(bytes[0] == 0
                || bytes[0] == 10
                || (bytes[0] == 100 && bytes[1] is >= 64 and <= 127)
                || bytes[0] == 127
                || (bytes[0] == 169 && bytes[1] == 254)
                || (bytes[0] == 172 && bytes[1] is >= 16 and <= 31)
                || (bytes[0] == 192 && bytes[1] == 0 && (bytes[2] == 0 || bytes[2] == 2))
                || (bytes[0] == 192 && bytes[1] == 168)
                || (bytes[0] == 198 && bytes[1] is >= 18 and <= 19)
                || (bytes[0] == 198 && bytes[1] == 51 && bytes[2] == 100)
                || (bytes[0] == 203 && bytes[1] == 0 && bytes[2] == 113)
                || bytes[0] >= 224);
        }

        if (IsIPv4Compatible(bytes))
        {
            var ipv4 = new IPAddress(bytes.AsSpan(12, 4));
            return IsPublicAddress(ipv4);
        }

        return !normalized.IsIPv6LinkLocal
            && !normalized.IsIPv6SiteLocal
            && !normalized.IsIPv6Teredo
            && (bytes[0] & 0xFE) != 0xFC
            && bytes[0] != 0xFF
            && !(bytes[0] == 0x20 && bytes[1] == 0x01 && bytes[2] == 0x0D && bytes[3] == 0xB8)
            && !(bytes[0] == 0x01 && bytes[1] == 0x00);
    }

    private static bool IsIPv4Compatible(byte[] bytes)
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
