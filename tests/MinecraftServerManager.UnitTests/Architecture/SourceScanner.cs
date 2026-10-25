using System.Text.RegularExpressions;

namespace MinecraftServerManager.UnitTests.Architecture;
/// <summary>
/// 架構規則違反記錄項目
/// </summary>
/// <param name="FilePath">相對於儲存庫根目錄之檔案路徑</param>
/// <param name="LineNumber">違反規則之原始行號（從 1 起算）</param>
/// <param name="LineContent">該行原始文字內容</param>
/// <param name="RuleId">規則識別代號（例如 A1、A2）</param>
/// <param name="Message">違反原因或規則說明</param>
public sealed record SourceViolation(
    string FilePath,
    int LineNumber,
    string LineContent,
    string RuleId,
    string Message);

/// <summary>
/// 提供原始碼文字掃描、註解/字串清洗與架構違規偵測之共用工具
/// </summary>
public static class SourceScanner
{
    private static readonly Lazy<string> SolutionRootLazy = new(ResolveSolutionRoot);

    /// <summary>
    /// 取得專案儲存庫根目錄絕對路徑
    /// </summary>
    public static string SolutionRoot => SolutionRootLazy.Value;

    /// <summary>
    /// 尋找儲存庫根目錄（依據 MinecraftServerManager.sln 或 Directory.Build.props 向上遞迴查詢）
    /// </summary>
    private static string ResolveSolutionRoot()
    {
        string? current = AppContext.BaseDirectory;
        while (!string.IsNullOrEmpty(current))
        {
            if (File.Exists(Path.Combine(current, "MinecraftServerManager.sln")) ||
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

    /// <summary>
    /// 取得指定相對目錄下所有符合條件的 C# 原始碼檔案清單（自動排除 bin、obj 及產生之原始碼）
    /// </summary>
    /// <param name="relativeDirectory">相對根目錄之路徑（例如 "src" 或 "tests"）</param>
    /// <returns>相對路徑（統一採正斜線 / 格式）與絕對路徑之鍵值配對清單</returns>
    public static IReadOnlyList<(string RelativePath, string FullPath)> GetSourceFiles(string relativeDirectory)
    {
        string fullDirectory = Path.Combine(SolutionRoot, relativeDirectory);
        if (!Directory.Exists(fullDirectory))
        {
            return Array.Empty<(string, string)>();
        }

        var results = new List<(string RelativePath, string FullPath)>();
        var rootUri = new Uri(SolutionRoot.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) + Path.DirectorySeparatorChar);

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

            Uri fileUri = new(file);
            string relativePath = Uri.UnescapeDataString(rootUri.MakeRelativeUri(fileUri).ToString()).Replace('\\', '/');
            results.Add((relativePath, file));
        }

        return results;
    }

    /// <summary>
    /// 清除 C# 原始碼中的單行註解、多行註解與字串字面值（將內容置換為等長空格並保留換行符號），
    /// 同時保留插值字串內的程式碼表達式，以確保原始碼長度、列號與行號完全精確對齊。
    /// </summary>
    /// <param name="sourceCode">原始 C# 程式碼字串</param>
    /// <returns>清洗後之程式碼字串</returns>
    public static string StripCommentsAndStrings(string sourceCode)
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

                continue;
            }

            // 2. 多行註解 /* ... */
            if (c == '/' && next == '*')
            {
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

                    // 逐字插值字串中的表達式處理
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

    /// <summary>
    /// 對目標檔案清單進行正規表示式違規掃描
    /// </summary>
    /// <param name="files">欲掃描之檔案集合</param>
    /// <param name="pattern">違規模式之正規表示式</param>
    /// <param name="ruleId">規則代號</param>
    /// <param name="ruleDescription">規則說明</param>
    /// <param name="isWhitelisted">白名單判定委派（傳入檔案相對路徑，回傳 true 則跳過檢查）</param>
    /// <returns>違規清單</returns>
    public static List<SourceViolation> ScanViolations(
        IEnumerable<(string RelativePath, string FullPath)> files,
        Regex pattern,
        string ruleId,
        string ruleDescription,
        Func<string, bool> isWhitelisted)
    {
        var violations = new List<SourceViolation>();

        foreach (var (relativePath, fullPath) in files)
        {
            if (isWhitelisted(relativePath))
            {
                continue;
            }

            string rawText = File.ReadAllText(fullPath);
            string stripped = StripCommentsAndStrings(rawText);

            string[] originalLines = rawText.Split('\n');
            string[] strippedLines = stripped.Split('\n');

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
