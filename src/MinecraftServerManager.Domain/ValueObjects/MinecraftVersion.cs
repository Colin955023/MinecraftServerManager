namespace MinecraftServerManager.Domain.ValueObjects;

public readonly record struct MinecraftVersion
{
    public string Value { get; }

    private MinecraftVersion(string value)
    {
        Value = value;
    }

    public static MinecraftVersion Parse(string? value)
    {
        if (!TryParse(value, out var version))
        {
            throw new ArgumentException("Minecraft 版本不可為空白", nameof(value));
        }

        return version;
    }

    public static bool TryParse(string? value, out MinecraftVersion version)
    {
        string normalized = value?.Trim() ?? string.Empty;
        if (normalized.Length == 0)
        {
            version = default;
            return false;
        }

        version = new MinecraftVersion(normalized);
        return true;
    }

    public override string ToString() => Value;
}
