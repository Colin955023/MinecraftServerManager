using System.Text.RegularExpressions;

namespace MinecraftServerManager.Infrastructure.Logging;

/// <summary>
/// 日誌敏感資訊遮罩工具
/// </summary>
public static partial class LogDataMasker
{
    private const string MaskReplacement = "***";

    [GeneratedRegex(@"(?i)(password|passwd|pwd|secret|token|api[_-]?key)\s*([=:]|\s+)\s*([^\s,;""'&]+)")]
    private static partial Regex SensitiveKeyValueRegex();

    [GeneratedRegex(@"(?i)(bearer\s+)[a-zA-Z0-9_\-\.]+")]
    private static partial Regex BearerTokenRegex();

    /// <summary>
    /// 遮罩字串中潛在的敏感資訊（密碼、token、金鑰等）
    /// </summary>
    public static string Mask(string? message)
    {
        if (string.IsNullOrEmpty(message))
        {
            return string.Empty;
        }

        string masked = SensitiveKeyValueRegex().Replace(message, match =>
        {
            string key = match.Groups[1].Value;
            string delimiter = match.Groups[2].Value;
            return $"{key}{delimiter}{MaskReplacement}";
        });

        masked = BearerTokenRegex().Replace(masked, match =>
        {
            string prefix = match.Groups[1].Value;
            return $"{prefix}{MaskReplacement}";
        });

        return masked;
    }
}
