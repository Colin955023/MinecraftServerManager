using System.Collections.Frozen;
using System.Net;

namespace MinecraftServerManager.Core.Servers;

/// <summary>
/// 提供 Minecraft server.properties 設定項目數值合法性驗證
/// </summary>
public static class ServerPropertiesValidator
{
    private static readonly FrozenSet<string> ValidDifficulties =
        new[] { "peaceful", "easy", "normal", "hard" }.ToFrozenSet(StringComparer.OrdinalIgnoreCase);

    private static readonly FrozenSet<string> ValidGamemodes =
        new[] { "survival", "creative", "adventure", "spectator" }.ToFrozenSet(StringComparer.OrdinalIgnoreCase);

    /// <summary>
    /// 驗證單一設定屬性值是否合法
    /// </summary>
    /// <param name="key">設定屬性索引鍵</param>
    /// <param name="value">欲驗證之數值</param>
    /// <param name="defaultValue">該屬性之預設值（用於推導型別）</param>
    /// <returns>若合法回傳 (true, null)；若非法回傳 (false, 錯誤描述)</returns>
    public static (bool IsValid, string? Error) ValidateProperty(string key, string value, string defaultValue)
    {
        string val = value.Trim();

        // 1. server-ip 位址驗證
        if (string.Equals(key, "server-ip", StringComparison.OrdinalIgnoreCase))
        {
            if (string.IsNullOrEmpty(val))
            {
                return (true, null);
            }

            if (IsValidHostOrIp(val))
            {
                return (true, null);
            }

            return (false, "請填入有效的 IP 位址（如 127.0.0.1）或留空以綁定所有網路介面");
        }

        // 2. management-server-host 位址驗證
        if (string.Equals(key, "management-server-host", StringComparison.OrdinalIgnoreCase))
        {
            if (string.IsNullOrEmpty(val) || IsValidHostOrIp(val))
            {
                return (true, null);
            }

            return (false, "請填入有效的主機名稱或 IP 位址");
        }

        // 3. 連接埠範圍驗證 (1 ~ 65534)
        if (string.Equals(key, "server-port", StringComparison.OrdinalIgnoreCase) ||
            string.Equals(key, "query.port", StringComparison.OrdinalIgnoreCase) ||
            string.Equals(key, "rcon.port", StringComparison.OrdinalIgnoreCase))
        {
            if (!int.TryParse(val, out int port) || port < 1 || port > 65534)
            {
                return (false, $"連接埠 {key} 必須在 1 到 65534 之間");
            }

            return (true, null);
        }

        // 4. 管理端協定連接埠 (0 ~ 65535)
        if (string.Equals(key, "management-server-port", StringComparison.OrdinalIgnoreCase))
        {
            if (!int.TryParse(val, out int port) || port < 0 || port > 65535)
            {
                return (false, "管理端連接埠必須介於 0 到 65535 之間（0 為隨機指派）");
            }

            return (true, null);
        }

        // 5. 最大玩家數量驗證
        if (string.Equals(key, "max-players", StringComparison.OrdinalIgnoreCase))
        {
            if (!int.TryParse(val, out int mp) || mp < 0)
            {
                return (false, "最大玩家數量必須為大於或等於 0 的整數");
            }

            return (true, null);
        }

        // 6. 視野與模擬距離驗證 (2 ~ 32)
        if (string.Equals(key, "view-distance", StringComparison.OrdinalIgnoreCase) ||
            string.Equals(key, "simulation-distance", StringComparison.OrdinalIgnoreCase))
        {
            if (!int.TryParse(val, out int dist) || dist < 2 || dist > 32)
            {
                return (false, "距離必須介於 2 到 32 之間");
            }

            return (true, null);
        }

        // 7. 實體廣播範圍百分比 (10 ~ 1000)
        if (string.Equals(key, "entity-broadcast-range-percentage", StringComparison.OrdinalIgnoreCase))
        {
            if (!int.TryParse(val, out int pct) || pct < 10 || pct > 1000)
            {
                return (false, "實體廣播百分比必須介於 10 到 1000 之間");
            }

            return (true, null);
        }

        // 8. 遊戲難度選單驗證
        if (string.Equals(key, "difficulty", StringComparison.OrdinalIgnoreCase))
        {
            if (!ValidDifficulties.Contains(val))
            {
                return (false, "難度必須為 peaceful、easy、normal 或 hard");
            }

            return (true, null);
        }

        // 9. 遊戲模式選單驗證
        if (string.Equals(key, "gamemode", StringComparison.OrdinalIgnoreCase))
        {
            if (!ValidGamemodes.Contains(val))
            {
                return (false, "遊戲模式必須為 survival、creative、adventure 或 spectator");
            }

            return (true, null);
        }

        // 10. 權限等級驗證 (0 ~ 4)
        if (string.Equals(key, "function-permission-level", StringComparison.OrdinalIgnoreCase) ||
            string.Equals(key, "op-permission-level", StringComparison.OrdinalIgnoreCase))
        {
            if (!int.TryParse(val, out int level) || level < 0 || level > 4)
            {
                return (false, "權限等級必須介於 0 到 4 之間");
            }

            return (true, null);
        }

        // 11. 依預設值判斷之布林型別驗證
        if (bool.TryParse(defaultValue, out _))
        {
            if (!bool.TryParse(val, out _))
            {
                return (false, "此設定僅允許填入 true 或 false");
            }

            return (true, null);
        }

        // 12. 依預設值判斷之整數型別驗證
        if (long.TryParse(defaultValue, out _))
        {
            if (!long.TryParse(val, out _))
            {
                return (false, "此設定必須填入整數數值");
            }

            return (true, null);
        }

        return (true, null);
    }

    private static bool IsValidHostOrIp(string val)
    {
        if (IPAddress.TryParse(val, out _))
        {
            return true;
        }

        bool looksLikeIp = true;
        foreach (char c in val)
        {
            if (c != '.' && !char.IsAsciiDigit(c))
            {
                looksLikeIp = false;
                break;
            }
        }

        if (looksLikeIp && val.Contains('.'))
        {
            return false;
        }

        if (string.Equals(val, "localhost", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        return Uri.CheckHostName(val) == UriHostNameType.Dns;
    }
}
