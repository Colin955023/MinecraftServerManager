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

/// <summary>提供原始碼文字掃描、註解/字串清洗與架構違規偵測之共用工具</summary>
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

    /// <summary>取得指定相對目錄下所有 C# 原始碼檔案（排除 bin、obj 及產生之原始碼）</summary>
    public static IReadOnlyList<(string RelativePath, string FullPath)> GetSourceFiles(string relativeDirectory)
    {
        string fullDirectory = Path.Combine(SolutionRoot, relativeDirectory);
        if (!Directory.Exists(fullDirectory))
        {
            return [];
        }

        var results = new List<(string RelativePath, string FullPath)>();
        foreach (string file in Directory.EnumerateFiles(fullDirectory, "*.cs", SearchOption.AllDirectories))
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
            char c = chars[i];
            char next = i + 1 < len ? chars[i + 1] : '\0';

            // 1. 單行註解 //
            if (c == '/' && next == '/')
            {
                int commentStart = i;
                chars[i] = ' ';
                chars[i + 1] = ' ';
                i += 2;
                while (i < len && chars[i] != '\n')
                {
                    if (chars[i] != '\r')
                    {
                        chars[i] = ' ';
                    }

                    i++;
                }

                commentRanges?.Add((commentStart, i));
                continue;
            }

            // 2. 多行註解 /* ... */
            if (c == '/' && next == '*')
            {
                int commentStart = i;
                chars[i] = ' ';
                chars[i + 1] = ' ';
                i += 2;
                while (i < len)
                {
                    if (chars[i] == '*' && i + 1 < len && chars[i + 1] == '/')
                    {
                        chars[i] = ' ';
                        chars[i + 1] = ' ';
                        i += 2;
                        break;
                    }

                    if (chars[i] is not '\r' and not '\n')
                    {
                        chars[i] = ' ';
                    }

                    i++;
                }

                commentRanges?.Add((commentStart, i));
                continue;
            }

            // 3. 原始字串字面值（Raw string literals C# 11+）：以至少三個引號開頭（可前綴 $）
            bool isRawInterpolated = c == '$' && next == '"' && i + 2 < len && chars[i + 2] == '"';
            bool isRawNormal = c == '"' && next == '"' && i + 2 < len && chars[i + 2] == '"';

            if (isRawInterpolated || isRawNormal)
            {
                int startQuotePos = isRawInterpolated ? i + 1 : i;
                int quoteCount = 0;
                while (startQuotePos + quoteCount < len && chars[startQuotePos + quoteCount] == '"')
                {
                    quoteCount++;
                }

                for (int k = i; k < startQuotePos + quoteCount; k++)
                {
                    chars[k] = ' ';
                }

                i = startQuotePos + quoteCount;

                while (i < len)
                {
                    if (chars[i] == '"')
                    {
                        int endCount = 0;
                        while (i + endCount < len && chars[i + endCount] == '"')
                        {
                            endCount++;
                        }

                        if (endCount >= quoteCount)
                        {
                            for (int k = 0; k < endCount; k++)
                            {
                                chars[i + k] = ' ';
                            }

                            i += endCount;
                            break;
                        }

                        for (int k = 0; k < endCount; k++)
                        {
                            chars[i + k] = ' ';
                        }

                        i += endCount;
                        continue;
                    }

                    if (chars[i] is not '\r' and not '\n')
                    {
                        chars[i] = ' ';
                    }

                    i++;
                }

                continue;
            }

            // 4. 逐字字串：@"..." 或 $@"... / @$"..."
            bool isVerbatimInterpolated = (c == '$' && next == '@' && i + 2 < len && chars[i + 2] == '"') ||
                                         (c == '@' && next == '$' && i + 2 < len && chars[i + 2] == '"');
            bool isVerbatimNormal = c == '@' && next == '"';

            if (isVerbatimInterpolated || isVerbatimNormal)
            {
                int quotePos = isVerbatimInterpolated ? i + 2 : i + 1;
                bool isInterpolated = isVerbatimInterpolated;
                for (int k = i; k <= quotePos; k++)
                {
                    chars[k] = ' ';
                }

                i = quotePos + 1;

                while (i < len)
                {
                    if (chars[i] == '"')
                    {
                        if (i + 1 < len && chars[i + 1] == '"')
                        {
                            chars[i] = ' ';
                            chars[i + 1] = ' ';
                            i += 2;
                            continue;
                        }

                        chars[i] = ' ';
                        i++;
                        break;
                    }

                    // 逐字插值字串中的運算式處理
                    if (isInterpolated && chars[i] == '{')
                    {
                        if (i + 1 < len && chars[i + 1] == '{')
                        {
                            chars[i] = ' ';
                            chars[i + 1] = ' ';
                            i += 2;
                            continue;
                        }

                        chars[i] = ' ';
                        i++;
                        int braceLevel = 1;
                        while (i < len && braceLevel > 0)
                        {
                            if (chars[i] == '{')
                            {
                                braceLevel++;
                            }
                            else if (chars[i] == '}')
                            {
                                braceLevel--;
                                if (braceLevel == 0)
                                {
                                    chars[i] = ' ';
                                    i++;
                                    break;
                                }
                            }

                            i++;
                        }

                        continue;
                    }

                    if (chars[i] is not '\r' and not '\n')
                    {
                        chars[i] = ' ';
                    }

                    i++;
                }

                continue;
            }

            // 5. 一般插值字串：$"..."
            if (c == '$' && next == '"')
            {
                chars[i] = ' ';
                chars[i + 1] = ' ';
                i += 2;

                while (i < len)
                {
                    if (chars[i] == '\\' && i + 1 < len)
                    {
                        chars[i] = ' ';
                        chars[i + 1] = ' ';
                        i += 2;
                        continue;
                    }

                    if (chars[i] == '"')
                    {
                        chars[i] = ' ';
                        i++;
                        break;
                    }

                    if (chars[i] == '{')
                    {
                        if (i + 1 < len && chars[i + 1] == '{')
                        {
                            chars[i] = ' ';
                            chars[i + 1] = ' ';
                            i += 2;
                            continue;
                        }

                        chars[i] = ' ';
                        i++;
                        int braceLevel = 1;
                        while (i < len && braceLevel > 0)
                        {
                            if (chars[i] == '{')
                            {
                                braceLevel++;
                            }
                            else if (chars[i] == '}')
                            {
                                braceLevel--;
                                if (braceLevel == 0)
                                {
                                    chars[i] = ' ';
                                    i++;
                                    break;
                                }
                            }

                            i++;
                        }

                        continue;
                    }

                    if (chars[i] is not '\r' and not '\n')
                    {
                        chars[i] = ' ';
                    }

                    i++;
                }

                continue;
            }

            // 6. 一般字串字面值："..."
            if (c == '"')
            {
                chars[i] = ' ';
                i++;
                while (i < len)
                {
                    if (chars[i] == '\\' && i + 1 < len)
                    {
                        chars[i] = ' ';
                        chars[i + 1] = ' ';
                        i += 2;
                        continue;
                    }

                    if (chars[i] == '"')
                    {
                        chars[i] = ' ';
                        i++;
                        break;
                    }

                    if (chars[i] is not '\r' and not '\n')
                    {
                        chars[i] = ' ';
                    }

                    i++;
                }

                continue;
            }

            // 7. 字元字面值：'...'
            if (c == '\'')
            {
                chars[i] = ' ';
                i++;
                while (i < len)
                {
                    if (chars[i] == '\\' && i + 1 < len)
                    {
                        chars[i] = ' ';
                        chars[i + 1] = ' ';
                        i += 2;
                        continue;
                    }

                    if (chars[i] == '\'')
                    {
                        chars[i] = ' ';
                        i++;
                        break;
                    }

                    if (chars[i] is not '\r' and not '\n')
                    {
                        chars[i] = ' ';
                    }

                    i++;
                }

                continue;
            }

            i++;
        }

        return new string(chars);
    }

    private static readonly ConcurrentDictionary<(string Path, bool PreserveStrings), (string[] Original, string[] Stripped)> LineCache = new();

    /// <summary>對目標檔案清單進行正規表示式違規掃描（preserveStrings=true 時僅移除註解並保留字串內容）</summary>
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
