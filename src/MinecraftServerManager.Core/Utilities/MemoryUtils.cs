using System.Globalization;
using System.Text.RegularExpressions;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.Core.Utilities;

/// <summary>
/// 記憶體驗證與正規化結果
/// </summary>
public sealed record MemoryValidationResult
{
    public bool IsValid { get; init; }
    public int MemoryMaxMb { get; init; }
    public int? MemoryMinMb { get; init; }
    public bool AdjustedMax { get; init; }
    public bool AdjustedMin { get; init; }
    public string? ErrorMessage { get; init; }
    public IReadOnlyList<string> WarningMessages { get; init; }

    public MemoryValidationResult(
        bool isValid,
        int memoryMaxMb = 0,
        int? memoryMinMb = null,
        bool adjustedMax = false,
        bool adjustedMin = false,
        string? errorMessage = null,
        IEnumerable<string>? warningMessages = null)
    {
        IsValid = isValid;
        MemoryMaxMb = memoryMaxMb;
        MemoryMinMb = memoryMinMb;
        AdjustedMax = adjustedMax;
        AdjustedMin = adjustedMin;
        ErrorMessage = errorMessage;
        WarningMessages = [.. warningMessages ?? []];
    }

    public static MemoryValidationResult Valid(
        int memoryMaxMb,
        int? memoryMinMb = null,
        bool adjustedMax = false,
        bool adjustedMin = false,
        IEnumerable<string>? warningMessages = null) =>
        new(true, memoryMaxMb, memoryMinMb, adjustedMax, adjustedMin, null, warningMessages);

    public static MemoryValidationResult Invalid(string errorMessage) =>
        new(false, errorMessage: errorMessage);
}

/// <summary>
/// 伺服器記憶體工具類別
/// </summary>
public static partial class MemoryUtils
{
    [GeneratedRegex(@"-(Xmx|Xms)(\d+)([kmgt]?)\b", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex XmxPattern();

    [GeneratedRegex(@"-Xmx[0-9]+[kmgt]?\b", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex XmxFlagRegex();

    [GeneratedRegex(@"-Xms[0-9]+[kmgt]?\b", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex XmsFlagRegex();

    /// <summary>
    /// 取得系統實體記憶體總量（MB）
    /// </summary>
    public static int GetTotalSystemMemoryMb()
    {
        long memoryBytes = GC.GetGCMemoryInfo().TotalAvailableMemoryBytes;
        return memoryBytes > 0 ? (int)(memoryBytes / (1024L * 1024L)) : 0;
    }

    /// <summary>
    /// 解析 Java 記憶體參數（-Xmx 或 -Xms）。若同一段文字出現多次相同參數，依 JVM 規範以最後一個為準。
    /// </summary>
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
                'g' => value * 1024,
                't' => value * 1024 * 1024,
                _ => value
            };

            if (megabytes is >= 0 and <= int.MaxValue)
            {
                parsedResult = (int)megabytes;
            }
        }

        return parsedResult;
    }

    /// <summary>
    /// 取得實際生效之最小記憶體（MB）：未指定時取預設值與最大記憶體之較小者
    /// </summary>
    public static int ResolveEffectiveMinMemoryMb(int? memoryMinMb, int memoryMaxMb) =>
        memoryMinMb ?? Math.Min(ServerDefaults.DefaultMemoryMinMb, memoryMaxMb);

    /// <summary>
    /// 將啟動腳本內容中的 -Xmx／-Xms 參數改寫為指定 MB 值；缺少 -Xms 時插入於第一個 -Xmx 之前。
    /// </summary>
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
    /// 驗證並正規化伺服器記憶體設定
    /// </summary>
    public static MemoryValidationResult ValidateAndNormalizeServerMemory(
        string? maxMemoryText,
        string? minMemoryText = "",
        int totalMemoryMb = 0)
    {
        string maxStr = maxMemoryText?.Trim() ?? string.Empty;
        string minStr = minMemoryText?.Trim() ?? string.Empty;

        if (!int.TryParse(maxStr, CultureInfo.InvariantCulture, out int maxMb))
        {
            return MemoryValidationResult.Invalid("最大記憶體必須是數字");
        }

        if (maxMb < 1024)
        {
            return MemoryValidationResult.Invalid("最大記憶體不可低於 1024 MB");
        }

        bool adjustedMax = false;
        var warnings = new List<string>();

        if (totalMemoryMb > 0 && maxMb > totalMemoryMb)
        {
            maxMb = totalMemoryMb;
            adjustedMax = true;
            warnings.Add($"最大記憶體超出系統總實體記憶體 ({totalMemoryMb} MB)，已自動調整為上限值 {totalMemoryMb} MB");
        }

        int? minMb = null;
        bool adjustedMin = false;

        if (!string.IsNullOrEmpty(minStr))
        {
            if (!int.TryParse(minStr, CultureInfo.InvariantCulture, out int parsedMinMb))
            {
                return MemoryValidationResult.Invalid("最小記憶體必須是數字");
            }

            if (parsedMinMb <= 0)
            {
                return MemoryValidationResult.Invalid("最小記憶體必須大於 0");
            }

            minMb = parsedMinMb;

            if (totalMemoryMb > 0 && minMb.Value > totalMemoryMb)
            {
                minMb = totalMemoryMb;
                adjustedMin = true;
                warnings.Add($"最小記憶體超出系統總實體記憶體 ({totalMemoryMb} MB)，已自動調整為上限值 {totalMemoryMb} MB");
            }

            if (minMb.Value > maxMb)
            {
                return MemoryValidationResult.Invalid("最小記憶體不可大於最大記憶體");
            }
        }

        return MemoryValidationResult.Valid(maxMb, minMb, adjustedMax, adjustedMin, warnings);
    }
}
