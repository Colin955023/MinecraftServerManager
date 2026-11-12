using System.Buffers;
using System.Text.RegularExpressions;

using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Logging;

/// <summary>記錄敏感資訊遮罩工具</summary>
public static partial class LogDataMasker
{
    private const string MaskReplacement = "***";
    private static readonly string CachedUserProfile = RuntimePaths.GetUserProfileDir();
    private static readonly string CachedUserProfileSlash = CachedUserProfile.Replace('\\', '/');

    private static readonly SearchValues<string> SensitiveKeywords =
        SearchValues.Create(["pass", "pwd", "secret", "token", "key", "bearer"], StringComparison.OrdinalIgnoreCase);

    [GeneratedRegex(@"(?i)(password|passwd|pwd|secret|token|api[_-]?key)\s*([=:]|\s+)\s*([^\s,;""'&]+)")]
    private static partial Regex SensitiveKeyValueRegex();

    [GeneratedRegex(@"(?i)(bearer\s+)[a-zA-Z0-9_\-\.]+")]
    private static partial Regex BearerTokenRegex();

    /// <summary>遮罩字串中潛在的敏感資訊（密碼、token、金鑰等）</summary>
    public static string Mask(string? message)
    {
        if (string.IsNullOrEmpty(message))
        {
            return string.Empty;
        }

        string masked = message;
        if (!string.IsNullOrEmpty(CachedUserProfile))
        {
            masked = masked
                .Replace(CachedUserProfile, "~", StringComparison.OrdinalIgnoreCase)
                .Replace(CachedUserProfileSlash, "~", StringComparison.OrdinalIgnoreCase);
        }

        if (!MayContainSensitiveData(masked))
        {
            return masked;
        }

        masked = SensitiveKeyValueRegex().Replace(masked, "$1$2" + MaskReplacement);
        return BearerTokenRegex().Replace(masked, "$1" + MaskReplacement);
    }

    private static bool MayContainSensitiveData(string text) =>
        text.AsSpan().ContainsAny(SensitiveKeywords);
}
