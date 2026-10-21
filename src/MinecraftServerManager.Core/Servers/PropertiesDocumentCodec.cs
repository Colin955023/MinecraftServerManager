using System.Buffers;
using System.Text;

namespace MinecraftServerManager.Core.Servers;

/// <summary>
/// Java .properties 格式檔案編解碼器
/// </summary>
public static class PropertiesDocumentCodec
{
    private static readonly SearchValues<char> KeyEscapeChars = SearchValues.Create("\\=: ");
    private static readonly SearchValues<char> ValueEscapeChars = SearchValues.Create("\\\t\r\n");

    public static Dictionary<string, string> Parse(string content)
    {
        ArgumentNullException.ThrowIfNull(content);
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        var logicalLine = new StringBuilder();
        var keyBuilder = new StringBuilder();
        var valueBuilder = new StringBuilder();

        foreach (ReadOnlySpan<char> rawLine in content.AsSpan().EnumerateLines())
        {
            ReadOnlySpan<char> trimmed = rawLine.TrimStart();
            if (trimmed.IsEmpty || trimmed[0] == '#' || trimmed[0] == '!')
            {
                continue;
            }

            // 處理跨行延續（行末有奇數個反斜線）
            if (HasOddTrailingBackslashes(rawLine))
            {
                logicalLine.Append(rawLine[..^1]);
                continue;
            }

            logicalLine.Append(rawLine);
            FlushLogicalLine(logicalLine, keyBuilder, valueBuilder, result);
        }

        if (logicalLine.Length > 0)
        {
            FlushLogicalLine(logicalLine, keyBuilder, valueBuilder, result);
        }

        return result;
    }

    private static void FlushLogicalLine(
        StringBuilder logicalLine,
        StringBuilder keyBuilder,
        StringBuilder valueBuilder,
        Dictionary<string, string> result)
    {
        string fullLine = logicalLine.ToString().Trim();
        logicalLine.Clear();
        if (fullLine.Length == 0 || fullLine.StartsWith('#') || fullLine.StartsWith('!'))
        {
            return;
        }

        var (key, value) = ParseKeyValue(fullLine, keyBuilder, valueBuilder);
        if (!string.IsNullOrEmpty(key))
        {
            result[key] = value;
        }
    }

    public static string Serialize(
        IReadOnlyDictionary<string, string> properties,
        string? headerComment = "Minecraft server properties")
    {
        ArgumentNullException.ThrowIfNull(properties);
        var sb = new StringBuilder();

        if (!string.IsNullOrWhiteSpace(headerComment))
        {
            sb.Append("# ").AppendLine(headerComment);
        }

        foreach (var (key, value) in properties)
        {
            string escapedKey = EscapeKey(key);
            string escapedValue = EscapeValue(value);
            sb.Append(escapedKey).Append('=').AppendLine(escapedValue);
        }

        return sb.ToString();
    }

    private static (string Key, string Value) ParseKeyValue(string line, StringBuilder keyBuilder, StringBuilder valueBuilder)
    {
        keyBuilder.Clear();
        valueBuilder.Clear();
        bool inKey = true;
        bool isEscaped = false;

        for (int i = 0; i < line.Length; i++)
        {
            char c = line[i];

            if (isEscaped)
            {
                isEscaped = false;
                if (c == 'u' && i + 4 < line.Length &&
                    int.TryParse(line.AsSpan(i + 1, 4), System.Globalization.NumberStyles.HexNumber, null, out int codePoint))
                {
                    char ch = (char)codePoint;
                    if (inKey)
                    {
                        keyBuilder.Append(ch);
                    }
                    else
                    {
                        valueBuilder.Append(ch);
                    }

                    i += 4;
                }
                else
                {
                    char unescaped = c switch
                    {
                        't' => '\t',
                        'r' => '\r',
                        'n' => '\n',
                        'f' => '\f',
                        _ => c,
                    };

                    if (inKey)
                    {
                        keyBuilder.Append(unescaped);
                    }
                    else
                    {
                        valueBuilder.Append(unescaped);
                    }
                }

                continue;
            }

            if (c == '\\')
            {
                isEscaped = true;
                continue;
            }

            if (inKey && (c is '=' or ':'))
            {
                inKey = false;
                continue;
            }

            if (inKey)
            {
                keyBuilder.Append(c);
            }
            else
            {
                valueBuilder.Append(c);
            }
        }

        return (keyBuilder.ToString().Trim(), valueBuilder.ToString());
    }

    private static bool HasOddTrailingBackslashes(ReadOnlySpan<char> line)
    {
        int count = 0;
        for (int i = line.Length - 1; i >= 0 && line[i] == '\\'; i--)
        {
            count++;
        }

        return count % 2 != 0;
    }

    private static string EscapeKey(string key)
    {
        if (key.AsSpan().IndexOfAny(KeyEscapeChars) < 0)
        {
            return key;
        }

        var sb = new StringBuilder(key.Length + 4);
        foreach (char c in key)
        {
            switch (c)
            {
                case '\\':
                    sb.Append(@"\\");
                    break;
                case '=':
                    sb.Append(@"\=");
                    break;
                case ':':
                    sb.Append(@"\:");
                    break;
                case ' ':
                    sb.Append(@"\ ");
                    break;
                default:
                    sb.Append(c);
                    break;
            }
        }

        return sb.ToString();
    }

    private static string EscapeValue(string value)
    {
        if (value.AsSpan().IndexOfAny(ValueEscapeChars) < 0)
        {
            return value;
        }

        var sb = new StringBuilder(value.Length + 4);
        foreach (char c in value)
        {
            switch (c)
            {
                case '\\':
                    sb.Append(@"\\");
                    break;
                case '\t':
                    sb.Append(@"\t");
                    break;
                case '\r':
                    sb.Append(@"\r");
                    break;
                case '\n':
                    sb.Append(@"\n");
                    break;
                default:
                    sb.Append(c);
                    break;
            }
        }

        return sb.ToString();
    }
}
