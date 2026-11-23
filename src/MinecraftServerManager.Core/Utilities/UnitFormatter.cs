using System.Globalization;

namespace MinecraftServerManager.Core.Utilities;

/// <summary>位元組與常見儲存單位格式化工具</summary>
public static class UnitFormatter
{
    private static readonly string[] Units = ["KiB", "MiB", "GiB", "TiB"];

    public static string FormatBytes(long size)
    {
        long value = Math.Max(0, size);
        if (value < 1024)
        {
            return string.Create(CultureInfo.InvariantCulture, $"{value} B");
        }

        double scaled = value / 1024d;
        int unitIndex = 0;

        // 以四捨五入至一位小數後的值判斷進位，避免 1023.95 顯示為「1024.0 KiB」
        while (unitIndex < Units.Length - 1 && Math.Round(scaled, 1, MidpointRounding.AwayFromZero) >= 1024)
        {
            scaled /= 1024;
            unitIndex++;
        }

        return string.Create(CultureInfo.InvariantCulture, $"{scaled:0.0} {Units[unitIndex]}");
    }
}
