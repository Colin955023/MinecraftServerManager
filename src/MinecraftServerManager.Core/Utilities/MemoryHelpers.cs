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
public static partial class MemoryHelpers
{
    // 須位於開頭、空白或引號之後，並以結尾、空白或引號收尾，避免誤抓 -XX:MaxRAM 等其他參數片段
    [GeneratedRegex(@"(?<=^|[\s""'])-(?<type>Xmx|Xms)(?<value>[0-9]+)(?<unit>[kmgt]?)(?=$|[\s""'])", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex MemoryFlagPattern();

    [GeneratedRegex(@"(?<=^|[\s""'])-Xmx[0-9]+[kmgt]?(?=$|[\s""'])", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex XmxFlagRegex();

    [GeneratedRegex(@"(?<=^|[\s""'])-Xms[0-9]+[kmgt]?(?=$|[\s""'])", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex XmsFlagRegex();

    // 受管腳本 java 行：-Xmx 之後到 -jar／@引數檔之間為自訂 JVM 參數
    [GeneratedRegex(@"(?<head>-Xmx[0-9]+[KkMmGgTt]?\s+)(?<extra>.*?)(?<tail>-jar\s|@"")", RegexOptions.CultureInvariant)]
    private static partial Regex ScriptJvmArgsRegex();

    /// <summary>以 <paramref name="extraArgs"/> 取代受管腳本中 -Xmx 與 -jar／@引數檔之間的自訂 JVM 參數；非受管格式回傳 false</summary>
    public static bool TryReplaceScriptJvmArgs(string content, string extraArgs, out string updated)
    {
        ArgumentNullException.ThrowIfNull(content);
        ArgumentNullException.ThrowIfNull(extraArgs);
        Match match = ScriptJvmArgsRegex().Match(content);
        if (!match.Success)
        {
            updated = content;
            return false;
        }

        Group extraGroup = match.Groups["extra"];
        updated = string.Concat(
            content.AsSpan(0, extraGroup.Index),
            extraArgs,
            content.AsSpan(extraGroup.Index + extraGroup.Length));
        return true;
    }

    /// <summary>取得系統實體記憶體總量（MB）</summary>
    public static long GetTotalSystemMemoryMb()
    {
        long memoryBytes = GC.GetGCMemoryInfo().TotalAvailableMemoryBytes;
        return memoryBytes > 0 ? memoryBytes / (1024L * 1024L) : 0;
    }

    /// <summary>解析 -Xmx 或 -Xms（無單位為位元組）；出現多次時以最後一個有效值為準，換算後小於 1 MB 或溢位者忽略</summary>
    public static int? ParseMemorySetting(string? text, string settingType = "Xmx")
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return null;
        }

        int? parsedResult = null;
        foreach (Match match in MemoryFlagPattern().Matches(text))
        {
            if (!match.Groups["type"].ValueSpan.Equals(settingType, StringComparison.OrdinalIgnoreCase)
                || !long.TryParse(match.Groups["value"].ValueSpan, NumberStyles.None, CultureInfo.InvariantCulture, out long value))
            {
                continue;
            }

            ReadOnlySpan<char> unitSpan = match.Groups["unit"].ValueSpan;
            char unit = unitSpan.IsEmpty ? '\0' : char.ToLowerInvariant(unitSpan[0]);
            long megabytes = unit switch
            {
                '\0' => value / (1024L * 1024L),
                'k' => value / 1024,
                'm' => value,
                // 乘法前先檢查上限，避免溢位後意外落入合法範圍
                'g' => value <= int.MaxValue / 1024 ? value * 1024 : -1,
                _ => value <= int.MaxValue / (1024 * 1024) ? value * 1024 * 1024 : -1,
            };

            if (megabytes is > 0 and <= int.MaxValue)
            {
                parsedResult = (int)megabytes;
            }
        }

        return parsedResult;
    }

    /// <summary>取得實際生效之最小記憶體（MB）：未指定時取預設值與最大記憶體之較小者</summary>
    public static int ResolveEffectiveMinMemoryMb(int? memoryMinMb, int memoryMaxMb)
    {
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(memoryMaxMb);
        if (memoryMinMb is { } min)
        {
            ArgumentOutOfRangeException.ThrowIfNegativeOrZero(min, nameof(memoryMinMb));
            return min;
        }

        return Math.Min(ServerDefaults.DefaultMemoryMinMb, memoryMaxMb);
    }

    /// <summary>改寫啟動腳本的 -Xmx／-Xms；缺少 -Xms 時插入於第一個 -Xmx 前</summary>
    public static string ApplyMemoryFlags(string content, int minMb, int maxMb)
    {
        ArgumentNullException.ThrowIfNull(content);
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(minMb);
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(maxMb);
        ArgumentOutOfRangeException.ThrowIfGreaterThan(minMb, maxMb);

        string xmx = string.Create(CultureInfo.InvariantCulture, $"-Xmx{maxMb}M");
        string xms = string.Create(CultureInfo.InvariantCulture, $"-Xms{minMb}M");
        bool hasXms = XmsFlagRegex().IsMatch(content);

        if (hasXms)
        {
            content = XmsFlagRegex().Replace(content, xms);
            return XmxFlagRegex().Replace(content, xmx);
        }

        // 單趟掃描：第一個 -Xmx 前補上 -Xms
        bool inserted = false;
        return XmxFlagRegex().Replace(content, _ =>
        {
            if (inserted)
            {
                return xmx;
            }

            inserted = true;
            return xms + " " + xmx;
        });
    }

    /// <summary>檢查記憶體設定文字；<paramref name="clampToSystem"/> 為 true 時超出系統記憶體者自動調降並回傳警告</summary>
    public static MemoryCheckResult CheckServerMemory(string? maxMemoryText, string? minMemoryText, long systemMemoryMb, bool clampToSystem = false)
    {
        if (!int.TryParse(maxMemoryText.AsSpan().Trim(), CultureInfo.InvariantCulture, out int maxMb) || maxMb <= 0)
        {
            return new(MemoryCheckLevel.Error, "最大記憶體必須為大於 0 的整數 (MB)");
        }

        int? minMb = null;
        ReadOnlySpan<char> minSpan = minMemoryText.AsSpan().Trim();
        if (!minSpan.IsEmpty)
        {
            if (!int.TryParse(minSpan, CultureInfo.InvariantCulture, out int parsedMin) || parsedMin <= 0)
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
            if (maxMb > systemMemoryMb)
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

            if (maxMb > systemMemoryMb / 2)
            {
                return new(MemoryCheckLevel.Warning, $"設定記憶體超過系統記憶體的一半 ({systemMemoryMb / 2} MB)", maxMb, minMb);
            }
        }

        return new(MemoryCheckLevel.Ok, string.Empty, maxMb, minMb);
    }
}
