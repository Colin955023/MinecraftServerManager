using System.Collections.Concurrent;
using System.Globalization;

namespace MinecraftServerManager.App.Controls;

/// <summary>玩家名單時間顯示：轉為使用者本機時區（yyyy-MM-dd HH:mm:ss）並快取結果</summary>
public static class PlayerTimeFormatter
{
    private const int MaxCacheEntries = 2048;
    private static readonly ConcurrentDictionary<string, string> Cache = new(StringComparer.Ordinal);

    /// <summary>格式化名單檔原始時間字串；無法解析時原樣回傳</summary>
    public static string Format(string? rawTime)
    {
        if (string.IsNullOrWhiteSpace(rawTime))
        {
            return string.Empty;
        }

        if (Cache.TryGetValue(rawTime, out string? cached))
        {
            return cached;
        }

        string formatted = DateTimeOffset.TryParse(rawTime, CultureInfo.InvariantCulture, DateTimeStyles.None, out var dto)
            ? dto.ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture)
            : rawTime;

        if (Cache.Count >= MaxCacheEntries)
        {
            Cache.Clear();
        }

        Cache[rawTime] = formatted;
        return formatted;
    }
}
