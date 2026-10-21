using System.Globalization;
using System.Text.Json.Serialization;

namespace MinecraftServerManager.Domain.Servers;

/// <summary>
/// 伺服器名單時間格式化工具（統一以 GMT+8 台灣時區顯示 yyyy-MM-dd HH:mm:ss）
/// </summary>
public static class ServerPlayerTimeFormatter
{
    private static readonly TimeSpan Gmt8Offset = TimeSpan.FromHours(8);

    public static string FormatToGmt8(string? rawTime)
    {
        if (string.IsNullOrWhiteSpace(rawTime))
        {
            return string.Empty;
        }

        if (DateTimeOffset.TryParse(rawTime, CultureInfo.InvariantCulture, DateTimeStyles.None, out var dto))
        {
            return dto.ToOffset(Gmt8Offset).ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture);
        }

        return rawTime;
    }
}

/// <summary>
/// 伺服器本地玩家連線快取項目 (usercache.json)
/// </summary>
public sealed record ServerUserCacheEntry(
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("uuid")] string Uuid,
    [property: JsonPropertyName("expiresOn")] string? ExpiresOn)
{
    [JsonIgnore]
    public string FormattedExpiresOn => ServerPlayerTimeFormatter.FormatToGmt8(ExpiresOn);
}

/// <summary>
/// 伺服器營運管理員設定項目 (ops.json)
/// </summary>
public sealed record ServerOperatorEntry(
    [property: JsonPropertyName("uuid")] string Uuid,
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("level")] int Level,
    [property: JsonPropertyName("bypassesPlayerLimit")] bool BypassesPlayerLimit);

/// <summary>
/// 伺服器白名單項目 (whitelist.json)
/// </summary>
public sealed record ServerWhitelistEntry(
    [property: JsonPropertyName("uuid")] string Uuid,
    [property: JsonPropertyName("name")] string Name);

/// <summary>
/// 伺服器封鎖玩家項目 (banned-players.json)
/// </summary>
public sealed record ServerBannedPlayerEntry(
    [property: JsonPropertyName("uuid")] string Uuid,
    [property: JsonPropertyName("name")] string Name,
    [property: JsonPropertyName("created")] string Created,
    [property: JsonPropertyName("source")] string Source,
    [property: JsonPropertyName("expires")] string Expires,
    [property: JsonPropertyName("reason")] string Reason)
{
    [JsonIgnore]
    public string FormattedCreated => ServerPlayerTimeFormatter.FormatToGmt8(Created);

    [JsonIgnore]
    public string FormattedExpires => ServerPlayerTimeFormatter.FormatToGmt8(Expires);
}

/// <summary>
/// 伺服器封鎖 IP 項目 (banned-ips.json)
/// </summary>
public sealed record ServerBannedIpEntry(
    [property: JsonPropertyName("ip")] string Ip,
    [property: JsonPropertyName("created")] string Created,
    [property: JsonPropertyName("source")] string Source,
    [property: JsonPropertyName("expires")] string Expires,
    [property: JsonPropertyName("reason")] string Reason)
{
    [JsonIgnore]
    public string FormattedCreated => ServerPlayerTimeFormatter.FormatToGmt8(Created);

    [JsonIgnore]
    public string FormattedExpires => ServerPlayerTimeFormatter.FormatToGmt8(Expires);
}

/// <summary>
/// 伺服器玩家與設定檔案完整集合套件
/// </summary>
public sealed record ServerPlayerConfigBundle(
    IReadOnlyList<ServerUserCacheEntry> UserCache,
    IReadOnlyList<ServerOperatorEntry> Operators,
    IReadOnlyList<ServerWhitelistEntry> Whitelist,
    IReadOnlyList<ServerBannedPlayerEntry> BannedPlayers,
    IReadOnlyList<ServerBannedIpEntry> BannedIps);
