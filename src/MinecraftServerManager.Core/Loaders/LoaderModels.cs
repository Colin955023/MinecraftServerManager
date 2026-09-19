namespace MinecraftServerManager.Core.Loaders;

/// <summary>
/// 載入器版本資訊
/// </summary>
public sealed record LoaderVersion(
    string Version,
    string? Url = null,
    bool Stable = true,
    string? MinecraftVersion = null,
    IReadOnlyList<string>? CompatibleGameVersions = null);

/// <summary>
/// 載入器安裝器描述
/// </summary>
public sealed record LoaderInstallerSpec(
    string Url,
    string? ExpectedHash = null,
    string? HashAlgorithm = null,
    string Version = "");

/// <summary>
/// 載入器安裝進度快照
/// </summary>
public sealed record LoaderInstallProgress(
    string Phase,
    string Message,
    int PercentCompleted);
