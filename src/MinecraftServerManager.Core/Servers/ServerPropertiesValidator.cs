using System.Buffers;
using System.Collections.Frozen;
using System.Globalization;
using System.Net;
using System.Net.Sockets;
using MinecraftServerManager.Domain.ValueObjects;

namespace MinecraftServerManager.Core.Servers;

/// <summary>server.properties 數值驗證</summary>
public static class ServerPropertiesValidator
{
    private static readonly SearchValues<char> IpLiteralChars = SearchValues.Create("0123456789.");

    private delegate (bool IsValid, string? Error) Rule(string key, ReadOnlySpan<char> value);

    private static readonly FrozenDictionary<string, Rule> Rules = new Dictionary<string, Rule>(StringComparer.OrdinalIgnoreCase)
    {
        ["server-ip"] = static (_, v) => Check(v.IsEmpty || IsValidHostOrIp(v), "請填入有效的 IP 位址（如 127.0.0.1）或留空以繫結所有網路介面"),
        ["management-server-host"] = static (_, v) => Check(v.IsEmpty || IsValidHostOrIp(v), "請填入有效的主機名稱或 IP 位址"),
        ["server-port"] = PortRule,
        ["query.port"] = PortRule,
        ["rcon.port"] = PortRule,
        ["management-server-port"] = static (_, v) => InRange(v, 0, 65535, "管理端連接埠必須介於 0 到 65535 之間（0 為隨機指派）"),
        ["max-players"] = static (_, v) => InRange(v, 0, int.MaxValue, "最大玩家數量必須為大於或等於 0 的整數"),
        ["view-distance"] = static (_, v) => DistanceRule(v),
        ["simulation-distance"] = static (_, v) => DistanceRule(v),
        ["entity-broadcast-range-percentage"] = static (_, v) => InRange(v, 10, 1000, "實體廣播百分比必須介於 10 到 1000 之間"),
        ["function-permission-level"] = static (_, v) => PermissionRule(v),
        ["op-permission-level"] = static (_, v) => PermissionRule(v),
        ["max-world-size"] = static (_, v) => InRange(v, 1, 29_999_984, "世界最大半徑必須介於 1 到 29999984 之間"),
        ["spawn-protection"] = static (_, v) => NonNegativeRule(v),
        ["player-idle-timeout"] = static (_, v) => NonNegativeRule(v),
        ["rate-limit"] = static (_, v) => NonNegativeRule(v),
        ["chat-spam-threshold-seconds"] = static (_, v) => NonNegativeRule(v),
        ["command-spam-threshold-seconds"] = static (_, v) => NonNegativeRule(v),
        ["status-heartbeat-interval"] = static (_, v) => NonNegativeRule(v),
        ["max-tick-time"] = static (_, v) => InRange(v, -1, long.MaxValue, "每 tick 最大毫秒數必須為 -1（停用）或大於等於 0 的整數"),
        ["network-compression-threshold"] = static (_, v) => InRange(v, -1, int.MaxValue, "網路壓縮門檻值必須為 -1（停用）或大於等於 0 的整數"),
        ["text-filtering-version"] = static (_, v) => InRange(v, 0, 1, "文字過濾版本必須為 0 或 1"),
    }.ToFrozenDictionary(StringComparer.OrdinalIgnoreCase);

    /// <summary>驗證單一設定屬性值是否合法</summary>
    /// <param name="key">設定屬性索引鍵</param>
    /// <param name="value">欲驗證之數值</param>
    /// <param name="defaultValue">該屬性之預設值（用於推導型別）</param>
    /// <returns>若合法回傳 (true, null)；若非法回傳 (false, 錯誤描述)</returns>
    public static (bool IsValid, string? Error) ValidateProperty(string key, string value, string defaultValue)
    {
        ArgumentNullException.ThrowIfNull(key);
        ArgumentNullException.ThrowIfNull(value);
        ReadOnlySpan<char> val = value.AsSpan().Trim();

        if (ServerPropertiesMetadata.GetOptions(key) is { Count: > 0 } options)
        {
            foreach (string option in options)
            {
                if (val.Equals(option, StringComparison.OrdinalIgnoreCase))
                {
                    return (true, null);
                }
            }

            return (false, $"{key} 必須為 {string.Join("、", options)} 中的一項");
        }

        return Rules.TryGetValue(key, out var rule)
            ? rule(key, val)
            : ValidateByDefaultType(key, val, defaultValue);
    }

    private static (bool, string?) PortRule(string key, ReadOnlySpan<char> v) =>
        InRange(v, 1, 65534, $"連接埠 {key} 必須在 1 到 65534 之間");

    private static (bool, string?) DistanceRule(ReadOnlySpan<char> v) =>
        InRange(v, 2, 32, "距離必須介於 2 到 32 之間");

    private static (bool, string?) PermissionRule(ReadOnlySpan<char> v) =>
        InRange(v, 0, 4, "權限等級必須介於 0 到 4 之間");

    private static (bool, string?) NonNegativeRule(ReadOnlySpan<char> v) =>
        InRange(v, 0, int.MaxValue, "此設定必須為大於或等於 0 的整數");

    /// <summary>未列舉之屬性依布林標記或預設值推導型別驗證</summary>
    private static (bool, string?) ValidateByDefaultType(string key, ReadOnlySpan<char> val, string defaultValue)
    {
        if (ServerPropertiesMetadata.IsBoolean(key) || bool.TryParse(defaultValue, out _))
        {
            return Check(bool.TryParse(val, out _), "此設定僅允許填入 true 或 false");
        }

        string effectiveDefault = string.IsNullOrEmpty(defaultValue) ? ServerPropertiesMetadata.GetDefault(key) : defaultValue;
        return long.TryParse(effectiveDefault, CultureInfo.InvariantCulture, out _)
            ? Check(long.TryParse(val, CultureInfo.InvariantCulture, out _), "此設定必須填入整數數值")
            : (true, null);
    }

    private static (bool, string?) Check(bool isValid, string error) => isValid ? (true, null) : (false, error);

    private static (bool, string?) InRange(ReadOnlySpan<char> val, long min, long max, string error) =>
        Check(long.TryParse(val, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out long number) && number >= min && number <= max, error);

    private static bool IsValidHostOrIp(ReadOnlySpan<char> val)
    {
        if (val.Equals("localhost", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        if (val.Contains(':'))
        {
            return IPAddress.TryParse(val, out var v6) && v6.AddressFamily == AddressFamily.InterNetworkV6;
        }

        // 僅含數字與句點者必須為完整四段十進位 IPv4（拒絕 999、127.1 等縮寫）
        if (!val.ContainsAnyExcept(IpLiteralChars))
        {
            return IsStrictIPv4(val);
        }

        return Uri.CheckHostName(val.ToString()) == UriHostNameType.Dns;
    }

    private static bool IsStrictIPv4(ReadOnlySpan<char> val)
    {
        Span<int> numbers = stackalloc int[4];
        if (!DotSeparatedIntParser.TryParse(val, numbers, out int count) || count != 4)
        {
            return false;
        }

        Span<Range> parts = stackalloc Range[5];
        val.Split(parts, '.');
        for (int i = 0; i < 4; i++)
        {
            ReadOnlySpan<char> segment = val[parts[i]];
            if ((segment.Length > 1 && segment[0] == '0') || numbers[i] > 255)
            {
                return false;
            }
        }

        return true;
    }
}
