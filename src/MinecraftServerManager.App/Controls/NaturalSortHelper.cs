using System.Collections;
using System.Collections.Concurrent;
using System.ComponentModel;
using System.Diagnostics.CodeAnalysis;
using System.Globalization;
using System.Linq.Expressions;
using System.Reflection;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.Controls;

/// <summary>
/// 自然排序輔助工具，提供支援自動單位換算（容量、數量、日期時間）與 Windows 自然排序規則的比較器
/// </summary>
public static class NaturalSortHelper
{
    /// <summary>
    /// 比對兩個字串之自然數值大小（自動將容量單位、數量單位、日期時間換算為統一單位後比較，不影響 UI 顯示）
    /// </summary>
    public static int CompareNatural(string? x, string? y)
    {
        if (ReferenceEquals(x, y))
        {
            return 0;
        }
        if (x is null)
        {
            return -1;
        }
        if (y is null)
        {
            return 1;
        }

        ReadOnlySpan<char> spanX = x.AsSpan().Trim();
        ReadOnlySpan<char> spanY = y.AsSpan().Trim();

        // 1. 容量單位自動統一換算為 Bytes 比較（支援 B / KB / KiB / MB / MiB / GB / GiB / TB / TiB 及 "-" 佔位符）
        bool isSizeX = TryParseDataSizeToBytes(spanX, out double bytesX);
        bool isSizeY = TryParseDataSizeToBytes(spanY, out double bytesY);
        if (isSizeX || isSizeY)
        {
            if (isSizeX && isSizeY)
            {
                return bytesX.CompareTo(bytesY);
            }
            if (isSizeX && IsPlaceholder(spanY))
            {
                return 1;
            }
            if (isSizeY && IsPlaceholder(spanX))
            {
                return -1;
            }
        }

        // 2. 日期時間字串自動統一換算為時間戳記比較
        bool isDateX = TryParseDateTime(spanX, out DateTimeOffset dateX);
        bool isDateY = TryParseDateTime(spanY, out DateTimeOffset dateY);
        if (isDateX || isDateY)
        {
            if (isDateX && isDateY)
            {
                return dateX.CompareTo(dateY);
            }
            if (isDateX && IsPlaceholder(spanY))
            {
                return 1;
            }
            if (isDateY && IsPlaceholder(spanX))
            {
                return -1;
            }
        }

        // 3. 數量／下載量單位自動統一換算為數值比較（如 1.2K、3.5M、1.5 萬、2 億、千分位數字）
        bool isQtyX = TryParseQuantity(spanX, out double qtyX);
        bool isQtyY = TryParseQuantity(spanY, out double qtyY);
        if (isQtyX && isQtyY)
        {
            return qtyX.CompareTo(qtyY);
        }

        return CultureInfo.CurrentCulture.CompareInfo.Compare(
            x,
            y,
            CompareOptions.NumericOrdering | CompareOptions.IgnoreCase);
    }

    private static bool IsPlaceholder(ReadOnlySpan<char> span) =>
        span.IsEmpty || span.SequenceEqual("-") || span.SequenceEqual("未知") || span.SequenceEqual("無");

    /// <summary>
    /// 嘗試將容量字串（如 "512 B", "12.5 KB", "900 MB", "1.2 GB", "2 TB"）解析並統一換算為位元組數（Bytes）。
    /// </summary>
    public static bool TryParseDataSizeToBytes(ReadOnlySpan<char> span, out double bytes)
    {
        bytes = 0;
        span = span.Trim();
        if (span.IsEmpty)
        {
            return false;
        }

        double multiplier;

        if (TryStripSuffix(span, "TIB", out ReadOnlySpan<char> numberPart) || TryStripSuffix(span, "TB", out numberPart))
        {
            multiplier = 1024d * 1024d * 1024d * 1024d;
        }
        else if (TryStripSuffix(span, "GIB", out numberPart) || TryStripSuffix(span, "GB", out numberPart))
        {
            multiplier = 1024d * 1024d * 1024d;
        }
        else if (TryStripSuffix(span, "MIB", out numberPart) || TryStripSuffix(span, "MB", out numberPart))
        {
            multiplier = 1024d * 1024d;
        }
        else if (TryStripSuffix(span, "KIB", out numberPart) || TryStripSuffix(span, "KB", out numberPart))
        {
            multiplier = 1024d;
        }
        else if (TryStripSuffix(span, "BYTES", out numberPart) || TryStripSuffix(span, "BYTE", out numberPart))
        {
            multiplier = 1d;
        }
        else if (span.Length >= 2 && (span[^1] is 'B' or 'b') && char.IsWhiteSpace(span[^2]))
        {
            numberPart = span[..^1].TrimEnd();
            multiplier = 1d;
        }
        else
        {
            return false;
        }

        if (numberPart.IsEmpty)
        {
            return false;
        }

        if (double.TryParse(numberPart, NumberStyles.Float | NumberStyles.AllowThousands, CultureInfo.InvariantCulture, out double val) &&
            !double.IsNaN(val) && !double.IsInfinity(val))
        {
            bytes = val * multiplier;
            return true;
        }

        return false;
    }

