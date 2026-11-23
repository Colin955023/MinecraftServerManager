namespace MinecraftServerManager.Domain.ValueObjects;

/// <summary>經驗證的 Minecraft 版本字串值物件</summary>
public readonly record struct MinecraftVersion
{
    private readonly string? _value;

    /// <summary>版本文字；<c>default</c> 執行個體為空字串</summary>
    public string Value => _value ?? string.Empty;

    /// <summary>是否為經驗證建立之版本（非 <c>default</c>）</summary>
    public bool IsValid => _value is not null;

    private MinecraftVersion(string value)
    {
        _value = value;
    }

    public static MinecraftVersion Parse(string? value)
    {
        if (!TryParse(value, out var version))
        {
            throw new ArgumentException($"無效的 Minecraft 版本：{(string.IsNullOrWhiteSpace(value) ? "（空白）" : value.Trim())}", nameof(value));
        }

        return version;
    }

    public static bool TryParse(string? value, out MinecraftVersion version)
    {
        ReadOnlySpan<char> text = value.AsSpan().Trim();
        if (text.IsEmpty || text.Equals("unknown", StringComparison.OrdinalIgnoreCase))
        {
            version = default;
            return false;
        }

        version = new MinecraftVersion(text.Length == value!.Length ? value : text.ToString());
        return true;
    }

    public override string ToString() => Value;
}
