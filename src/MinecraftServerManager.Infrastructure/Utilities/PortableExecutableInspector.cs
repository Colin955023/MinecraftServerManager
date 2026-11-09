using System.Reflection.PortableExecutable;
using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.Infrastructure.Utilities;

/// <summary>
/// 以 .NET 原生 PEReader 讀取 Windows 執行檔標頭（取代手寫 DOS/PE 位元組解析）
/// </summary>
public static class PortableExecutableInspector
{
    /// <summary>
    /// 讀取 PE 檔案之目標機器類型；非合法 PE 或無法讀取時回傳 null
    /// </summary>
    public static Machine? TryReadMachine(string filePath)
    {
        try
        {
            using var reader = new PEReader(SafeFileSystem.OpenRead(filePath, FileShare.Read));
            // 無 MZ/PE 簽章時 PEReader 會視為 COFF 物件檔，須排除
            return reader.PEHeaders.IsCoffOnly ? null : reader.PEHeaders.CoffHeader.Machine;
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or BadImageFormatException)
        {
            return null;
        }
    }

    /// <summary>
    /// 判斷機器類型是否為 64 位元架構
    /// </summary>
    public static bool Is64Bit(Machine machine) => machine is Machine.Amd64 or Machine.Arm64 or Machine.IA64;
}
