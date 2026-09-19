using System.Text;

namespace MinecraftServerManager.Core.Servers;

/// <summary>
/// Java .properties 格式檔案編解碼器
/// </summary>
public static class PropertiesDocumentCodec
{
    public static Dictionary<string, string> Parse(string content)
    {
        ArgumentNullException.ThrowIfNull(content);
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        using var reader = new StringReader(content);
        string? line;
        var logicalLine = new StringBuilder();
        var keyBuilder = new StringBuilder();
        var valueBuilder = new StringBuilder();

        while ((line = reader.ReadLine()) is not null)
        {
            string trimmed = line.TrimStart();
            if (trimmed.Length == 0 || trimmed.StartsWith('#') || trimmed.StartsWith('!'))
            {
                continue;
            }

            // 處理跨行延續（行末有奇數個反斜線）
            if (HasOddTrailingBackslashes(line))
            {
                logicalLine.Append(line.AsSpan(0, line.Length - 1));
                continue;
            }

            logicalLine.Append(line);
            string fullLine = logicalLine.ToString().Trim();
            logicalLine.Clear();

            if (fullLine.Length == 0 || fullLine.StartsWith('#') || fullLine.StartsWith('!'))
            {
                continue;
            }

            var (key, value) = ParseKeyValue(fullLine, keyBuilder, valueBuilder);
            if (!string.IsNullOrEmpty(key))
            {
                result[key] = value;
            }
        }

        return result;
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

    private static bool HasOddTrailingBackslashes(string line)
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
        var sb = new StringBuilder();
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
        var sb = new StringBuilder();
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
