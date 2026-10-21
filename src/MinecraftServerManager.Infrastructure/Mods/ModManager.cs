using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.Infrastructure.Mods;

/// <summary>
/// 模組管理外觀服務實作
/// </summary>
public sealed class ModManager(
    ILocalModScanner scanner,
    IModFileInstaller installer) : IModManager
{
    public async Task<IReadOnlyList<LocalModInfo>> GetModsAsync(
        string serverDirectory,
        bool includeDisabled = true,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);
        string stableServerDir = SafeFileSystem.ResolveStableDirectory(serverDirectory, create: true);
        string modsDir = Path.Combine(stableServerDir, "mods");

        var mods = await scanner.ScanModsAsync(modsDir, cancellationToken).ConfigureAwait(false);
        return includeDisabled ? mods : [.. mods.Where(m => m.Status == ModStatus.Enabled)];
    }

    public Task<LocalModMutationResult> SetModStateAsync(
        string serverDirectory,
        string modId,
        bool enable,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);
        string stableServerDir = SafeFileSystem.ResolveStableDirectory(serverDirectory, create: true);
        string modsDir = Path.Combine(stableServerDir, "mods");
        return installer.SetModStateAsync(modsDir, modId, enable, cancellationToken);
    }

    public Task<LocalModMutationResult> DeleteModsAsync(
        string serverDirectory,
        IReadOnlyList<string> modIds,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);
        string stableServerDir = SafeFileSystem.ResolveStableDirectory(serverDirectory, create: true);
        string modsDir = Path.Combine(stableServerDir, "mods");
        return installer.DeleteModsAsync(modsDir, modIds, cancellationToken);
    }

    public Task<LocalModMutationResult> ImportModAsync(
        string serverDirectory,
        string sourceFilePath,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);
        string stableServerDir = SafeFileSystem.ResolveStableDirectory(serverDirectory, create: true);
        string modsDir = Path.Combine(stableServerDir, "mods");
        return installer.ImportLocalModAsync(modsDir, sourceFilePath, cancellationToken);
    }

    public Task<ModFileOperationResult> InstallOnlineModAsync(
        string serverDirectory,
        string downloadUrl,
        string fileName,
        string? expectedHash = null,
        string? hashAlgorithm = null,
        IProgress<int>? progress = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);
        string stableServerDir = SafeFileSystem.ResolveStableDirectory(serverDirectory, create: true);
        string modsDir = Path.Combine(stableServerDir, "mods");
        return installer.InstallRemoteModAsync(modsDir, downloadUrl, fileName, expectedHash, hashAlgorithm, progress, cancellationToken);
    }
}
