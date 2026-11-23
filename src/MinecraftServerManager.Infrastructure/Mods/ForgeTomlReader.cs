using System.Text;
using System.Text.RegularExpressions;

namespace MinecraftServerManager.Infrastructure.Mods;

/// <summary>讀取 <c>mods.toml</c> 中模組掃描所需的欄位</summary>
internal static partial class ForgeTomlReader
{
    internal const string DependenciesHeader = "[[dependencies";

    internal static string? ExtractMinecraftDependency(string content)
    {
        if (string.IsNullOrWhiteSpace(content))
        {
            return null;
        }

        content = StripCommentLines(content);
        int idx = FindTableHeader(content, DependenciesHeader, 0);
        while (idx >= 0)
        {
            // 區段延伸至下一個行首表頭（[[...]] 或 [...]）
            int nextSection = FindTableHeader(content, "[", idx + 1);
            string section = nextSection >= 0 ? content[idx..nextSection] : content[idx..];
            if (ForgeMinecraftModIdRegex().IsMatch(section))
            {
                var match = ForgeVersionRangeRegex().Match(section);
                if (match.Success)
                {
                    return CleanTomlValue(match.Groups[1].Value);
                }
            }

            idx = FindTableHeader(content, DependenciesHeader, idx + 1);
        }

        var directMatch = ForgeMcDepRegex().Match(content);
        if (directMatch.Success)
        {
            return CleanTomlValue(directMatch.Groups[1].Value);
        }

        return null;
    }

    /// <summary>移除整行註解（行首空白後為 <c>#</c>），保留其餘行</summary>
    internal static string StripCommentLines(string content)
    {
        if (!content.Contains('#'))
        {
            return content;
        }

        var builder = new StringBuilder(content.Length);
        foreach (var line in content.AsSpan().EnumerateLines())
        {
            if (!line.TrimStart().StartsWith('#'))
            {
                builder.Append(line).Append('\n');
            }
        }

        return builder.ToString();
    }

    /// <summary>自 <paramref name="start"/> 起尋找行首（允許前導空白）以 <paramref name="header"/> 開頭的表頭，回傳其位置；找不到回傳 -1</summary>
    internal static int FindTableHeader(string content, string header, int start)
    {
        int lineStart = start <= 0 ? 0 : content.LastIndexOf('\n', start - 1) + 1;
        while (lineStart < content.Length)
        {
            int pos = lineStart;
            while (pos < content.Length && content[pos] is ' ' or '\t')
            {
                pos++;
            }

            if (pos >= start && content.AsSpan(pos).StartsWith(header, StringComparison.OrdinalIgnoreCase))
            {
                return pos;
            }

            int newline = content.IndexOf('\n', pos);
            if (newline < 0)
            {
                break;
            }

            lineStart = newline + 1;
        }

        return -1;
    }

    internal static string? ExtractValueAt(string content, int pos, ref int nextIndex)
    {
        while (pos < content.Length && (content[pos] == ' ' || content[pos] == '\t' || content[pos] == '\r' || content[pos] == '\n'))
        {
            pos++;
        }

        if (pos >= content.Length)
        {
            return string.Empty;
        }

        if (pos + 3 <= content.Length && content.AsSpan(pos, 3).SequenceEqual("'''"))
        {
            // 多行常值字串：不解跳脫
            int end = content.IndexOf("'''", pos + 3, StringComparison.Ordinal);
            nextIndex = end >= 0 ? Math.Max(nextIndex, end + 3) : content.Length;
            return (end >= 0 ? content[(pos + 3)..end] : content[(pos + 3)..]).Trim();
        }

        if (pos + 3 <= content.Length && content.AsSpan(pos, 3).SequenceEqual("\"\"\""))
        {
            // 多行基本字串：需解跳脫
            int end = FindUnescapedQuote(content, pos + 3, "\"\"\"");
            nextIndex = end >= 0 ? Math.Max(nextIndex, end + 3) : content.Length;
            return UnescapeTomlString((end >= 0 ? content[(pos + 3)..end] : content[(pos + 3)..]).Trim());
        }

        if (content[pos] == '\'')
        {
            int end = content.IndexOf('\'', pos + 1);
            nextIndex = end >= 0 ? Math.Max(nextIndex, end + 1) : content.Length;
            return (end >= 0 ? content[(pos + 1)..end] : content[(pos + 1)..]).Trim();
        }

        if (content[pos] == '"')
        {
            int end = FindUnescapedQuote(content, pos + 1, "\"");
            nextIndex = end >= 0 ? Math.Max(nextIndex, end + 1) : content.Length;
            return UnescapeTomlString((end >= 0 ? content[(pos + 1)..end] : content[(pos + 1)..]).Trim());
        }

        int eol = content.IndexOf('\n', pos);
        string rawVal = eol >= 0 ? content[pos..eol] : content[pos..];
        nextIndex = eol >= 0 ? Math.Max(nextIndex, eol + 1) : content.Length;

        int hashIdx = rawVal.IndexOf('#');
        if (hashIdx >= 0)
        {
            rawVal = rawVal[..hashIdx];
        }

        return rawVal.Trim();
    }

