namespace MinecraftServerManager.Domain.Servers;

/// <summary>LoaderKind 字串解析的唯一入口：不分大小寫、僅接受已定義之列舉名稱（拒絕純數字字串）</summary>
public static class LoaderKinds
{
    public static bool TryParse(string? value, out LoaderKind kind)
    {
        ReadOnlySpan<char> text = value.AsSpan().Trim();
        if (text.IsEmpty || !char.IsAsciiLetter(text[0]))
        {
            kind = LoaderKind.Unknown;
            return false;
        }

        if (Enum.TryParse(text, ignoreCase: true, out kind) && Enum.IsDefined(kind))
        {
            return true;
        }

        kind = LoaderKind.Unknown;
        return false;
    }

    public static LoaderKind ParseOrDefault(string? value, LoaderKind fallback = LoaderKind.Unknown) =>
        TryParse(value, out var kind) ? kind : fallback;
}
