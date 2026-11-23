using System.Text.Json;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Http;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Loaders;

public sealed partial class LoaderInstallerService
{
    private async Task<string> DownloadInstallerJarAsync(
        LoaderKind loader,
        string minecraftVersion,
        string loaderVersion,
        Action onStartDownload,
        CancellationToken cancellationToken)
    {
        bool isDynamic = Policies.TryGetValue(loader, out var policy) && policy.MetaUri is not null;
        InstallerDescriptor descriptor;
        if (isDynamic)
        {
            var (resolved, fallbackPath) = await ResolveDynamicInstallerAsync(loader, policy!, cancellationToken).ConfigureAwait(false);
            if (fallbackPath is not null)
            {
                return await ExecuteWithInstallerLockAsync(
                    Path.GetFileName(fallbackPath),
                    () =>
                    {
                        CleanupOldInstallers(loader, fallbackPath);
                        return Task.FromResult(fallbackPath);
                    },
                    cancellationToken).ConfigureAwait(false);
            }

            descriptor = resolved!;
            onStartDownload();
        }
        else
        {
            string mc = ValidateVersionToken(minecraftVersion, nameof(minecraftVersion));
            string lv = ValidateVersionToken(loaderVersion, nameof(loaderVersion));
            string url = loader switch
            {
                LoaderKind.Forge => $"https://maven.minecraftforge.net/net/minecraftforge/forge/{mc}-{lv}/forge-{mc}-{lv}-installer.jar",
                LoaderKind.NeoForge => $"https://maven.neoforged.net/releases/net/neoforged/neoforge/{lv}/neoforge-{lv}-installer.jar",
                _ => throw new NotSupportedException($"不支援的 Loader: {loader}")
            };
            var uri = new Uri(url);
            descriptor = new(uri, Path.GetFileName(uri.AbsolutePath));
        }

        string destination = Path.Combine(_cacheDir, descriptor.FileName);
        if (!SafeFileSystem.IsPathWithin(_cacheDir, destination, strict: false))
        {
            throw new InvalidOperationException($"安裝器快取路徑超出允許範圍：{descriptor.FileName}");
        }

        string hashSidecar = destination + ".sha256";
        return await ExecuteWithInstallerLockAsync(
            descriptor.FileName,
            async () =>
            {
                // 快取安裝器執行前須與下載當下記錄之 SHA-256 相符，否則重新下載
                if (!await IsCachedInstallerIntactAsync(destination, hashSidecar, cancellationToken).ConfigureAwait(false))
                {
                    try
                    {
                        await DownloadAndVerifyAsync(loader, descriptor, destination, hashSidecar, cancellationToken).ConfigureAwait(false);
                    }
                    catch (Exception ex) when (isDynamic && ex is not OperationCanceledException)
                    {
                        _metadataCache.TryRemove(loader, out _);
                        throw;
                    }
                }

                CleanupOldInstallers(loader, destination);
                return destination;
            },
            cancellationToken).ConfigureAwait(false);
    }

    private async Task<string> ExecuteWithInstallerLockAsync(
        string installerName,
        Func<Task<string>> action,
        CancellationToken cancellationToken)
    {
        using var gate = await _downloadGates.AcquireAsync(installerName, cancellationToken).ConfigureAwait(false);
        _activeInstallers.TryAdd(installerName, 0);
        try
        {
            return await action().ConfigureAwait(false);
        }
        finally
        {
            _activeInstallers.TryRemove(installerName, out _);
        }
    }

    /// <summary>Maven 路徑片段只允許版號字元，避免組出非預期網址</summary>
    private static string ValidateVersionToken(string value, string paramName)
    {
        string trimmed = value?.Trim() ?? string.Empty;
        if (trimmed.Length == 0
            || trimmed.AsSpan().IndexOfAnyExcept(VersionTokenChars) >= 0
            || trimmed.Contains("..", StringComparison.Ordinal))
        {
            throw new ArgumentException($"版本格式無效：{value}", paramName);
        }

        return Uri.EscapeDataString(trimmed);
    }

