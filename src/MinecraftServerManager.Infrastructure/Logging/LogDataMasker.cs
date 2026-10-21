using System.Text.RegularExpressions;

namespace MinecraftServerManager.Infrastructure.Logging;

/// <summary>
/// 記錄敏感資訊遮罩工具
/// </summary>
public static partial class LogDataMasker
{
    private const string MaskReplacement = "***";
    private static readonly string CachedUserProfile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
    private static readonly string CachedUserProfileSlash = CachedUserProfile.Replace('\\', '/');

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

        string masked = message;
        if (!string.IsNullOrEmpty(CachedUserProfile))
        {
            if (masked.Contains(CachedUserProfile, StringComparison.OrdinalIgnoreCase))
            {
                masked = masked.Replace(CachedUserProfile, "~", StringComparison.OrdinalIgnoreCase);
            }
            if (masked.Contains(CachedUserProfileSlash, StringComparison.OrdinalIgnoreCase))
            {
                masked = masked.Replace(CachedUserProfileSlash, "~", StringComparison.OrdinalIgnoreCase);
            }
        }

        if (!MayContainSensitiveData(masked))
        {
            return masked;
        }

        masked = SensitiveKeyValueRegex().Replace(masked, static match =>
        {
            string key = match.Groups[1].Value;
            string delimiter = match.Groups[2].Value;
            return $"{key}{delimiter}{MaskReplacement}";
        });

        masked = BearerTokenRegex().Replace(masked, static match =>
        {
            string prefix = match.Groups[1].Value;
            return $"{prefix}{MaskReplacement}";
        });

        return masked;
    }

    private static bool MayContainSensitiveData(string text) =>
        text.Contains("pass", StringComparison.OrdinalIgnoreCase) ||
        text.Contains("pwd", StringComparison.OrdinalIgnoreCase) ||
        text.Contains("secret", StringComparison.OrdinalIgnoreCase) ||
        text.Contains("token", StringComparison.OrdinalIgnoreCase) ||
        text.Contains("key", StringComparison.OrdinalIgnoreCase) ||
        text.Contains("bearer", StringComparison.OrdinalIgnoreCase);
}
