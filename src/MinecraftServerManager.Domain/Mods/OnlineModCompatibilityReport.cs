namespace MinecraftServerManager.Domain.Mods;

/// <summary>
/// 線上模組相容性與依賴分析結果
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
        HardErrors = Common.CollectionUtilities.ToReadOnlyList(hardErrors);
        Warnings = Common.CollectionUtilities.ToReadOnlyList(warnings);
        Notes = Common.CollectionUtilities.ToReadOnlyList(notes);
        MissingRequiredDependencies = Common.CollectionUtilities.ToReadOnlyList(missingRequiredDependencies);
        OptionalDependencies = Common.CollectionUtilities.ToReadOnlyList(optionalDependencies);
        IncompatibleInstalled = Common.CollectionUtilities.ToReadOnlyList(incompatibleInstalled);
        InstalledVersionMismatches = Common.CollectionUtilities.ToReadOnlyList(installedVersionMismatches);
        EmbeddedDependencies = Common.CollectionUtilities.ToReadOnlyList(embeddedDependencies);
        AlreadyInstalled = Common.CollectionUtilities.ToReadOnlyList(alreadyInstalled);
    }
}
