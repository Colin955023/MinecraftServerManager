using System.Collections.Frozen;
using System.Diagnostics.CodeAnalysis;

namespace MinecraftServerManager.Infrastructure.Http;

/// <summary>官方來源網址檢查：HTTPS、預設埠、無使用者資訊且主機須在白名單內</summary>
internal static class TrustedHostPolicy
{
    /// <summary>建立不分大小寫的主機白名單</summary>
    public static FrozenSet<string> Hosts(params string[] hosts) =>
        hosts.ToFrozenSet(StringComparer.OrdinalIgnoreCase);

    /// <summary>網址符合官方來源條件時回傳解析結果</summary>
    public static bool TryCreate(string? url, FrozenSet<string> allowedHosts, [NotNullWhen(true)] out Uri? uri)
    {
        uri = null;
        if (string.IsNullOrWhiteSpace(url) || !Uri.TryCreate(url.Trim(), UriKind.Absolute, out var parsed))
        {
            return false;
        }

        if (parsed.Scheme != Uri.UriSchemeHttps
            || !parsed.IsDefaultPort
            || !string.IsNullOrEmpty(parsed.UserInfo)
            || !allowedHosts.Contains(parsed.Host))
        {
            return false;
        }

        uri = parsed;
        return true;
    }

    /// <summary>網址是否符合官方來源條件</summary>
    public static bool IsTrusted(string? url, FrozenSet<string> allowedHosts) =>
        TryCreate(url, allowedHosts, out _);
}
