using System.Globalization;

namespace MinecraftServerManager.Core.Utilities;

public static class UnitFormatter
{
    private static readonly string[] Units = ["B", "KiB", "MiB", "GiB"];

    public static string FormatBytes(long size)
    {
        long value = Math.Max(0, size);
        double scaled = value;

        foreach (string unit in Units)
        {
            if (scaled < 1024)
            {
                return unit == "B"
                    ? $"{(long)scaled} B"
                    : string.Create(CultureInfo.InvariantCulture, $"{scaled:0.0} {unit}");
            }

            scaled /= 1024;
        }

        return string.Create(CultureInfo.InvariantCulture, $"{scaled:0.0} TiB");
    }
}
