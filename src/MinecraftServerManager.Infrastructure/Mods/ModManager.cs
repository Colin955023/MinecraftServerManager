using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;
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
        string modsDir = ResolveModsDirectory(serverDirectory);
        var mods = await scanner.ScanModsAsync(modsDir, cancellationToken).ConfigureAwait(false);
        return includeDisabled ? mods : [.. mods.Where(m => m.Status == ModStatus.Enabled)];
    }

    public Task<LocalModMutationResult> SetModStateAsync(
        string serverDirectory,
        string modId,
        bool enable,
        CancellationToken cancellationToken = default) =>
        installer.SetModStateAsync(ResolveModsDirectory(serverDirectory), modId, enable, cancellationToken);

    public Task<LocalModMutationResult> DeleteModsAsync(
        string serverDirectory,
        IReadOnlyList<string> modIds,
        CancellationToken cancellationToken = default) =>
        installer.DeleteModsAsync(ResolveModsDirectory(serverDirectory), modIds, cancellationToken);

    public Task<LocalModMutationResult> ImportModAsync(
        string serverDirectory,
        string sourceFilePath,
        CancellationToken cancellationToken = default) =>
        installer.ImportLocalModAsync(ResolveModsDirectory(serverDirectory), sourceFilePath, cancellationToken);

    public Task<ModFileOperationResult> InstallOnlineModAsync(
        string serverDirectory,
        string downloadUrl,
        string fileName,
        string? expectedHash = null,
        string? hashAlgorithm = null,
        IProgress<int>? progress = null,
        CancellationToken cancellationToken = default) =>
        installer.InstallRemoteModAsync(ResolveModsDirectory(serverDirectory), downloadUrl, fileName, expectedHash, hashAlgorithm, progress, cancellationToken);

    private static string ResolveModsDirectory(string serverDirectory)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);
        string stableServerDir = SafeFileSystem.ResolveStableDirectory(serverDirectory, create: true);
        return Path.Combine(stableServerDir, ServerDefaults.ModsDirectoryName);
    }
}
