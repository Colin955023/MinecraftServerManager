using System.Buffers;
using System.Globalization;
using System.Text;

namespace MinecraftServerManager.Core.Servers;

/// <summary>Java .properties 格式檔案編解碼器（依 java.util.Properties 規格）</summary>
public static class PropertiesDocumentCodec
{
    private const string WhitespaceChars = " \t\f";
    private static readonly SearchValues<char> KeyTerminators = SearchValues.Create("=: \t\f");
    private static readonly SearchValues<char> KeyEscapeChars = SearchValues.Create("\\=: \t\r\n\f");
    private static readonly SearchValues<char> ValueEscapeChars = SearchValues.Create("\\\t\r\n\f");

    public static Dictionary<string, string> Parse(string content)
    {
        ArgumentNullException.ThrowIfNull(content);
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        var logicalLine = new StringBuilder();
        var keyBuilder = new StringBuilder();
        var valueBuilder = new StringBuilder();
        bool isContinuation = false;

        foreach (ReadOnlySpan<char> rawLine in content.AsSpan().EnumerateLines())
        {
            // 每個自然行（含延續行）的前導空白皆不屬於內容
            ReadOnlySpan<char> segment = rawLine.TrimStart(WhitespaceChars);

            // 註解與空白行只在邏輯行開頭有意義；延續行以 # 開頭仍屬於值
            if (!isContinuation && (segment.IsEmpty || segment[0] is '#' or '!'))
            {
                continue;
            }

            if (HasOddTrailingBackslashes(segment))
            {
                logicalLine.Append(segment[..^1]);
                isContinuation = true;
                continue;
            }

            isContinuation = false;
            if (logicalLine.Length == 0)
            {
                // 單行非延續行直接以 Span 解析
                AddEntry(segment, keyBuilder, valueBuilder, result);
                continue;
            }

            logicalLine.Append(segment);
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
        string fullLine = logicalLine.ToString();
        logicalLine.Clear();
        AddEntry(fullLine, keyBuilder, valueBuilder, result);
    }

    private static void AddEntry(
        ReadOnlySpan<char> line,
        StringBuilder keyBuilder,
        StringBuilder valueBuilder,
        Dictionary<string, string> result)
    {
        if (line.IsEmpty)
        {
            return;
        }

        var (key, value) = ParseKeyValue(line, keyBuilder, valueBuilder);
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
            // 每行皆補註解前綴，避免多行註解被解析為屬性
            foreach (ReadOnlySpan<char> commentLine in headerComment.AsSpan().EnumerateLines())
            {
                sb.Append("# ").Append(commentLine).AppendLine();
            }
        }

        foreach (var (key, value) in properties)
        {
            AppendEscapedKey(sb, key);
            sb.Append('=');
            AppendEscapedValue(sb, value);
            sb.AppendLine();
        }

        return sb.ToString();
    }

    /// <summary>解析邏輯行：鍵止於未跳脫之 =、: 或空白；分隔符前後空白不屬於值，值尾端空白保留</summary>
    private static (string Key, string Value) ParseKeyValue(ReadOnlySpan<char> line, StringBuilder keyBuilder, StringBuilder valueBuilder)
    {
        keyBuilder.Clear();
        valueBuilder.Clear();

        int index = ReadEscaped(line, 0, keyBuilder, stopAtKeyTerminator: true);

        // 略過鍵後空白，以及至多一個 = 或 : 分隔符與其後空白
        while (index < line.Length && WhitespaceChars.Contains(line[index]))
        {
            index++;
        }

        if (index < line.Length && line[index] is '=' or ':')
        {
            index++;
            while (index < line.Length && WhitespaceChars.Contains(line[index]))
            {
                index++;
            }
        }

        ReadEscaped(line, index, valueBuilder, stopAtKeyTerminator: false);
        return (keyBuilder.ToString(), valueBuilder.ToString());
    }

    private static int ReadEscaped(ReadOnlySpan<char> line, int start, StringBuilder target, bool stopAtKeyTerminator)
    {
        int i = start;
        while (i < line.Length)
        {
            char c = line[i];
            if (c != '\\')
            {
                if (stopAtKeyTerminator && KeyTerminators.Contains(c))
                {
                    return i;
                }

                target.Append(c);
                i++;
                continue;
            }

            if (i + 1 >= line.Length)
            {
                return line.Length;
            }

            char next = line[i + 1];
            if (next == 'u' && TryParseUnicodeEscape(line, i + 2, out char unicode))
            {
                target.Append(unicode);
                i += 6;
                continue;
            }

            target.Append(next switch
            {
                't' => '\t',
                'r' => '\r',
                'n' => '\n',
                'f' => '\f',
                _ => next,
            });
            i += 2;
        }

        return i;
    }

    private static bool TryParseUnicodeEscape(ReadOnlySpan<char> line, int start, out char value)
    {
        value = default;
        if (start + 4 > line.Length)
        {
            return false;
        }

        ReadOnlySpan<char> hex = line.Slice(start, 4);
        foreach (char h in hex)
        {
            if (!char.IsAsciiHexDigit(h))
            {
                return false;
            }
        }

        value = (char)int.Parse(hex, NumberStyles.AllowHexSpecifier, CultureInfo.InvariantCulture);
        return true;
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

    private static void AppendEscapedKey(StringBuilder sb, string key)
    {
        if (key.Length > 0 && key[0] is '#' or '!')
        {
            sb.Append('\\');
        }

        if (key.AsSpan().IndexOfAny(KeyEscapeChars) < 0)
        {
            sb.Append(key);
            return;
        }

        foreach (char c in key)
        {
            AppendEscapedChar(sb, c, escapeSeparators: true);
        }
    }

    private static void AppendEscapedValue(StringBuilder sb, string value)
    {
        ReadOnlySpan<char> span = value.AsSpan();
        int leading = 0;

        // 值首空白須跳脫，否則解析時會被視為分隔空白而遺失
        while (leading < span.Length && span[leading] == ' ')
        {
            sb.Append(@"\ ");
            leading++;
        }

        span = span[leading..];
        if (span.IndexOfAny(ValueEscapeChars) < 0)
        {
            sb.Append(span);
            return;
        }

        foreach (char c in span)
        {
            AppendEscapedChar(sb, c, escapeSeparators: false);
        }
    }

    private static void AppendEscapedChar(StringBuilder sb, char c, bool escapeSeparators)
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
            case '\f':
                sb.Append(@"\f");
                break;
            case '=' or ':' or ' ' when escapeSeparators:
                sb.Append('\\').Append(c);
                break;
            default:
                sb.Append(c);
                break;
        }
    }
}
