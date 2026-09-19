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
        WarningMessages = (warningMessages ?? []).ToArray();
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
    [GeneratedRegex(@"-(Xmx|Xms)(\d+)([mMgG]?)")]
    private static partial Regex XmxPattern();

    /// <summary>
    /// 解析 Java 記憶體參數（-Xmx 或 -Xms）
    /// </summary>
    public static int? ParseMemorySetting(string? text, string settingType = "Xmx")
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return null;
        }

        var match = XmxPattern().Match(text);
        if (!match.Success)
        {
            return null;
        }

        string matchedType = match.Groups[1].Value;
        if (!string.Equals(matchedType, settingType, StringComparison.OrdinalIgnoreCase))
        {
            return null;
        }

        if (!int.TryParse(match.Groups[2].Value, CultureInfo.InvariantCulture, out int value))
        {
            return null;
        }

        string unit = match.Groups[3].Value;
        if (string.Equals(unit, "g", StringComparison.OrdinalIgnoreCase))
        {
            return value * 1024;
        }

        return value;
    }

    /// <summary>
    /// 格式化記憶體大小（MB）
    /// </summary>
    public static string FormatMemoryMb(int memoryMb, bool compact = true)
    {
        if (compact)
        {
            if (memoryMb >= 1024)
            {
                return memoryMb % 1024 == 0
                    ? $"{memoryMb / 1024}G"
                    : $"{memoryMb / 1024.0:F1}G";
            }
            return $"{memoryMb}M";
        }

        if (memoryMb >= 1024)
        {
            return $"{memoryMb / 1024.0:F1} GB";
        }
        return $"{memoryMb} MB";
    }

    /// <summary>
    /// 格式化位元組大小（B/KB/MB/GB）
    /// </summary>
    public static string FormatBytes(long bytes)
    {
        if (bytes < 0)
        {
            return "-";
        }
        if (bytes < 1024)
        {
            return $"{bytes} B";
        }
        double kb = bytes / 1024.0;
        if (kb < 1024)
        {
            return $"{kb:F1} KB";
        }
        double mb = kb / 1024.0;
        if (mb < 1024)
        {
            return $"{mb:F1} MB";
        }
        double gb = mb / 1024.0;
        return $"{gb:F2} GB";
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
