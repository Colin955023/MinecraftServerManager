using MinecraftServerManager.Core.Ports;

namespace MinecraftServerManager.Infrastructure.FileSystem;

/// <summary>
/// 以 <see cref="SafeFileSystem"/> 實作之呈現層本機檔案系統存取
/// </summary>
public sealed class LocalFileSystem : ILocalFileSystem
{
    public bool FileExists(string? path) =>
        !string.IsNullOrWhiteSpace(path) && SafeFileSystem.FileExists(path);

    public bool DirectoryExists(string? path) =>
        !string.IsNullOrWhiteSpace(path) && SafeFileSystem.DirectoryExists(path);

    public void CreateDirectory(string path)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        SafeFileSystem.CreateDirectory(path);
    }

    public DateTime? GetDirectoryLastWriteTime(string path) =>
        DirectoryExists(path) ? SafeFileSystem.GetDirectoryLastWriteTime(path) : null;
}
