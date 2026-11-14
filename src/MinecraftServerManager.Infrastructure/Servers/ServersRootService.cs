using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>伺服器根目錄檢查與遷移服務</summary>
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

    public Task<IReadOnlyList<string>> RelocateAllContentAsync(
        string currentRoot,
        string newRoot,
        IProgress<(int Percent, string Message)>? progress = null,
        CancellationToken cancellationToken = default) =>
        Task.Run(() => ServersRootRelocator.RelocateAllContent(currentRoot, newRoot, progress, cancellationToken), cancellationToken);
}
