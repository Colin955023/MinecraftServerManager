using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.Infrastructure.Mods;

/// <summary>模組管理外觀：以伺服器目錄解析 mods 資料夾後委派掃描與檔案異動</summary>
public sealed class ModManager : IModManager
{
    private readonly ILocalModScanner _scanner;
    private readonly ModFileInstaller _installer;

    public ModManager(ILocalModScanner scanner, ModFileInstaller installer)
    {
        ArgumentNullException.ThrowIfNull(scanner);
        ArgumentNullException.ThrowIfNull(installer);
        _scanner = scanner;
        _installer = installer;
    }

    public async Task<IReadOnlyList<LocalModInfo>> GetModsAsync(
        string serverDirectory,
        bool includeDisabled = true,
        CancellationToken cancellationToken = default)
    {
        string modsDir = await ResolveModsDirectoryAsync(serverDirectory, cancellationToken).ConfigureAwait(false);
        var mods = await _scanner.ScanModsAsync(modsDir, cancellationToken).ConfigureAwait(false);
        return includeDisabled ? mods : [.. mods.Where(static m => m.Status == ModStatus.Enabled)];
    }

    public Task<LocalModMutationResult> SetModStateAsync(
        string serverDirectory,
        string modId,
        bool enable,
        CancellationToken cancellationToken = default) =>
        // 啟停前置檔案檢查為同步 I/O，以 Task.Run 避免佔用呼叫端（UI）執行緒
        Task.Run(() => ModFileInstaller.SetModStateAsync(ResolveModsDirectory(serverDirectory), modId, enable, cancellationToken), cancellationToken);

    public async Task<LocalModMutationResult> DeleteModsAsync(
        string serverDirectory,
        IReadOnlyList<string> modIds,
        CancellationToken cancellationToken = default) =>
        await ModFileInstaller.DeleteModsAsync(await ResolveModsDirectoryAsync(serverDirectory, cancellationToken).ConfigureAwait(false), modIds, cancellationToken).ConfigureAwait(false);

    public async Task<LocalModMutationResult> ImportModAsync(
        string serverDirectory,
        string sourceFilePath,
        CancellationToken cancellationToken = default) =>
        await ModFileInstaller.ImportLocalModAsync(await ResolveModsDirectoryAsync(serverDirectory, cancellationToken).ConfigureAwait(false), sourceFilePath, cancellationToken).ConfigureAwait(false);

    public Task<ModFileOperationResult> InstallOnlineModAsync(
        string serverDirectory,
        string downloadUrl,
        string fileName,
        string? expectedHash = null,
        string? hashAlgorithm = null,
        IProgress<int>? progress = null,
        CancellationToken cancellationToken = default) =>
        Task.Run(() => _installer.InstallRemoteModAsync(ResolveModsDirectory(serverDirectory), downloadUrl, fileName, expectedHash, hashAlgorithm, progress, cancellationToken), cancellationToken);

    /// <summary>目錄解析含同步檔案系統 I/O，一律移至背景執行緒</summary>
    private static Task<string> ResolveModsDirectoryAsync(string serverDirectory, CancellationToken cancellationToken)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);
        return Task.Run(() => ResolveModsDirectory(serverDirectory), cancellationToken);
    }

    private static string ResolveModsDirectory(string serverDirectory)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);
        string stableServerDir = SafeFileSystem.ResolveStableDirectory(serverDirectory, create: true);
        return Path.Combine(stableServerDir, ServerDefaults.ModsDirectoryName);
    }
}
