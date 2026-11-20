using System.Collections.Concurrent;
using System.Text.RegularExpressions;

namespace MinecraftServerManager.UnitTests.Architecture;
/// <summary>架構規則違反記錄項目</summary>
public sealed record SourceViolation(
    string FilePath,
    int LineNumber,
    string LineContent,
    string RuleId,
    string Message);

/// <summary>原始碼文字掃描、註解/字串清洗與架構違規偵測之共用工具</summary>
public static class SourceScanner
{
    private static readonly Lazy<string> SolutionRootLazy = new(ResolveSolutionRoot);

    /// <summary>取得專案儲存庫根目錄絕對路徑</summary>
    public static string SolutionRoot => SolutionRootLazy.Value;

    private static string ResolveSolutionRoot()
    {
        string? current = AppContext.BaseDirectory;
        while (!string.IsNullOrEmpty(current))
        {
            if (File.Exists(Path.Combine(current, "MinecraftServerManager.slnx")) ||
                File.Exists(Path.Combine(current, "Directory.Build.props")))
            {
                return Path.GetFullPath(current);
            }

            DirectoryInfo? parent = Directory.GetParent(current);
            if (parent is null)
            {
                break;
            }

            current = parent.FullName;
        }

        throw new InvalidOperationException($"無法自路徑 '{AppContext.BaseDirectory}' 向上定位專案儲存庫根目錄。");
    }

