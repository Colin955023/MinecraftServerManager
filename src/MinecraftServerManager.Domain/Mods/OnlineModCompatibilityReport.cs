namespace MinecraftServerManager.Domain.Mods;

/// <summary>
/// 線上模組相容性與相依性分析結果
/// </summary>
public sealed record OnlineModCompatibilityReport
{
    public IReadOnlyList<string> HardErrors { get; }
    public IReadOnlyList<string> Warnings { get; }
    public IReadOnlyList<string> Notes { get; }
    public IReadOnlyList<string> MissingRequiredDependencies { get; }
    public IReadOnlyList<string> OptionalDependencies { get; }
    public IReadOnlyList<string> IncompatibleInstalled { get; }
    public IReadOnlyList<string> InstalledVersionMismatches { get; }
    public IReadOnlyList<string> EmbeddedDependencies { get; }
    public IReadOnlyList<string> AlreadyInstalled { get; }

    public bool HasHardErrors => HardErrors.Count > 0;
    public bool IsCompatible => HardErrors.Count == 0 && IncompatibleInstalled.Count == 0 && MissingRequiredDependencies.Count == 0;
    public bool Compatible => IsCompatible;
    public IReadOnlyList<string> MissingRequired => MissingRequiredDependencies;
    public IReadOnlyList<string> Incompatible => IncompatibleInstalled;
    public IReadOnlyList<string> Optional => OptionalDependencies;

    public OnlineModCompatibilityReport(
        IEnumerable<string>? hardErrors = null,
        IEnumerable<string>? warnings = null,
        IEnumerable<string>? notes = null,
        IEnumerable<string>? missingRequiredDependencies = null,
        IEnumerable<string>? optionalDependencies = null,
        IEnumerable<string>? incompatibleInstalled = null,
        IEnumerable<string>? installedVersionMismatches = null,
        IEnumerable<string>? embeddedDependencies = null,
        IEnumerable<string>? alreadyInstalled = null)
    {
        HardErrors = [.. hardErrors ?? []];
        Warnings = [.. warnings ?? []];
        Notes = [.. notes ?? []];
        MissingRequiredDependencies = [.. missingRequiredDependencies ?? []];
        OptionalDependencies = [.. optionalDependencies ?? []];
        IncompatibleInstalled = [.. incompatibleInstalled ?? []];
        InstalledVersionMismatches = [.. installedVersionMismatches ?? []];
        EmbeddedDependencies = [.. embeddedDependencies ?? []];
        AlreadyInstalled = [.. alreadyInstalled ?? []];
    }
}
