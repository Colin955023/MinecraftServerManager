using System.Text.RegularExpressions;

namespace MinecraftServerManager.Infrastructure.Java;

public readonly record struct JavaVersionDetails(
    int MajorVersion,
    bool Is64Bit,
    string? Vendor);

public static partial class JavaVersionParser
{
    public static int? ParseMajor(string output) => ParseDetails(output)?.MajorVersion;

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

        bool is64Bit = output.Contains("64-Bit", StringComparison.OrdinalIgnoreCase) ||
                      output.Contains("x86_64", StringComparison.OrdinalIgnoreCase) ||
                      output.Contains("amd64", StringComparison.OrdinalIgnoreCase) ||
                      !output.Contains("32-Bit", StringComparison.OrdinalIgnoreCase);

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
