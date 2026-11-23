using System.Buffers;
using System.Text.RegularExpressions;

namespace MinecraftServerManager.Infrastructure.Java;

public readonly record struct JavaVersionDetails(
    int MajorVersion,
    bool Is64Bit,
    string? Vendor);

public static partial class JavaVersionParser
{
    private static readonly SearchValues<string> Bit32Markers = SearchValues.Create(["32-Bit", "x86_32"], StringComparison.OrdinalIgnoreCase);
    private static readonly SearchValues<string> Bit64Markers = SearchValues.Create(["64-Bit", "x86_64", "amd64", "aarch64"], StringComparison.OrdinalIgnoreCase);

    /// <summary>廠牌關鍵字對照；依序比對，較明確的發行版需排在通用字樣（Oracle、OpenJDK）之前</summary>
    private static readonly (string Keyword, string Vendor)[] VendorMarkers =
    [
        ("Microsoft", "Microsoft"),
        ("Temurin", "Eclipse Adoptium"),
        ("Adoptium", "Eclipse Adoptium"),
        ("AdoptOpenJDK", "Eclipse Adoptium"),
        ("Zulu", "Azul Zulu"),
        ("Azul", "Azul Zulu"),
        ("Corretto", "Amazon Corretto"),
        ("Liberica", "BellSoft Liberica"),
        ("BellSoft", "BellSoft Liberica"),
        ("Semeru", "IBM Semeru"),
        ("IBM", "IBM Semeru"),
        ("GraalVM", "GraalVM"),
        ("JetBrains", "JetBrains Runtime"),
        ("SapMachine", "SAP SapMachine"),
        ("Dragonwell", "Alibaba Dragonwell"),
        ("Red_Hat", "Red Hat"),
        ("Red Hat", "Red Hat"),
        ("Java(TM)", "Oracle"),
        ("Oracle", "Oracle"),
        ("OpenJDK", "OpenJDK"),
    ];

    public static JavaVersionDetails? ParseDetails(string output)
    {
        ArgumentNullException.ThrowIfNull(output);
        var match = VersionPattern().Match(output);
        if (!match.Success || !int.TryParse(match.Groups["major"].Value, out int major))
        {
            return null;
        }

        int effectiveMajor = major;
        if (major == 1)
        {
            if (!int.TryParse(match.Groups["minor"].Value, out int legacyMajor))
            {
                return null;
            }

            effectiveMajor = legacyMajor;
        }

        ReadOnlySpan<char> span = output.AsSpan();
        bool is64Bit = !span.ContainsAny(Bit32Markers) && span.ContainsAny(Bit64Markers);

        return new JavaVersionDetails(effectiveMajor, is64Bit, DetectVendor(span));
    }

    private static string? DetectVendor(ReadOnlySpan<char> output)
    {
        foreach (var (keyword, vendor) in VendorMarkers)
        {
            if (output.Contains(keyword, StringComparison.OrdinalIgnoreCase))
            {
                return vendor;
            }
        }

        return null;
    }

    [GeneratedRegex("version\\s+\\\"(?<major>\\d+)(?:\\.(?<minor>\\d+))?", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex VersionPattern();
}