    /// <summary>
    /// 嘗試將含數量單位之字串（如 "1.5K", "2.3M", "1.2 萬", "3 億" 或純數字）統一換算為數值。
    /// </summary>
    public static bool TryParseQuantity(ReadOnlySpan<char> span, out double value)
    {
        value = 0;
        span = span.Trim();
        if (span.IsEmpty)
        {
            return false;
        }

        // 避免將版本號（如 "1.20.4" 含兩個小數點）誤判為純浮點數
        int dotCount = 0;
        for (int i = 0; i < span.Length; i++)
        {
            if (span[i] == '.')
            {
                dotCount++;
                if (dotCount > 1)
                {
                    return false;
                }
            }
        }

        double multiplier = 1d;
        ReadOnlySpan<char> numberPart = span;

        if (TryStripSuffix(span, "百萬", out var pMillion))
        {
            multiplier = 1_000_000d;
            numberPart = pMillion;
        }
        else if (TryStripSuffix(span, "億", out var pHundredMillion))
        {
            multiplier = 100_000_000d;
            numberPart = pHundredMillion;
        }
        else if (TryStripSuffix(span, "萬", out var pTenThousand) || TryStripSuffix(span, "W", out pTenThousand))
        {
            multiplier = 10_000d;
            numberPart = pTenThousand;
        }
        else if (TryStripSuffix(span, "千", out var pThousand) || TryStripSuffix(span, "K", out pThousand))
        {
            multiplier = 1_000d;
            numberPart = pThousand;
        }
        else if (TryStripSuffix(span, "M", out var pM))
        {
            multiplier = 1_000_000d;
            numberPart = pM;
        }

        if (numberPart.IsEmpty)
        {
            return false;
        }

        if (double.TryParse(numberPart, NumberStyles.Float | NumberStyles.AllowThousands, CultureInfo.InvariantCulture, out double parsed) &&
            !double.IsNaN(parsed) && !double.IsInfinity(parsed))
        {
            value = parsed * multiplier;
            return true;
        }

        return false;
    }

    private static bool TryParseDateTime(ReadOnlySpan<char> span, out DateTimeOffset result)
    {
        result = default;
        if (span.Length < 8 || !char.IsAsciiDigit(span[0]) || !char.IsAsciiDigit(span[1]) || !char.IsAsciiDigit(span[2]) || !char.IsAsciiDigit(span[3]))
        {
            return false;
        }

        if (span[4] is not ('-' or '/'))
        {
            return false;
        }

        return DateTimeOffset.TryParse(span, CultureInfo.InvariantCulture, DateTimeStyles.AssumeLocal, out result);
    }

    private static bool TryStripSuffix(ReadOnlySpan<char> span, ReadOnlySpan<char> suffix, out ReadOnlySpan<char> prefix)
    {
        if (span.Length > suffix.Length && span.EndsWith(suffix, StringComparison.OrdinalIgnoreCase))
        {
            prefix = span[..^suffix.Length].TrimEnd();
            return !prefix.IsEmpty && (char.IsAsciiDigit(prefix[^1]) || prefix[^1] == '.');
        }

        prefix = default;
        return false;
    }
}

/// <summary>
/// 純字串的 Windows 自然排序比較器
/// </summary>
public sealed class StringNaturalComparer : IComparer<string>
{
    public static readonly StringNaturalComparer Instance = new();

    public int Compare(string? x, string? y) =>
        NaturalSortHelper.CompareNatural(x, y);
}

/// <summary>
/// 依據屬性名稱與 Windows 自然排序規則之泛型物件比較器
/// </summary>
public sealed class WindowsNaturalSortComparer<T>(string propertyName, ListSortDirection direction) : IComparer<T>
{
    private readonly WindowsNaturalSortComparer _inner = new(propertyName, direction);

