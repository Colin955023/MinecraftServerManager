using System.Buffers;
using System.Globalization;
using System.Net;

namespace MinecraftServerManager.Core.Servers;

/// <summary>提供 Minecraft server.properties 設定項目數值合法性驗證</summary>
public static class ServerPropertiesValidator
{
    private static readonly SearchValues<char> IpLiteralChars = SearchValues.Create("0123456789.");

    /// <summary>驗證單一設定屬性值是否合法</summary>
    /// <param name="key">設定屬性索引鍵</param>
    /// <param name="value">欲驗證之數值</param>
    /// <param name="defaultValue">該屬性之預設值（用於推導型別）</param>
    /// <returns>若合法回傳 (true, null)；若非法回傳 (false, 錯誤描述)</returns>
    public static (bool IsValid, string? Error) ValidateProperty(string key, string value, string defaultValue)
    {
        ArgumentNullException.ThrowIfNull(key);
        ArgumentNullException.ThrowIfNull(value);
        string val = value.Trim();

        return key.ToLowerInvariant() switch
        {
            "server-ip" => Check(val.Length == 0 || IsValidHostOrIp(val), "請填入有效的 IP 位址（如 127.0.0.1）或留空以繫結所有網路介面"),
            "management-server-host" => Check(val.Length == 0 || IsValidHostOrIp(val), "請填入有效的主機名稱或 IP 位址"),
            "server-port" or "query.port" or "rcon.port" => IntInRange(val, 1, 65534, $"連接埠 {key} 必須在 1 到 65534 之間"),
            "management-server-port" => IntInRange(val, 0, 65535, "管理端連接埠必須介於 0 到 65535 之間（0 為隨機指派）"),
            "max-players" => IntInRange(val, 0, int.MaxValue, "最大玩家數量必須為大於或等於 0 的整數"),
            "view-distance" or "simulation-distance" => IntInRange(val, 2, 32, "距離必須介於 2 到 32 之間"),
            "entity-broadcast-range-percentage" => IntInRange(val, 10, 1000, "實體廣播百分比必須介於 10 到 1000 之間"),
            "difficulty" => Check(IsListedOption(key, val), "難度必須為 peaceful、easy、normal 或 hard"),
            "gamemode" => Check(IsListedOption(key, val), "遊戲模式必須為 survival、creative、adventure 或 spectator"),
            "function-permission-level" or "op-permission-level" => IntInRange(val, 0, 4, "權限等級必須介於 0 到 4 之間"),
            _ => ValidateByDefaultType(key, val, defaultValue),
        };
    }

    /// <summary>未列舉之屬性依布林清單或預設值推導型別驗證</summary>
    private static (bool, string?) ValidateByDefaultType(string key, string val, string defaultValue)
    {
        if (ServerPropertiesMetadata.BooleanKeys.Contains(key) || bool.TryParse(defaultValue, out _))
        {
            return Check(bool.TryParse(val, out _), "此設定僅允許填入 true 或 false");
        }

        string effectiveDefault = string.IsNullOrEmpty(defaultValue) ? ServerPropertiesMetadata.GetDefault(key) : defaultValue;
        return long.TryParse(effectiveDefault, CultureInfo.InvariantCulture, out _)
            ? Check(long.TryParse(val, CultureInfo.InvariantCulture, out _), "此設定必須填入整數數值")
            : (true, null);
    }

    private static (bool, string?) Check(bool isValid, string error) => isValid ? (true, null) : (false, error);

    private static (bool, string?) IntInRange(string val, int min, int max, string error) =>
        Check(int.TryParse(val, CultureInfo.InvariantCulture, out int number) && number >= min && number <= max, error);

    private static bool IsListedOption(string key, string val) =>
        ServerPropertiesMetadata.GetOptions(key) is { } options && options.Contains(val, StringComparer.OrdinalIgnoreCase);

    private static bool IsValidHostOrIp(string val)
    {
        if (IPAddress.TryParse(val, out _) || string.Equals(val, "localhost", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        // 僅含數字與句點卻非合法 IP（如 999.1.1）者視為無效，避免被當成主機名稱放行
        if (val.Contains('.', StringComparison.Ordinal) && !val.AsSpan().ContainsAnyExcept(IpLiteralChars))
        {
            return false;
        }

        return Uri.CheckHostName(val) == UriHostNameType.Dns;
    }
}
