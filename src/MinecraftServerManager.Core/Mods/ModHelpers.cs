using System.Buffers;
using System.Text;
using System.Text.RegularExpressions;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Mods;

namespace MinecraftServerManager.Core.Mods;

/// <summary>模組檔名與識別字</summary>
public static partial class ModHelpers
{
    public const string Sha512HashAlgorithm = HashAlgorithmNames.Sha512;
    public const string Sha1HashAlgorithm = HashAlgorithmNames.Sha1;
    public const string PreferredHashAlgorithm = Sha512HashAlgorithm;
    public const string JarExtension = ".jar";
    public const string DisabledModExtension = ".jar.disabled";
    private static readonly SearchValues<char> FormattingChars = SearchValues.Create("\x1B§\\");

    /// <summary>檔名是否以 .jar 結尾（不分大小寫）</summary>
    public static bool IsJarFileName(ReadOnlySpan<char> fileName) =>
        fileName.EndsWith(JarExtension, StringComparison.OrdinalIgnoreCase);

    /// <summary>檔名是否為已停用模組（.jar.disabled）</summary>
    public static bool IsDisabledModFileName(ReadOnlySpan<char> fileName) =>
        fileName.EndsWith(DisabledModExtension, StringComparison.OrdinalIgnoreCase);

    /// <summary>是否為模組檔案（.jar 或 .jar.disabled）</summary>
    public static bool IsModFileName(ReadOnlySpan<char> fileName) =>
        IsJarFileName(fileName) || IsDisabledModFileName(fileName);

    /// <summary>由模組檔名主幹組成啟用中模組檔名（stem.jar）</summary>
    public static string ToEnabledModFileName(ReadOnlySpan<char> stem) => string.Concat(stem, JarExtension);

    /// <summary>由模組檔名主幹組成已停用模組檔名（stem.jar.disabled）</summary>
    public static string ToDisabledModFileName(ReadOnlySpan<char> stem) => string.Concat(stem, DisabledModExtension);

    public static string ModFilenameStem(string? filename) =>
        ModFilenameStem((filename ?? string.Empty).AsSpan()).ToString();

    public static ReadOnlySpan<char> ModFilenameStem(ReadOnlySpan<char> filename)
    {
        ReadOnlySpan<char> raw = filename.Trim();
        if (IsDisabledModFileName(raw))
        {
            return raw[..^DisabledModExtension.Length];
        }
        if (IsJarFileName(raw))
        {
            return raw[..^JarExtension.Length];
        }
        return raw;
    }

    /// <summary>挑選最佳雜湊值（優先 sha512，次選 sha1）與演算法名稱；無可用雜湊時演算法為空字串</summary>
    public static string? ResolveHash(ModFile? file, out string algorithm)
    {
        if (TryGetHash(file, Sha512HashAlgorithm, out string? sha512))
        {
            algorithm = Sha512HashAlgorithm;
            return sha512;
        }

        if (TryGetHash(file, Sha1HashAlgorithm, out string? sha1))
        {
            algorithm = Sha1HashAlgorithm;
            return sha1;
        }

        algorithm = string.Empty;
        return null;
    }

    /// <summary>目前雜湊是否與線上檔案的 sha512 或 sha1 任一相符（不分大小寫）</summary>
    public static bool HashMatches(ModFile? file, string? currentHash) =>
        !string.IsNullOrWhiteSpace(currentHash) &&
        ((TryGetHash(file, Sha512HashAlgorithm, out string? sha512) && string.Equals(currentHash, sha512, StringComparison.OrdinalIgnoreCase)) ||
         (TryGetHash(file, Sha1HashAlgorithm, out string? sha1) && string.Equals(currentHash, sha1, StringComparison.OrdinalIgnoreCase)));

    public static string NormalizeIdentifier(string? value) =>
        (value ?? string.Empty).Trim().ToLowerInvariant();

    /// <summary>清除 ANSI 跳脫序列與 Minecraft 格式化代碼；null 回傳空字串，其餘空白原樣保留</summary>
    public static string StripColorAndFormattingCodes(string? text)
    {
        if (string.IsNullOrEmpty(text) || !text.AsSpan().ContainsAny(FormattingChars))
        {
            return text ?? string.Empty;
        }

        return ColorAndFormattingCodeRegex().Replace(text, string.Empty);
    }

