using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.Infrastructure.Mods;

/// <summary>呈現層模組檔案輔助服務：路徑解析、暫存清理與官方來源判定</summary>
public sealed class ModFileService : IModFileService
{
    private const string DisabledSuffix = ".disabled";

    public bool IsOfficialModrinthSource(string? url) => ModFileInstaller.IsOfficialModrinthSource(url);

    public void CleanupStagingDirectory(string serverPath)
    {
        if (string.IsNullOrWhiteSpace(serverPath))
        {
            return;
        }

        ModFileInstaller.CleanupStagingDirectory(Path.Combine(serverPath, ServerDefaults.ModsDirectoryName));
    }

    public string EnsureModsDirectory(string serverPath)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverPath);
        return SafeFileSystem.CreateDirectory(Path.Combine(serverPath, ServerDefaults.ModsDirectoryName));
    }

    public string ResolveModFilePath(string serverPath, string fileName)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverPath);
        string modsDir = Path.Combine(serverPath, ServerDefaults.ModsDirectoryName);
        if (string.IsNullOrWhiteSpace(fileName))
        {
            return modsDir;
        }

        string filePath = Path.Combine(modsDir, fileName);
        if (SafeFileSystem.FileExists(filePath))
        {
            return filePath;
        }

        string disabledPath = filePath + DisabledSuffix;
        return SafeFileSystem.FileExists(disabledPath) ? disabledPath : modsDir;
    }

    public void DeleteModFileVariants(string serverPath, string fileName)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverPath);
        ArgumentException.ThrowIfNullOrWhiteSpace(fileName);

        string filePath = Path.Combine(serverPath, ServerDefaults.ModsDirectoryName, fileName);
        foreach (string candidate in (string[])[filePath, filePath + DisabledSuffix])
        {
            if (SafeFileSystem.FileExists(candidate))
            {
                SafeFileSystem.DeleteWithin(serverPath, candidate);
            }
        }
    }
}
