using MinecraftServerManager.Core.Ports;

namespace MinecraftServerManager.Infrastructure.FileSystem;

/// <summary>以背景執行緒執行之呈現層檔案系統操作</summary>
public sealed class LocalFileSystem : ILocalFileSystem
{
    public Task<bool> FileExistsAsync(string? path, CancellationToken cancellationToken = default) =>
        string.IsNullOrWhiteSpace(path)
            ? Task.FromResult(false)
            : Task.Run(() => SafeFileSystem.FileExists(path), cancellationToken);

    public Task<bool> DirectoryExistsAsync(string? path, CancellationToken cancellationToken = default) =>
        string.IsNullOrWhiteSpace(path)
            ? Task.FromResult(false)
            : Task.Run(() => SafeFileSystem.DirectoryExists(path), cancellationToken);

    public Task CreateDirectoryAsync(string path, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        return Task.Run(() => SafeFileSystem.CreateDirectory(path), cancellationToken);
    }

    public Task<DateTimeOffset?> GetDirectoryLastWriteTimeAsync(string path, CancellationToken cancellationToken = default) =>
        string.IsNullOrWhiteSpace(path)
            ? Task.FromResult<DateTimeOffset?>(null)
            : Task.Run(
                () => SafeFileSystem.TryGetDirectoryLastWriteTime(path),
                cancellationToken);
}
