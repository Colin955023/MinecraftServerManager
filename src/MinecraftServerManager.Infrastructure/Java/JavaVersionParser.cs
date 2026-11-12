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

        string? vendor = DetectVendor(output);

        return new JavaVersionDetails(effectiveMajor, is64Bit, vendor);
    }

    private static string? DetectVendor(string output)
    {
        if (output.Contains("Microsoft", StringComparison.OrdinalIgnoreCase))
        {
            return "Microsoft";
        }

        if (output.Contains("Adoptium", StringComparison.OrdinalIgnoreCase) ||
            output.Contains("Temurin", StringComparison.OrdinalIgnoreCase))
        {
            return "Eclipse Adoptium";
        }

        if (output.Contains("Zulu", StringComparison.OrdinalIgnoreCase) ||
            output.Contains("Azul", StringComparison.OrdinalIgnoreCase))
        {
            return "Azul Zulu";
        }

        if (output.Contains("Corretto", StringComparison.OrdinalIgnoreCase))
        {
            return "Amazon Corretto";
        }

        if (output.Contains("Liberica", StringComparison.OrdinalIgnoreCase) ||
            output.Contains("BellSoft", StringComparison.OrdinalIgnoreCase))
        {
            return "BellSoft Liberica";
        }

        if (output.Contains("Semeru", StringComparison.OrdinalIgnoreCase) ||
            output.Contains("IBM", StringComparison.OrdinalIgnoreCase))
        {
            return "IBM Semeru";
        }

        if (output.Contains("Java(TM)", StringComparison.OrdinalIgnoreCase) ||
            output.Contains("Oracle", StringComparison.OrdinalIgnoreCase))
        {
            return "Oracle";
        }

        if (output.Contains("OpenJDK", StringComparison.OrdinalIgnoreCase))
        {
            return "OpenJDK";
        }

        return null;
    }

    [GeneratedRegex("version\\s+\\\"(?<major>\\d+)(?:\\.(?<minor>\\d+))?", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex VersionPattern();
}
