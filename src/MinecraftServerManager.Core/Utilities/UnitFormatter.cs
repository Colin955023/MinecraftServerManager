using System.Globalization;

namespace MinecraftServerManager.Core.Utilities;

public static class UnitFormatter
{
    private static readonly string[] Units = ["B", "KiB", "MiB", "GiB"];

    public static double BytesToMiB(long size) => size / (1024d * 1024d);

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
                    : scaled.ToString("0.0", CultureInfo.InvariantCulture) + $" {unit}";
            }

            scaled /= 1024;
        }

        return scaled.ToString("0.0", CultureInfo.InvariantCulture) + " TiB";
    }
}
