namespace MinecraftServerManager.Domain.Mods;

public sealed record ModFile(
    string Filename,
    string Url = "",
    bool IsPrimary = false,
    long Size = 0,
    IReadOnlyDictionary<string, string>? Hashes = null);
