namespace MinecraftServerManager.Domain.Mods;

/// <summary>
/// 線上模組資訊（Modrinth 等遠端來源搜尋與探索結果快照）
/// </summary>
public sealed record OnlineModInfo(
    string ProjectId,
    string Slug,
    string Name,
    string Author,
    string Description = "",
    string LatestVersion = "",
    int Downloads = 0,
    string ServerSide = "",
    string ClientSide = "");
