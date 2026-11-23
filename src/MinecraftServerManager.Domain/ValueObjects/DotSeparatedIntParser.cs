using System.Globalization;

namespace MinecraftServerManager.Domain.ValueObjects;

/// <summary>高效能點分隔整數 Span 解析器（零配置）</summary>
public static class DotSeparatedIntParser
{
    /// <summary>嘗試將點分隔字串解析為整數陣列，成功回傳 true</summary>
    public static bool TryParse(ReadOnlySpan<char> span, Span<int> destination, out int count)
    {
        count = 0;
        if (span.IsEmpty)
        {
            return false;
        }

        while (!span.IsEmpty)
        {
            if (count >= destination.Length)
            {
                return false;
            }

            int dotIndex = span.IndexOf('.');
            ReadOnlySpan<char> segment = dotIndex >= 0 ? span[..dotIndex] : span;
            if (segment.IsEmpty || !int.TryParse(segment, NumberStyles.None, CultureInfo.InvariantCulture, out int number))
            {
                return false;
            }

            destination[count++] = number;
            if (dotIndex < 0)
            {
                break;
            }

            span = span[(dotIndex + 1)..];
            if (span.IsEmpty)
            {
                return false;
            }
        }

        return true;
    }

    /// <summary>檢查是否為純點分隔數字（無負號、符號或前導點／末尾點）</summary>
    public static bool IsDotSeparatedNumeric(ReadOnlySpan<char> span, int minSegments = 2, int maxSegments = int.MaxValue)
    {
        if (span.IsEmpty)
        {
            return false;
        }

        int segments = 0;
        while (!span.IsEmpty)
        {
            int dotIndex = span.IndexOf('.');
            ReadOnlySpan<char> segment = dotIndex >= 0 ? span[..dotIndex] : span;
            if (segment.IsEmpty)
            {
                return false;
            }

            foreach (char c in segment)
            {
                if (!char.IsAsciiDigit(c))
                {
                    return false;
                }
            }

            segments++;
            if (segments > maxSegments)
            {
                return false;
            }

            if (dotIndex < 0)
            {
                break;
            }

            span = span[(dotIndex + 1)..];
            if (span.IsEmpty)
            {
                return false;
            }
        }

        return segments >= minSegments;
    }
}
