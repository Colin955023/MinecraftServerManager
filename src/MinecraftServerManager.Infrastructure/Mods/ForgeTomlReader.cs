using System.Text.RegularExpressions;

namespace MinecraftServerManager.Infrastructure.Mods;

/// <summary>Forge／NeoForge <c>mods.toml</c> 的輕量欄位讀取（僅擷取模組掃描所需欄位，不實作完整 TOML）</summary>
internal static partial class ForgeTomlReader
{
    internal static string? ExtractMinecraftDependency(string content)
    {
        if (string.IsNullOrWhiteSpace(content))
        {
            return null;
        }

        int idx = 0;
        while ((idx = content.IndexOf("[[dependencies", idx, StringComparison.OrdinalIgnoreCase)) >= 0)
        {
            int nextSection = content.IndexOf("[[", idx + 14, StringComparison.Ordinal);
            string section = nextSection >= 0 ? content[idx..nextSection] : content[idx..];
            if (ForgeMinecraftModIdRegex().IsMatch(section))
            {
                var match = ForgeVersionRangeRegex().Match(section);
                if (match.Success)
                {
                    return CleanTomlValue(match.Groups[1].Value);
                }
            }
            if (nextSection < 0)
            {
                break;
            }
            idx = nextSection;
        }

        var directMatch = ForgeMcDepRegex().Match(content);
        if (directMatch.Success)
        {
            return CleanTomlValue(directMatch.Groups[1].Value);
        }

        return null;
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
            int end = content.IndexOf("'''", pos + 3, StringComparison.Ordinal);
            if (end >= 0)
            {
                nextIndex = Math.Max(nextIndex, end + 3);
                return content[(pos + 3)..end].Trim();
            }
            nextIndex = content.Length;
            return content[(pos + 3)..].Trim();
        }

        if (pos + 3 <= content.Length && content.AsSpan(pos, 3).SequenceEqual("\"\"\""))
        {
            int end = content.IndexOf("\"\"\"", pos + 3, StringComparison.Ordinal);
            if (end >= 0)
            {
                nextIndex = Math.Max(nextIndex, end + 3);
                return content[(pos + 3)..end].Trim();
            }
            nextIndex = content.Length;
            return content[(pos + 3)..].Trim();
        }

        if (content[pos] == '\'')
        {
            int end = content.IndexOf('\'', pos + 1);
            if (end >= 0)
            {
                nextIndex = Math.Max(nextIndex, end + 1);
                return content[(pos + 1)..end].Trim();
            }
            return content[(pos + 1)..].Trim();
        }

        if (content[pos] == '"')
        {
            int end = -1;
            for (int i = pos + 1; i < content.Length; i++)
            {
                if (content[i] == '"')
                {
                    int backslashes = 0;
                    for (int j = i - 1; j > pos && content[j] == '\\'; j--)
                    {
                        backslashes++;
                    }
                    if (backslashes % 2 == 0)
                    {
                        end = i;
                        break;
                    }
                }
            }
            if (end >= 0)
            {
                nextIndex = Math.Max(nextIndex, end + 1);
                return UnescapeTomlString(content[(pos + 1)..end].Trim());
            }
            return UnescapeTomlString(content[(pos + 1)..].Trim());
        }

        int eol = content.IndexOf('\n', pos);
        string rawVal = eol >= 0 ? content[pos..eol] : content[pos..];
        if (eol >= 0)
        {
            nextIndex = Math.Max(nextIndex, eol + 1);
        }
        else
        {
            nextIndex = content.Length;
        }

        int hashIdx = rawVal.IndexOf('#');
        if (hashIdx >= 0)
        {
            rawVal = rawVal[..hashIdx];
        }

        return rawVal.Trim();
    }

    private static string UnescapeTomlString(string value)
    {
        if (string.IsNullOrEmpty(value) || !value.Contains('\\'))
        {
            return value;
        }

        return value
            .Replace("\\n", "\n", StringComparison.Ordinal)
            .Replace("\\r", "\r", StringComparison.Ordinal)
            .Replace("\\t", "\t", StringComparison.Ordinal)
            .Replace("\\\"", "\"", StringComparison.Ordinal)
            .Replace("\\\\", "\\", StringComparison.Ordinal);
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
            if ((c == '"' || c == '\'') && (i == 0 || val[i - 1] != '\\'))
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

    [GeneratedRegex(@"(?m)^\s*modId\s*=\s*[""']minecraft[""']\s*\n\s*versionRange\s*=\s*(.+)$")]
    private static partial Regex ForgeMcDepRegex();

    [GeneratedRegex(@"modId\s*=\s*[""']minecraft[""']", RegexOptions.IgnoreCase)]
    private static partial Regex ForgeMinecraftModIdRegex();

    [GeneratedRegex(@"versionRange\s*=\s*(.+)$", RegexOptions.Multiline | RegexOptions.IgnoreCase)]
    private static partial Regex ForgeVersionRangeRegex();
}
