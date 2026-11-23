using System.Collections.Frozen;

namespace MinecraftServerManager.Domain.Servers;

/// <summary>LoaderKind 字串解析入口：不分大小寫精確比對名稱</summary>
public static class LoaderKinds
{
    private static readonly FrozenDictionary<string, LoaderKind> ByName =
        Enum.GetValues<LoaderKind>().ToFrozenDictionary(static kind => kind.ToString(), StringComparer.OrdinalIgnoreCase);

    private static readonly FrozenDictionary<string, LoaderKind>.AlternateLookup<ReadOnlySpan<char>> ByNameSpan =
        ByName.GetAlternateLookup<ReadOnlySpan<char>>();

    public static bool TryParse(string? value, out LoaderKind kind)
    {
        if (ByNameSpan.TryGetValue(value.AsSpan().Trim(), out kind))
        {
            return true;
        }

        kind = LoaderKind.Unknown;
        return false;
    }

    public static LoaderKind ParseOrDefault(string? value, LoaderKind fallback = LoaderKind.Unknown) =>
        TryParse(value, out var kind) ? kind : fallback;

    private static readonly FrozenDictionary<string, LoaderKind> ByModrinthId = Enum.GetValues<LoaderKind>()
        .Where(static kind => kind != LoaderKind.Unknown)
        .ToFrozenDictionary(static kind => ToModrinthId(kind), static kind => kind, StringComparer.OrdinalIgnoreCase);

    /// <summary>取得 Modrinth API 使用之小寫載入器識別字；未知載入器為 unknown</summary>
    public static string ToModrinthId(LoaderKind loader) => loader switch
    {
        LoaderKind.Vanilla => "vanilla",
        LoaderKind.Paper => "paper",
        LoaderKind.Fabric => "fabric",
        LoaderKind.Forge => "forge",
        LoaderKind.NeoForge => "neoforge",
        LoaderKind.Quilt => "quilt",
        _ => "unknown",
    };

    /// <summary>解析 Modrinth 載入器識別字（不分大小寫）；無對映者（含 unknown、datapack）回傳 false</summary>
    public static bool TryParseModrinthId(string? id, out LoaderKind kind)
    {
        if (id is not null && ByModrinthId.TryGetValue(id, out kind))
        {
            return true;
        }

        kind = LoaderKind.Unknown;
        return false;
    }
}