    /// <summary>自 <paramref name="start"/> 起尋找未被反斜線跳脫的引號序列</summary>
    private static int FindUnescapedQuote(string content, int start, string quote)
    {
        int index = start;
        while ((index = content.IndexOf(quote, index, StringComparison.Ordinal)) >= 0)
        {
            if (!IsEscaped(content, index, start))
            {
                return index;
            }

            index++;
        }

        return -1;
    }

    /// <summary>位置前方連續反斜線為奇數個時該字元被跳脫</summary>
    private static bool IsEscaped(string text, int index, int lowerBound)
    {
        int backslashes = 0;
        for (int j = index - 1; j >= lowerBound && text[j] == '\\'; j--)
        {
            backslashes++;
        }

        return backslashes % 2 == 1;
    }

    private static string UnescapeTomlString(string value)
    {
        if (string.IsNullOrEmpty(value) || !value.Contains('\\'))
        {
            return value;
        }

        // 單次掃描：逐一處理跳脫序列，避免 \\n 被誤判為換行
        var builder = new StringBuilder(value.Length);
        for (int i = 0; i < value.Length; i++)
        {
            char c = value[i];
            if (c != '\\' || i + 1 >= value.Length)
            {
                builder.Append(c);
                continue;
            }

            char next = value[++i];
            switch (next)
            {
                case 'n': builder.Append('\n'); break;
                case 'r': builder.Append('\r'); break;
                case 't': builder.Append('\t'); break;
                case '"': builder.Append('"'); break;
                case '\\': builder.Append('\\'); break;
                default: builder.Append('\\').Append(next); break;
            }
        }

        return builder.ToString();
    }

    private static string CleanTomlValue(string raw)
    {
        if (string.IsNullOrWhiteSpace(raw))
        {
            return string.Empty;
        }

        string val = raw.Trim();
        bool inQuotes = false;
        char quoteChar = '\0';
        int commentIndex = -1;
        for (int i = 0; i < val.Length; i++)
        {
            char c = val[i];
            if ((c == '"' || c == '\'') && !IsEscaped(val, i, 0))
            {
                if (!inQuotes)
                {
                    inQuotes = true;
                    quoteChar = c;
                }
                else if (c == quoteChar)
                {
                    inQuotes = false;
                }
            }
            else if (c == '#' && !inQuotes)
            {
                commentIndex = i;
                break;
            }
        }

        if (commentIndex >= 0)
        {
            val = val[..commentIndex];
        }

        return val.Trim('\'', '"', ' ', '\r', '\n', '\t');
    }

    [GeneratedRegex(@"(?m)^\s*modId\s*=\s*[""']minecraft[""']\s*\n\s*versionRange\s*=\s*(.+)$", RegexOptions.CultureInvariant)]
    private static partial Regex ForgeMcDepRegex();

    [GeneratedRegex(@"modId\s*=\s*[""']minecraft[""']", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex ForgeMinecraftModIdRegex();

    [GeneratedRegex(@"versionRange\s*=\s*(.+)$", RegexOptions.Multiline | RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex ForgeVersionRangeRegex();
}
