using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Loaders;

/// <summary>受信任構件下載器：統一網域白名單驗證、強雜湊格式驗證與進度回報</summary>
internal static class TrustedArtifactDownloader
{
    public static async Task DownloadVerifiedAsync(
        IHttpPort httpPort,
        Uri downloadUri,
        string destinationFilePath,
        string expectedHash,
        string hashAlgorithm,
        IProgress<LoaderInstallProgress>? progress,
        int minProgressPct,
        int maxProgressPct,
        string artifactDisplayName,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(httpPort);
        ArgumentNullException.ThrowIfNull(downloadUri);
        ArgumentException.ThrowIfNullOrWhiteSpace(destinationFilePath);
        ArgumentException.ThrowIfNullOrWhiteSpace(expectedHash);

        progress?.Report(new LoaderInstallProgress(LoaderInstallPhase.Downloading, $"正在下載 {artifactDisplayName}...", minProgressPct));

        var downloadResult = await httpPort.DownloadAsync(
            downloadUri,
            destinationFilePath,
            new SynchronousProgress<HttpProgress>(p =>
            {
                int pct = ProgressMapping.Map(p.BytesDownloaded, p.TotalBytes, minProgressPct, maxProgressPct);
                progress?.Report(new LoaderInstallProgress(LoaderInstallPhase.Downloading, $"正在下載 {artifactDisplayName} ({UnitFormatter.FormatBytes(p.BytesDownloaded)})...", pct));
            }),
            expectedHash: expectedHash,
            expectedHashAlgorithm: hashAlgorithm,
            cancellationToken: cancellationToken).ConfigureAwait(false);

        if (!downloadResult.Success)
        {
            throw new InvalidOperationException($"下載 {artifactDisplayName} 失敗：{downloadResult.Error}");
        }
    }
}
