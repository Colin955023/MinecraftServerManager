using System.Globalization;

namespace MinecraftServerManager.Core.Utilities;

public static class UnitFormatter
{
    public static double BytesToMiB(long size) => size / (1024d * 1024d);

    public static string FormatBytes(long size)
    {
        long value = Math.Max(0, size);
        double scaled = value;
        string[] units = new[] { "B", "KiB", "MiB", "GiB" };

        foreach (string? unit in units)
        {
            if (scaled < 1024)
            {
                return unit == "B"
                    ? $"{(long)scaled} B"
                    : scaled.ToString("0.0", CultureInfo.InvariantCulture) + $" {unit}";
            }

            scaled /= 1024;
        }

        return scaled.ToString("0.0", CultureInfo.InvariantCulture) + " TiB";
    }
}