    private async Task DownloadAndVerifyAsync(
        LoaderKind loader,
        InstallerDescriptor descriptor,
        string destination,
        string hashSidecar,
        CancellationToken cancellationToken)
    {
        // 安裝器會以 java 執行：取不到雜湊即拒絕，不做未驗證下載
        string? expectedHash = descriptor.ExpectedHash;
        string expectedAlgorithm = descriptor.HashAlgorithm ?? HashAlgorithmNames.Sha256;
        if (expectedHash is null)
        {
            foreach (var (alg, len) in HashAlgorithms)
            {
                expectedHash = await TryFetchInstallerHashAsync($"{descriptor.Uri.AbsoluteUri}.{alg}", len, cancellationToken).ConfigureAwait(false);
                if (expectedHash is not null)
                {
                    expectedAlgorithm = alg;
                    break;
                }
            }
        }

        if (expectedHash is null)
        {
            throw new InvalidOperationException($"無法取得 {loader} 安裝器的雜湊檔，已拒絕下載與執行");
        }

        await TrustedArtifactDownloader.DownloadVerifiedAsync(
            _httpPort,
            descriptor.Uri,
            destination,
            expectedHash,
            expectedAlgorithm,
            progress: null,
            minProgressPct: 0,
            maxProgressPct: 100,
            artifactDisplayName: $"{loader} 安裝器",
            cancellationToken).ConfigureAwait(false);

        // 下載時已驗證 SHA-256 者直接記錄，免重新雜湊
        string sha256 = string.Equals(expectedAlgorithm, HashAlgorithmNames.Sha256, StringComparison.OrdinalIgnoreCase)
            ? expectedHash.ToLowerInvariant()
            : await HashCalculator.ComputeFileHashAsync(destination, cancellationToken: cancellationToken).ConfigureAwait(false);
        await SafeFileSystem.WriteAllTextAsync(hashSidecar, sha256, cancellationToken: cancellationToken).ConfigureAwait(false);
    }

    private async Task<(InstallerDescriptor? Descriptor, string? FallbackPath)> ResolveDynamicInstallerAsync(
        LoaderKind loader,
        InstallerPolicy policy,
        CancellationToken cancellationToken)
    {
        DateTimeOffset nowUtc = _timeProvider.GetUtcNow();
        if (_metadataCache.TryGetValue(loader, out var cached) && nowUtc < cached.ExpiresAtUtc)
        {
            return (cached.Descriptor, null);
        }

        try
        {
            var response = await _httpPort.GetJsonDocumentAsync(policy.MetaUri!, cancellationToken).ConfigureAwait(false);
            using var doc = response.Payload;
            if (response.IsSuccess && doc is not null && TryParseDynamicDescriptor(doc.RootElement, policy, out var descriptor))
            {
                _metadataCache[loader] = (descriptor, nowUtc.Add(MetadataCacheTtl));
                return (descriptor, null);
            }

            Logger.Warning("無法解析 {Loader} 安裝器中繼資料 (Status: {StatusCode})，改檢查本機快取", loader, response.StatusCode);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "查詢 {Loader} 最新安裝器中繼資料失敗，改檢查本機快取", loader);
        }

        string? fallbackPath = await TryFindLatestIntactCacheAsync(policy, cancellationToken).ConfigureAwait(false);
        if (fallbackPath is not null)
        {
            Logger.Warning("無法連線 {Loader} 中繼資料端點，改用本機已驗證快取：{Path}", loader, fallbackPath);
            return (null, fallbackPath);
        }

        throw new InvalidOperationException($"無法取得 {loader} 最新安裝器中繼資料，且本機無可用的已驗證快取");
    }

    private bool TryParseDynamicDescriptor(JsonElement root, InstallerPolicy policy, out InstallerDescriptor descriptor)
    {
        descriptor = default!;
        if (root.ValueKind != JsonValueKind.Array)
        {
            return false;
        }

        InstallerDescriptor? firstValid = null;
        foreach (JsonElement item in root.EnumerateArray())
        {
            if (!TryValidateInstallerUri(item.GetStringOrNull("url"), policy, out Uri? uri, out string fileName))
            {
                continue;
            }

            string? expectedHash = null;
            string? expectedAlg = null;
            if (policy.ReadMetaHashes && item.TryGetProperty("hashes", JsonValueKind.Object, out JsonElement hashes))
            {
                foreach (var (alg, len) in HashAlgorithms)
                {
                    if (ExtractValidHexHash(hashes.GetStringOrNull(alg), len) is string hex)
                    {
                        expectedHash = hex;
                        expectedAlg = alg;
                        break;
                    }
                }
            }

            var candidate = new InstallerDescriptor(uri!, fileName, expectedHash, expectedAlg);
            firstValid ??= candidate;
            if (!policy.PreferStable || item.GetBooleanOrNull("stable") == true)
            {
                descriptor = candidate;
                return true;
            }
        }

        if (firstValid is null)
        {
            return false;
        }

        descriptor = firstValid;
        return true;
    }

    private bool TryValidateInstallerUri(string? rawUrl, InstallerPolicy policy, out Uri? uri, out string fileName)
    {
        uri = null;
        fileName = string.Empty;
        if (policy.AllowedHosts is null
            || !TrustedHostPolicy.TryCreate(rawUrl, policy.AllowedHosts, out Uri? parsed)
            || !string.IsNullOrEmpty(parsed.Query)
            || !string.IsNullOrEmpty(parsed.Fragment))
        {
            return false;
        }

        string candidateName = Path.GetFileName(parsed.AbsolutePath);
        if (!IsInstallerFileName(candidateName, policy) ||
            !SafeFileSystem.IsPathWithin(_cacheDir, Path.Combine(_cacheDir, candidateName), strict: false))
        {
            return false;
        }

        uri = parsed;
        fileName = candidateName;
        return true;
    }
}
