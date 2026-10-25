using System.Buffers;
using System.Text;
using System.Text.RegularExpressions;
using MinecraftServerManager.Domain.Mods;

namespace MinecraftServerManager.Core.Mods;

/// <summary>
/// 模組檔名與識別字輔助工具
/// </summary>
public static partial class ModHelpers
{
    public const string PreferredHashAlgorithm = "sha512";
    private static readonly SearchValues<char> FormattingChars = SearchValues.Create("\x1B§\\");

    public static string ModFilenameStem(string? filename)
    {
        string raw = (filename ?? string.Empty).Trim();
        if (raw.EndsWith(".jar.disabled", StringComparison.OrdinalIgnoreCase))
        {
            return raw[..^13];
        }
        if (raw.EndsWith(".jar", StringComparison.OrdinalIgnoreCase))
        {
            return raw[..^4];
        }
        return raw;
    }

    public static string NormalizeIdentifier(string? value) =>
        (value ?? string.Empty).Trim().ToLowerInvariant();

    /// <summary>
    /// 正規化雜湊演算法名稱字串（供外部輸入或驗證比對使用）
    /// </summary>
    public static string NormalizeHashAlgorithm(string? algorithm)
    {
        string norm = NormalizeIdentifier(algorithm);
        return norm is "sha512" or "sha256" or "sha1" ? norm : PreferredHashAlgorithm;
    }

    /// <summary>
    /// 清除字串中的 ANSI 跳脫序列（CSI、OSC、2-char ESC）以及 Minecraft 格式化代碼（§、\u00a7、Hex 格式）
    /// </summary>
    public static string StripColorAndFormattingCodes(string? text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return string.Empty;
        }

        if (!text.AsSpan().ContainsAny(FormattingChars))
        {
            return text;
        }

        return ColorAndFormattingCodeRegex().Replace(text, string.Empty);
    }

    public static string NormalizeModSearchQuery(string rawQuery)
    {
        if (string.IsNullOrWhiteSpace(rawQuery))
        {
            return string.Empty;
        }

        string clean = ModFilenameStem(rawQuery);
        clean = StripColorAndFormattingCodes(clean);
        clean = CamelCaseRegex().Replace(clean, " $1");
        clean = CamelCaseAcronymBoundaryRegex().Replace(clean, " ");
        clean = clean.Replace('_', ' ').Replace('-', ' ').Replace('+', ' ');
        clean = CombinedModNoiseRegex().Replace(clean, " ");

        var sb = new StringBuilder(clean.Length);
        foreach (var range in clean.AsSpan().Split(' '))
        {
            var word = clean.AsSpan(range);
            if (!word.IsEmpty)
            {
                if (sb.Length > 0)
                {
                    sb.Append(' ');
                }
                sb.Append(word);
            }
        }

        return sb.Length > 0 ? sb.ToString() : ModFilenameStem(rawQuery);
    }

    /// <summary>
    /// 判定版本類型是否為允許範圍
    /// </summary>
    public static bool IsAllowedVersionType(string? versionType)
    {
        string norm = NormalizeIdentifier(versionType);
        return norm is "" or "release" or "stable" || norm.Contains("beta", StringComparison.Ordinal);
    }

    /// <summary>
    /// 從線上模組版本集合中挑選優先級最高之最佳相容版本（供無相依環境之純獨立選版使用）
    /// </summary>
    public static OnlineModVersion? SelectBestModVersion(IEnumerable<OnlineModVersion> versions)
    {
        return versions
            .Select(static v => (Version: v, ParsedVersion: new FlexVersion(v.VersionNumber)))
            .OrderByDescending(static x => x.Version.PrimaryFile is not null ? 1 : 0)
            .ThenByDescending(static x => GetVersionTypePriority(x.Version.VersionType))
            .ThenByDescending(static x => x.Version.DatePublished)
            .ThenByDescending(static x => x.ParsedVersion)
            .Select(static x => x.Version)
            .FirstOrDefault();
    }

    private static int GetVersionTypePriority(string versionType)
    {
        string norm = NormalizeIdentifier(versionType);
        if (norm == "release")
        {
            return 3;
        }

        if (norm is "beta" or "snapshot")
        {
            return 2;
        }

        if (norm == "alpha")
        {
            return 1;
        }

        return 0;
    }

    [GeneratedRegex(@"(?<=[a-z0-9])([A-Z])")]
    private static partial Regex CamelCaseRegex();

    // 處理連續大寫字母後接一個「大寫+小寫」單字的邊界，例如 "XMLParser" -> "XML Parser"
    [GeneratedRegex(@"(?<=[A-Z])(?=[A-Z][a-z])")]
    private static partial Regex CamelCaseAcronymBoundaryRegex();

    [GeneratedRegex(@"(?i)\b(?:fabric|forge|loader|quilt|neoforge|beta|alpha|rc|pre|snapshot|build|patch)(?:[0-9.-]+)?\b|(?i)\bmc\s*\d+(?:\.\d+){1,2}[a-z0-9.-]*\b|\b\d+(?:\.\d+){1,3}[a-z0-9.-]*\b")]
    private static partial Regex CombinedModNoiseRegex();

    [GeneratedRegex(@"(?:\x1B|(?i)\\u001b|(?i)\\x1b)(?:\[[0-?]*[ -/]*[@-~]|\].*?(?:\x07|\x1B\\)|[@-Z\\-_])|§x(?:§[0-9a-fA-F]){6}|§[0-9a-fk-orA-FK-ORzZ]|(?i)\\u00a7[0-9a-fk-or]")]
    private static partial Regex ColorAndFormattingCodeRegex();
}