    public int Compare(T? x, T? y) => _inner.Compare(x, y);
}

/// <summary>
/// 依據屬性名稱與 Windows 自然排序規則之物件比較器
/// </summary>
public sealed class WindowsNaturalSortComparer(string propertyName, ListSortDirection direction) : IComparer
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(WindowsNaturalSortComparer));
    private static readonly ConcurrentDictionary<(Type, string), Func<object, object?>?> GetterCache = new();

    public int Compare(object? x, object? y)
    {
        if (ReferenceEquals(x, y))
        {
            return 0;
        }
        if (x is null)
        {
            return direction == ListSortDirection.Ascending ? -1 : 1;
        }
        if (y is null)
        {
            return direction == ListSortDirection.Ascending ? 1 : -1;
        }

        int result = CompareValues(x, y);
        return direction == ListSortDirection.Ascending ? result : -result;
    }

    private int CompareValues(object x, object y)
    {
        // 檔案／目錄大小特殊最佳化：若物件具有對應原始位元組屬性，優先採用數值比較
        if (string.Equals(propertyName, "FileSize", StringComparison.OrdinalIgnoreCase) ||
            string.Equals(propertyName, "Size", StringComparison.OrdinalIgnoreCase) ||
            string.Equals(propertyName, "SizeFormatted", StringComparison.OrdinalIgnoreCase))
        {
            long? rawX = GetPropertyValue<long>(x, "RawFileSize") ?? GetPropertyValue<long>(x, "RawSizeBytes") ?? GetPropertyValue<long>(x, "SizeBytes");
            long? rawY = GetPropertyValue<long>(y, "RawFileSize") ?? GetPropertyValue<long>(y, "RawSizeBytes") ?? GetPropertyValue<long>(y, "SizeBytes");
            if (rawX.HasValue && rawY.HasValue && (rawX.Value >= 0 || rawY.Value >= 0))
            {
                return rawX.Value.CompareTo(rawY.Value);
            }
        }

        // 下載量特殊最佳化：若物件具有 DownloadCountRaw，優先採用數值比較
        if (string.Equals(propertyName, "Downloads", StringComparison.OrdinalIgnoreCase))
        {
            long? rawX = GetPropertyValue<long>(x, "DownloadCountRaw");
            long? rawY = GetPropertyValue<long>(y, "DownloadCountRaw");
            if (rawX.HasValue && rawY.HasValue)
            {
                return rawX.Value.CompareTo(rawY.Value);
            }
        }

        object? valX = GetPropertyValue(x, propertyName);
        object? valY = GetPropertyValue(y, propertyName);

        if (valX is null && valY is null)
        {
            return 0;
        }
        if (valX is null)
        {
            return -1;
        }
        if (valY is null)
        {
            return 1;
        }

        if (valX is string strX && valY is string strY)
        {
            return NaturalSortHelper.CompareNatural(strX, strY);
        }

        if (valX is IComparable compX)
        {
            try
            {
                return compX.CompareTo(valY);
            }
            catch (Exception ex)
            {
                Logger.Warning("自然排序物件比較失敗，改用字串比對: {0}", ex.Message);
            }
        }

        return NaturalSortHelper.CompareNatural(valX.ToString(), valY.ToString());
    }

    private static Func<object, object?>? CreateGetter([DynamicallyAccessedMembers(DynamicallyAccessedMemberTypes.PublicProperties)] Type type, string propName)
    {
        var prop = type.GetProperty(propName, BindingFlags.Public | BindingFlags.Instance);
        if (prop is null || !prop.CanRead)
        {
            return null;
        }

        var param = Expression.Parameter(typeof(object), "obj");
        var castParam = Expression.Convert(param, type);
        var propAccess = Expression.Property(castParam, prop);
        var castResult = Expression.Convert(propAccess, typeof(object));
        return Expression.Lambda<Func<object, object?>>(castResult, param).Compile();
    }

    [UnconditionalSuppressMessage("Trimming", "IL2077", Justification = "Tuple cache key carries runtime Type of sortable UI row item")]
    private static object? GetPropertyValue(object target, string propName)
    {
        var type = target.GetType();
        var getter = GetterCache.GetOrAdd((type, propName), static key => CreateGetter(key.Item1, key.Item2));
        return getter?.Invoke(target);
    }

    private static T? GetPropertyValue<T>(object target, string propName) where T : struct
    {
        object? val = GetPropertyValue(target, propName);
        if (val is T typed)
        {
            return typed;
        }
        return null;
    }
}
