using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.Infrastructure.Mods;

/// <summary>呈現層模組檔案輔助服務：路徑解析、暫存清理與官方來源判定</summary>
public sealed class ModFileService : IModFileService
{
    public bool IsOfficialModrinthSource(string? url) => ModFileInstaller.IsOfficialModrinthSource(url);

    public Task CleanupStagingDirectoryAsync(string serverPath, CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(serverPath))
        {
            return Task.CompletedTask;
        }

        return Task.Run(() => ModFileInstaller.CleanupStagingDirectory(Path.Combine(serverPath, ServerDefaults.ModsDirectoryName)), cancellationToken);
    }

    public Task<string> EnsureModsDirectoryAsync(string serverPath, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverPath);
        return Task.Run(() => SafeFileSystem.CreateDirectory(Path.Combine(serverPath, ServerDefaults.ModsDirectoryName)), cancellationToken);
    }

    public Task<string> ResolveModFilePathAsync(string serverPath, string fileName, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverPath);
        return Task.Run(() => ResolveModFilePath(serverPath, fileName), cancellationToken);
    }

    public Task DeleteModFileVariantsAsync(string serverPath, string fileName, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverPath);
        ArgumentException.ThrowIfNullOrWhiteSpace(fileName);
        return Task.Run(() => DeleteModFileVariants(serverPath, fileName), cancellationToken);
    }

    private static string ResolveModFilePath(string serverPath, string fileName)
    {
        string modsDir = Path.Combine(serverPath, ServerDefaults.ModsDirectoryName);
        if (!ModFileVariants.TryGetPaths(modsDir, fileName, out string? enabledPath, out string? disabledPath))
        {
            return modsDir;
        }

        return SafeFileSystem.FileExists(enabledPath) ? enabledPath
            : SafeFileSystem.FileExists(disabledPath) ? disabledPath
            : modsDir;
    }

    private static void DeleteModFileVariants(string serverPath, string fileName)
    {
        string modsPath = Path.Combine(serverPath, ServerDefaults.ModsDirectoryName);
        if (!SafeFileSystem.DirectoryExists(modsPath))
        {
            return;
        }

        string modsDir = SafeFileSystem.ResolveStableDirectory(modsPath);
        if (ModFileVariants.TryGetPaths(modsDir, fileName, out string? enabledPath, out string? disabledPath))
        {
            ModFileVariants.DeleteVariants(modsDir, enabledPath, disabledPath);
        }
    }
}
