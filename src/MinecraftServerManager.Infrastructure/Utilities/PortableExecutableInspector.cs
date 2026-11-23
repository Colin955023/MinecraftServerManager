using System.Reflection.PortableExecutable;
using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.Infrastructure.Utilities;

/// <summary>讀取 Windows 執行檔標頭</summary>
public static class PortableExecutableInspector
{
    /// <summary>讀取 PE 檔案之目標機器類型；非合法 PE 或無法讀取時回傳 null</summary>
    public static Machine? TryReadMachine(string filePath) =>
        TryReadHeaders(filePath) is { } headers ? headers.CoffHeader.Machine : null;

    /// <summary>讀取可執行檔（非 DLL）之目標機器類型；非合法 PE 執行檔時回傳 null</summary>
    public static Machine? TryReadExecutableMachine(string filePath) =>
        TryReadHeaders(filePath) is { IsDll: false } headers ? headers.CoffHeader.Machine : null;

    /// <summary>只解析標頭，不建立整份映像；無 MZ/PE 簽章時會被視為 COFF 物件檔，須排除</summary>
    private static PEHeaders? TryReadHeaders(string filePath)
    {
        try
        {
            using var stream = SafeFileSystem.OpenRead(filePath, FileShare.Read);
            var headers = new PEHeaders(stream);
            return headers.IsCoffOnly ? null : headers;
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or BadImageFormatException)
        {
            return null;
        }
    }

    /// <summary>機器類型是否為 64 位元架構</summary>
    public static bool Is64Bit(Machine machine) => machine is Machine.Amd64 or Machine.Arm64 or Machine.IA64;
}
