namespace MinecraftServerManager.Domain.Mods;

/// <summary>線上模組版本所包含的下載檔案資訊</summary>
public sealed record ModFile(
    string FileName,
    string Url = "",
    bool IsPrimary = false,
    long Size = 0,
    IReadOnlyDictionary<string, string>? Hashes = null);
