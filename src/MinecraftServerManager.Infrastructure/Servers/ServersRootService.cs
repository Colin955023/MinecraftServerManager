using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>以 <see cref="ServersRootRelocator"/> 實作之伺服器存放根目錄檢查與遷移服務（耗時作業一律於背景執行緒執行）</summary>
public sealed class ServersRootService : IServersRootService
{
    public ServersRootCheck ValidateTargetRoot(string? currentRoot, string? newRoot)
    {
        var result = ServersRootRelocator.ValidateTargetRoot(currentRoot, newRoot, out string normalizedCurrent, out string normalizedNew);
        return new ServersRootCheck(result, normalizedCurrent, normalizedNew);
    }

    public Task<bool> HasStoredContentAsync(string? currentRoot, CancellationToken cancellationToken = default) =>
        Task.Run(() => ServersRootRelocator.HasStoredContent(currentRoot), cancellationToken);

    public Task<bool> IsTargetDirectoryEmptyAsync(string? targetRoot, CancellationToken cancellationToken = default) =>
        Task.Run(() => ServersRootRelocator.IsTargetDirectoryEmpty(targetRoot), cancellationToken);

    public Task RelocateAllContentAsync(
        string currentRoot,
        string newRoot,
        IProgress<(int Percent, string Message)>? progress = null,
        CancellationToken cancellationToken = default) =>
        Task.Run(() => ServersRootRelocator.RelocateAllContent(currentRoot, newRoot, progress, cancellationToken), cancellationToken);
}
