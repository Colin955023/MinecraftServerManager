using System.Globalization;
using System.Text.RegularExpressions;

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
    [GeneratedRegex(@"-(Xmx|Xms)(\d+)([mMgG]?)", RegexOptions.CultureInvariant)]
    private static partial Regex XmxPattern();

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

            char last = remainder[^1];
            bool hasUnit = last is 'g' or 'G' or 'm' or 'M';
            ReadOnlySpan<char> digits = hasUnit ? remainder[..^1] : remainder;
            if (!int.TryParse(digits, CultureInfo.InvariantCulture, out int value))
            {
                continue;
            }

            parsedResult = (hasUnit && (last is 'g' or 'G'))
                ? value * 1024
                : value;
        }

        return parsedResult;
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