    /// <summary>取得目錄下符合樣式的原始碼（預設 C#；排除 bin、obj 與產生碼）</summary>
    public static IReadOnlyList<(string RelativePath, string FullPath)> GetSourceFiles(string relativeDirectory, string searchPattern = "*.cs")
    {
        string fullDirectory = Path.Combine(SolutionRoot, relativeDirectory);
        if (!Directory.Exists(fullDirectory))
        {
            return [];
        }

        var results = new List<(string RelativePath, string FullPath)>();
        foreach (string file in Directory.EnumerateFiles(fullDirectory, searchPattern, SearchOption.AllDirectories))
        {
            string normalized = file.Replace('\\', '/');
            if (normalized.Contains("/bin/", StringComparison.OrdinalIgnoreCase) ||
                normalized.Contains("/obj/", StringComparison.OrdinalIgnoreCase) ||
                normalized.EndsWith(".g.cs", StringComparison.OrdinalIgnoreCase) ||
                normalized.EndsWith(".AssemblyAttributes.cs", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            string relativePath = Path.GetRelativePath(SolutionRoot, file).Replace('\\', '/');
            results.Add((relativePath, file));
        }

        return results;
    }

    /// <summary>清除單行/多行註解與字串字面值為等長空格（保留插值字串內運算式與換行對齊）</summary>
    public static string StripCommentsAndStrings(string sourceCode) => StripCore(sourceCode, commentRanges: null);

    /// <summary>僅清除註解為等長空格（保留字串字面值與換行對齊）</summary>
    public static string StripCommentsOnly(string sourceCode)
    {
        if (string.IsNullOrEmpty(sourceCode))
        {
            return string.Empty;
        }

        var commentRanges = new List<(int Start, int End)>();
        _ = StripCore(sourceCode, commentRanges);

        char[] chars = sourceCode.ToCharArray();
        foreach (var (start, end) in commentRanges)
        {
            for (int k = start; k < end; k++)
            {
                if (chars[k] is not '\r' and not '\n')
                {
                    chars[k] = ' ';
                }
            }
        }

        return new string(chars);
    }

    private static string StripCore(string sourceCode, List<(int Start, int End)>? commentRanges)
    {
        if (string.IsNullOrEmpty(sourceCode))
        {
            return string.Empty;
        }

        char[] chars = sourceCode.ToCharArray();
        int len = chars.Length;
        int i = 0;

        while (i < len)
        {
            int start = i;
            char c = chars[i];
            char next = i + 1 < len ? chars[i + 1] : '\0';

            // 註解：單行 // 止於換行，多行 /* */ 止於 */（未結束則至檔尾）
            if (c == '/' && next is '/' or '*')
            {
                int end = sourceCode.IndexOf(next == '/' ? "\n" : "*/", next == '/' ? i : i + 2, StringComparison.Ordinal);
                end = end >= 0 && next == '*' ? end + 2 : end;
                i = end < 0 ? len : end;
                Blank(chars, start, i);
                commentRanges?.Add((start, i));
                continue;
            }

            // 字元字面值
            if (c == '\'')
            {
                i = SkipQuoted(chars, i + 1, '\'', verbatim: false, interpolated: false);
                Blank(chars, start, start + 1);
                continue;
            }

            // 字串：前綴 $ 與 @ 任意組合，另含原始字串（三個以上引號）
            int quote = i;
            while (quote < len && quote < i + 2 && chars[quote] is '$' or '@')
            {
                quote++;
            }

            if (quote >= len || chars[quote] != '"')
            {
                i++;
                continue;
            }

            ReadOnlySpan<char> prefix = chars.AsSpan(i, quote - i);
            bool verbatim = prefix.Contains('@');
            bool interpolated = prefix.Contains('$');
            int quoteRun = CountRun(chars, quote);
            if (!verbatim && quoteRun >= 3)
            {
                i = quote + quoteRun;
                while (i < len)
                {
                    int run = chars[i] == '"' ? CountRun(chars, i) : 0;
                    i += Math.Max(run, 1);
                    if (run >= quoteRun)
                    {
                        break;
                    }
                }

                Blank(chars, start, i);
                continue;
            }

            Blank(chars, start, quote + 1);
            i = SkipQuoted(chars, quote + 1, '"', verbatim, interpolated);
        }

        return new string(chars);
    }

    /// <summary>將範圍內除換行外的字元改為空白</summary>
    private static void Blank(char[] chars, int start, int end)
    {
        for (int k = start; k < end; k++)
        {
            if (chars[k] is not '\r' and not '\n')
            {
                chars[k] = ' ';
            }
        }
    }

    private static int CountRun(char[] chars, int index)
    {
        int count = 0;
        while (index + count < chars.Length && chars[index + count] == chars[index])
        {
            count++;
        }

        return count;
    }

    /// <summary>清除自開頭引號之後至結尾引號（含）的內容，回傳其後位置；插值運算式 {…} 保留原文</summary>
    private static int SkipQuoted(char[] chars, int i, char quote, bool verbatim, bool interpolated)
    {
        int len = chars.Length;
        while (i < len)
        {
            char c = chars[i];
            bool doubled = i + 1 < len && chars[i + 1] == c;
            if (!verbatim && c == '\\' && i + 1 < len)
            {
                Blank(chars, i, i + 2);
                i += 2;
            }
            else if (c == quote && verbatim && doubled)
            {
                Blank(chars, i, i + 2);
                i += 2;
            }
            else if (c == quote)
            {
                chars[i] = ' ';
                return i + 1;
            }
            else if (interpolated && c == '{' && doubled)
            {
                Blank(chars, i, i + 2);
                i += 2;
            }
            else if (interpolated && c == '{')
            {
                chars[i++] = ' ';
                for (int depth = 1; i < len && depth > 0; i++)
                {
                    depth += chars[i] == '{' ? 1 : chars[i] == '}' ? -1 : 0;
                    if (depth == 0)
                    {
                        chars[i] = ' ';
                    }
                }
            }
            else
            {
                Blank(chars, i, i + 1);
                i++;
            }
        }

        return i;
    }

    private static readonly ConcurrentDictionary<(string Path, bool PreserveStrings), (string[] Original, string[] Stripped)> LineCache = new();

    /// <summary>以正規表示式掃描違規</summary>
    public static List<SourceViolation> ScanViolations(
        IEnumerable<(string RelativePath, string FullPath)> files,
        Regex pattern,
        string ruleId,
        string ruleDescription,
        Func<string, bool> isWhitelisted,
        bool preserveStrings = false)
    {
        var violations = new List<SourceViolation>();

        foreach (var (relativePath, fullPath) in files)
        {
            if (isWhitelisted(relativePath))
            {
                continue;
            }

            var (originalLines, strippedLines) = LineCache.GetOrAdd((fullPath, preserveStrings), static key =>
            {
                string rawText = File.ReadAllText(key.Path);
                string stripped = key.PreserveStrings ? StripCommentsOnly(rawText) : StripCommentsAndStrings(rawText);
                return (rawText.Split('\n'), stripped.Split('\n'));
            });

            int lineCount = Math.Min(originalLines.Length, strippedLines.Length);
            for (int lineIdx = 0; lineIdx < lineCount; lineIdx++)
            {
                string strippedLine = strippedLines[lineIdx];
                if (pattern.IsMatch(strippedLine))
                {
                    string rawLine = originalLines[lineIdx].TrimEnd('\r');
                    violations.Add(new SourceViolation(
                        relativePath,
                        lineIdx + 1,
                        rawLine.Trim(),
                        ruleId,
                        ruleDescription));
                }
            }
        }

        return violations;
    }
}