    /// <summary>取得線上模組版本所宣告之必要相依性 Project ID 清單</summary>
    public static IReadOnlyList<string> GetRequiredDependencyIds(OnlineModVersion version)
    {
        ArgumentNullException.ThrowIfNull(version);
        if (version.Dependencies.Count == 0)
        {
            return [];
        }

        var result = new List<string>(version.Dependencies.Count);
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var dep in version.Dependencies)
        {
            if (dep.DependencyType == ModDependencyType.Required &&
                !string.IsNullOrWhiteSpace(dep.ProjectId) &&
                seen.Add(dep.ProjectId))
            {
                result.Add(dep.ProjectId);
            }
        }

        return result;
    }

    public static string NormalizeModSearchQuery(string? rawQuery)
    {
        if (string.IsNullOrWhiteSpace(rawQuery))
        {
            return string.Empty;
        }

        ReadOnlySpan<char> stemSpan = ModFilenameStem(rawQuery.AsSpan());
        string clean = StripColorAndFormattingCodes(stemSpan.ToString());
        clean = CamelCaseRegex().Replace(clean, " ");
        clean = CamelCaseAcronymBoundaryRegex().Replace(clean, " ");

        // 單趟替換符號並移除噪音詞
        clean = string.Create(clean.Length, clean, static (span, source) =>
        {
            for (int i = 0; i < source.Length; i++)
            {
                char c = source[i];
                span[i] = c is '_' or '-' or '+' ? ' ' : c;
            }
        });
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

        return sb.Length > 0 ? sb.ToString() : stemSpan.ToString();
    }

    /// <summary>不分大小寫查詢雜湊表，空白值視為不存在</summary>
    private static bool TryGetHash(ModFile? file, string algorithm, out string? hash)
    {
        hash = null;
        if (file?.Hashes is not { } hashes)
        {
            return false;
        }

        if (!hashes.TryGetValue(algorithm, out hash))
        {
            foreach (var (key, value) in hashes)
            {
                if (string.Equals(key, algorithm, StringComparison.OrdinalIgnoreCase))
                {
                    hash = value;
                    break;
                }
            }
        }

        return !string.IsNullOrWhiteSpace(hash);
    }

    // 小寫或數字後接大寫的零寬度邊界，例如 "JustEnoughItems" -> "Just Enough Items"
    [GeneratedRegex(@"(?<=[a-z0-9])(?=[A-Z])", RegexOptions.CultureInvariant)]
    private static partial Regex CamelCaseRegex();

    // 處理連續大寫字母後接一個「大寫+小寫」單字的邊界，例如 "XMLParser" -> "XML Parser"
    [GeneratedRegex(@"(?<=[A-Z])(?=[A-Z][a-z])", RegexOptions.CultureInvariant)]
    private static partial Regex CamelCaseAcronymBoundaryRegex();

    [GeneratedRegex(
        @"\b(?:fabric|forge|loader|quilt|neoforge|beta|alpha|rc|pre|snapshot|build|patch)(?:[0-9.-]+)?\b|\bmc\s*[0-9]+(?:\.[0-9]+){1,2}[a-z0-9.-]*\b|\b[0-9]+(?:\.[0-9]+){1,3}[a-z0-9.-]*\b",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex CombinedModNoiseRegex();

    // ANSI 跳脫序列（含字面 \u001b、\x1b）、§x 十六進位色碼、§ 單碼（含 §x、§z）與字面 \u00a7 形式
    [GeneratedRegex(
        @"(?:\x1B|(?i:\\u001b|\\x1b))(?:\[[0-?]*[ -/]*[@-~]|\].*?(?:\x07|\x1B\\)|[@-Z\\-_])|§x(?:§[0-9a-fA-F]){6}|§[0-9a-fk-orxzA-FK-ORXZ]|(?i:\\u00a7(?:x(?:\\u00a7[0-9a-f]){6}|[0-9a-fk-orxz]))",
        RegexOptions.CultureInvariant)]
    private static partial Regex ColorAndFormattingCodeRegex();
}
