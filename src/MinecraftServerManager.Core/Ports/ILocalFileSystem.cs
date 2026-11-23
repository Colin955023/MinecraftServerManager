namespace MinecraftServerManager.Core.Ports;

/// <summary>呈現層使用之本機檔案系統存在性檢查與目錄建立介面（皆於背景執行緒執行）</summary>
public interface ILocalFileSystem
{
    /// <summary>檔案是否存在</summary>
    public Task<bool> FileExistsAsync(string? path, CancellationToken cancellationToken = default);

    /// <summary>目錄是否存在</summary>
    public Task<bool> DirectoryExistsAsync(string? path, CancellationToken cancellationToken = default);

    /// <summary>建立目錄（已存在時不做任何事）</summary>
    public Task CreateDirectoryAsync(string path, CancellationToken cancellationToken = default);

    /// <summary>取得目錄最後修改時間；目錄不存在時回傳 null</summary>
    public Task<DateTimeOffset?> GetDirectoryLastWriteTimeAsync(string path, CancellationToken cancellationToken = default);
}
