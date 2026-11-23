using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.Core.Ports;

/// <summary>伺服器完整性檢驗結果</summary>
public sealed record ServerIntegrityResult(bool HasMissing, IReadOnlyList<string> MissingFiles);

/// <summary>伺服器關鍵檔案與結構完整性檢驗服務合約</summary>
public interface IServerIntegrityService
{
    /// <summary>伺服器核心關鍵啟動檔案是否存在</summary>
    public Task<ServerIntegrityResult> CheckImportantFilesAsync(string serverPath, LoaderKind loader, CancellationToken cancellationToken = default);
}
