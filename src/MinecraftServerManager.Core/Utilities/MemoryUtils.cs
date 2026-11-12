using System.Globalization;
using System.Text.RegularExpressions;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.Core.Utilities;

/// <summary>記憶體設定檢查等級</summary>
public enum MemoryCheckLevel
{
    Ok,
    Warning,
    Error,
}

/// <summary>記憶體設定檢查結果（Error 不可儲存；Warning 可儲存但需提示）</summary>
public readonly record struct MemoryCheckResult(MemoryCheckLevel Level, string Message, int MaxMb = 0, int? MinMb = null);

/// <summary>伺服器記憶體工具類別</summary>
public static partial class MemoryUtils
{
    [GeneratedRegex(@"-(Xmx|Xms)(\d+)([kmgt]?)\b", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex XmxPattern();

    [GeneratedRegex(@"-Xmx[0-9]+[kmgt]?\b", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex XmxFlagRegex();

    [GeneratedRegex(@"-Xms[0-9]+[kmgt]?\b", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex XmsFlagRegex();

    /// <summary>取得系統實體記憶體總量（MB）</summary>
    public static int GetTotalSystemMemoryMb()
    {
        long memoryBytes = GC.GetGCMemoryInfo().TotalAvailableMemoryBytes;
        return memoryBytes > 0 ? (int)(memoryBytes / (1024L * 1024L)) : 0;
    }

    /// <summary>解析 Java 記憶體參數（-Xmx 或 -Xms）。若同一段文字出現多次相同參數，依 JVM 規範以最後一個為準。</summary>
    public static int? ParseMemorySetting(string? text, string settingType = "Xmx")
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return null;
        }

        int? parsedResult = null;
        ReadOnlySpan<char> span = text.AsSpan();
        foreach (var match in XmxPattern().EnumerateMatches(span))
        {
            ReadOnlySpan<char> matched = span.Slice(match.Index, match.Length);
            if (matched.Length <= 4 || matched[0] != '-')
            {
                continue;
            }

            ReadOnlySpan<char> matchedType = matched.Slice(1, 3);
            if (!matchedType.Equals(settingType, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            ReadOnlySpan<char> remainder = matched[4..];
            if (remainder.IsEmpty)
            {
                continue;
            }

            char unit = char.ToLowerInvariant(remainder[^1]);
            bool hasUnit = unit is 'k' or 'm' or 'g' or 't';
            ReadOnlySpan<char> digits = hasUnit ? remainder[..^1] : remainder;
            if (!long.TryParse(digits, CultureInfo.InvariantCulture, out long value))
            {
                continue;
            }

            long megabytes = unit switch
            {
                'k' => value / 1024,
                // 乘法前先檢查上限，避免溢位後意外落入合法範圍（-1 會被下方範圍檢查排除）
                'g' => value <= int.MaxValue / 1024 ? value * 1024 : -1,
                't' => value <= int.MaxValue / (1024 * 1024) ? value * 1024 * 1024 : -1,
                _ => value
            };

            if (megabytes is >= 0 and <= int.MaxValue)
            {
                parsedResult = (int)megabytes;
            }
        }

        return parsedResult;
    }

    /// <summary>取得實際生效之最小記憶體（MB）：未指定時取預設值與最大記憶體之較小者</summary>
    public static int ResolveEffectiveMinMemoryMb(int? memoryMinMb, int memoryMaxMb) =>
        memoryMinMb ?? Math.Min(ServerDefaults.DefaultMemoryMinMb, memoryMaxMb);

    /// <summary>將啟動腳本內容中的 -Xmx／-Xms 參數改寫為指定 MB 值；缺少 -Xms 時插入於第一個 -Xmx 之前。</summary>
    public static string ApplyMemoryFlags(string content, int minMb, int maxMb)
    {
        ArgumentNullException.ThrowIfNull(content);

        bool hasXmx = XmxFlagRegex().IsMatch(content);
        bool hasXms = XmsFlagRegex().IsMatch(content);

        if (hasXmx)
        {
            content = XmxFlagRegex().Replace(content, $"-Xmx{maxMb}M");
        }

        if (hasXms)
        {
            content = XmsFlagRegex().Replace(content, $"-Xms{minMb}M");
        }
        else if (hasXmx)
        {
            content = XmxFlagRegex().Replace(content, match => $"-Xms{minMb}M " + match.Value, 1);
        }

        return content;
    }

    /// <summary>
    /// 檢查伺服器記憶體設定文字（建立伺服器與調整記憶體共用同一套規則）；
    /// <paramref name="clampToSystem"/> 為 true 時超出系統總記憶體之數值自動調降為上限並回傳警告，否則視為錯誤
    /// </summary>
    public static MemoryCheckResult CheckServerMemory(string? maxMemoryText, string? minMemoryText, long systemMemoryMb, bool clampToSystem = false)
    {
        if (!int.TryParse(maxMemoryText?.Trim(), CultureInfo.InvariantCulture, out int maxMb) || maxMb <= 0)
        {
            return new(MemoryCheckLevel.Error, "最大記憶體必須為大於 0 的整數 (MB)");
        }

        int? minMb = null;
        if (!string.IsNullOrWhiteSpace(minMemoryText))
        {
            if (!int.TryParse(minMemoryText.Trim(), CultureInfo.InvariantCulture, out int parsedMin) || parsedMin <= 0)
            {
                return new(MemoryCheckLevel.Error, "最小記憶體必須為大於 0 的整數 (MB)");
            }

            if (parsedMin > maxMb)
            {
                return new(MemoryCheckLevel.Error, "最小記憶體不可大於最大記憶體");
            }

            minMb = parsedMin;
        }

        if (systemMemoryMb > 0)
        {
            int peak = Math.Max(maxMb, minMb ?? 0);
            if (peak > systemMemoryMb)
            {
                if (!clampToSystem)
                {
                    return new(MemoryCheckLevel.Error, $"設定記憶體超過系統總記憶體 ({systemMemoryMb} MB)", maxMb, minMb);
                }

                int limit = (int)Math.Min(systemMemoryMb, int.MaxValue);
                return new(
                    MemoryCheckLevel.Warning,
                    $"設定記憶體超出系統總實體記憶體 ({systemMemoryMb} MB)，已自動調整為上限值 {limit} MB",
                    Math.Min(maxMb, limit),
                    minMb is { } min ? Math.Min(min, limit) : null);
            }

            if (peak > systemMemoryMb / 2)
            {
                return new(MemoryCheckLevel.Warning, $"設定記憶體超過系統記憶體的一半 ({systemMemoryMb / 2} MB)", maxMb, minMb);
            }
        }

        return new(MemoryCheckLevel.Ok, string.Empty, maxMb, minMb);
    }
}
