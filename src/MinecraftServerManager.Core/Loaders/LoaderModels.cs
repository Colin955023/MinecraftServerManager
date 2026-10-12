using System.Text.Json.Serialization;

namespace MinecraftServerManager.Core.Loaders;

/// <summary>
/// 載入器版本資訊
/// </summary>
public sealed record LoaderVersion(
    string Version,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    string? Url = null,
    bool Stable = true,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    string? MinecraftVersion = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    IReadOnlyList<string>? CompatibleGameVersions = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    int? JavaMajor = null,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    string? Build = null);

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
