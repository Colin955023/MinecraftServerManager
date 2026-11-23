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
    private static readonly string CachedUserProfileEscaped = CachedUserProfile.Replace(@"\", @"\\", StringComparison.Ordinal);

    private static readonly SearchValues<string> SensitiveKeywords =
        SearchValues.Create(["pass", "pwd", "secret", "token", "key", "bearer", "basic", "auth", "cookie", "://"], StringComparison.OrdinalIgnoreCase);

    // Cookie／Authorization 標頭整行遮罩
    [GeneratedRegex(@"(?i)\b((?:set-)?cookie|authorization)(\s*[=:]\s*)[^\r\n]+")]
    private static partial Regex SensitiveHeaderRegex();

    // 鍵值對：支援 JSON 與單雙引號鍵、=／: 或空白分隔，以及引號包住的值
    [GeneratedRegex(@"(?i)([""']?(?:password|passwd|pwd|secret|client[_-]?secret|private[_-]?key|token|api[_-]?key|access[_-]?key)[""']?)(\s*[=:]\s*|\s+)([""']?)[^\s,;""'&}]+")]
    private static partial Regex SensitiveKeyValueRegex();

    // Bearer 與 Basic 驗證（含 Base64 與 JWT 字元）
    [GeneratedRegex(@"(?i)\b(bearer|basic)\s+[A-Za-z0-9\-._~+/]+=*")]
    private static partial Regex AuthSchemeRegex();

    // URL 內嵌帳密 scheme://user:pass@host
    [GeneratedRegex(@"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@")]
    private static partial Regex UrlCredentialRegex();

    /// <summary>遮罩字串中潛在的敏感資訊（密碼、token、金鑰、驗證標頭、URL 帳密、使用者目錄）</summary>
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
                .Replace(CachedUserProfileEscaped, "~", StringComparison.OrdinalIgnoreCase)
                .Replace(CachedUserProfile, "~", StringComparison.OrdinalIgnoreCase)
                .Replace(CachedUserProfileSlash, "~", StringComparison.OrdinalIgnoreCase);
        }

        if (!masked.AsSpan().ContainsAny(SensitiveKeywords))
        {
            return masked;
        }

        masked = SensitiveHeaderRegex().Replace(masked, "$1$2" + MaskReplacement);
        masked = SensitiveKeyValueRegex().Replace(masked, "$1$2$3" + MaskReplacement);
        masked = AuthSchemeRegex().Replace(masked, "$1 " + MaskReplacement);
        return UrlCredentialRegex().Replace(masked, "$1" + MaskReplacement + ":" + MaskReplacement + "@");
    }
}
