using System.Buffers;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.Domain.ValueObjects;

public readonly record struct ServerName
{
    private static readonly SearchValues<char> InvalidWindowsChars = SearchValues.Create(
        "\0\u0001\u0002\u0003\u0004\u0005\u0006\u0007\u0008\t\n\u000B\u000C\r\u000E\u000F\u0010\u0011\u0012\u0013\u0014\u0015\u0016\u0017\u0018\u0019\u001A\u001B\u001C\u001D\u001E\u001F\u007F\u0080\u0081\u0082\u0083\u0084\u0085\u0086\u0087\u0088\u0089\u008A\u008B\u008C\u008D\u008E\u008F\u0090\u0091\u0092\u0093\u0094\u0095\u0096\u0097\u0098\u0099\u009A\u009B\u009C\u009D\u009E\u009F<>:\"/\\|?*");

    public const int DefaultMaxLength = 100;

    public string Value { get; }

    private ServerName(string value)
    {
        Value = value;
    }

    public static ServerName Parse(string? value, int maxLength = DefaultMaxLength)
    {
        if (!TryValidate(value, maxLength, out string normalized, out string? error))
        {
            throw new ArgumentException(error, nameof(value));
        }

        return new ServerName(normalized);
    }

    public static bool TryParse(string? value, out ServerName result, int maxLength = DefaultMaxLength)
    {
        if (!TryValidate(value, maxLength, out string normalized, out _))
        {
            result = default;
            return false;
        }

        result = new ServerName(normalized);
        return true;
    }

    public override string ToString() => Value;

    private static bool TryValidate(string? value, int maxLength, out string normalized, out string? error)
    {
        normalized = value ?? string.Empty;
        int effectiveMaxLength = Math.Max(1, maxLength);

        ReadOnlySpan<char> span = normalized.AsSpan();
        if (span.IsEmpty || span.Trim().Length != span.Length)
        {
            error = "伺服器名稱不可為空白或包含前後空白";
            return false;
        }

        if (span.Length > effectiveMaxLength)
        {
            error = $"伺服器名稱過長（上限 {effectiveMaxLength} 字元）";
            return false;
        }

        if (span is "." or ".."
            || span[^1] is '.' or ' '
            || ContainsInvalidCharacter(span))
        {
            error = "伺服器名稱不可包含路徑片段或不合法字元";
            return false;
        }

        int dotIndex = span.IndexOf('.');
        ReadOnlySpan<char> baseName = (dotIndex >= 0 ? span[..dotIndex] : span).TrimEnd(" .");
        if (baseName.IsEmpty || IsWindowsDeviceName(span))
        {
            error = "伺服器名稱不符合 Windows 檔名規則";
            return false;
        }

        if (span.Equals(".issues", StringComparison.OrdinalIgnoreCase)
            || span.Equals(ServerDefaults.RegistryFileName, StringComparison.OrdinalIgnoreCase)
            || span.Equals("servers_config.json", StringComparison.OrdinalIgnoreCase)
            || span.StartsWith(ServerDefaults.InternalPrefix, StringComparison.OrdinalIgnoreCase))
        {
            error = "伺服器名稱與程式內部保留路徑衝突";
            return false;
        }

        error = null;
        return true;
    }

    private static bool ContainsInvalidCharacter(ReadOnlySpan<char> span) =>
        span.ContainsAny(InvalidWindowsChars);

    /// <summary>檢查單一路徑區段或檔名是否為 Windows 保留裝置名稱（如 CON、PRN、AUX、NUL、CLOCK$、COM1..9、LPT1..9 及上標變體）。</summary>
    public static bool IsWindowsDeviceName(ReadOnlySpan<char> value)
    {
        ReadOnlySpan<char> trimmed = value.TrimEnd(" .");
        int dotIndex = trimmed.IndexOf('.');
        ReadOnlySpan<char> baseName = (dotIndex >= 0 ? trimmed[..dotIndex] : trimmed).TrimEnd(" .");
        if (baseName.Equals("CON", StringComparison.OrdinalIgnoreCase)
            || baseName.Equals("PRN", StringComparison.OrdinalIgnoreCase)
            || baseName.Equals("AUX", StringComparison.OrdinalIgnoreCase)
            || baseName.Equals("NUL", StringComparison.OrdinalIgnoreCase)
            || baseName.Equals("CLOCK$", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        return baseName.Length == 4
            && (baseName.StartsWith("COM", StringComparison.OrdinalIgnoreCase)
                || baseName.StartsWith("LPT", StringComparison.OrdinalIgnoreCase))
            && baseName[3] is (>= '1' and <= '9') or '¹' or '²' or '³';
    }
}
