namespace MinecraftServerManager.Domain.ValueObjects;

public readonly record struct ServerName
{
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

        if (normalized.Length == 0 || normalized != normalized.Trim())
        {
            error = "伺服器名稱不可為空白或包含前後空白";
            return false;
        }

        if (normalized.Length > effectiveMaxLength)
        {
            error = $"伺服器名稱過長（上限 {effectiveMaxLength} 字元）";
            return false;
        }

        if (normalized is "." or ".."
            || normalized.EndsWith('.')
            || normalized.EndsWith(' ')
            || normalized.Any(IsInvalidWindowsNameCharacter))
        {
            error = "伺服器名稱不可包含路徑片段或不合法字元";
            return false;
        }

        int dotIndex = normalized.IndexOf('.');
        string baseName = (dotIndex >= 0 ? normalized[..dotIndex] : normalized).TrimEnd(' ', '.');
        if (baseName.Length == 0 || IsWindowsDeviceName(baseName))
        {
            error = "伺服器名稱不符合 Windows 檔名規則";
            return false;
        }

        string comparisonName = normalized.ToLowerInvariant();
        if (comparisonName is ".issues" or "servers_config.json" || comparisonName.StartsWith(".msm-", StringComparison.Ordinal))
        {
            error = "伺服器名稱與程式內部保留路徑衝突";
            return false;
        }

        error = null;
        return true;
    }

    private static bool IsInvalidWindowsNameCharacter(char character) =>
        char.IsControl(character) || character is '<' or '>' or ':' or '"' or '/' or '\\' or '|' or '?' or '*';

    private static bool IsWindowsDeviceName(string baseName)
    {
        if (baseName.Equals("CON", StringComparison.OrdinalIgnoreCase)
            || baseName.Equals("PRN", StringComparison.OrdinalIgnoreCase)
            || baseName.Equals("AUX", StringComparison.OrdinalIgnoreCase)
            || baseName.Equals("NUL", StringComparison.OrdinalIgnoreCase)
            || baseName.Equals("CLOCK$", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        if (baseName.Length == 4
            && (baseName.StartsWith("COM", StringComparison.OrdinalIgnoreCase)
                || baseName.StartsWith("LPT", StringComparison.OrdinalIgnoreCase)))
        {
            string suffix = baseName[3..];
            return suffix.All(character => character is (>= '1' and <= '9') or '¹' or '²' or '³');
        }

        return false;
    }
}
