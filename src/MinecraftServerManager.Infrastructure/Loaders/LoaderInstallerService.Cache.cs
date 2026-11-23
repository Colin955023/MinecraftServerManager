using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Loaders;

public sealed partial class LoaderInstallerService
{
    private async Task<string?> TryFindLatestIntactCacheAsync(InstallerPolicy policy, CancellationToken cancellationToken)
    {
        IReadOnlyList<FileSystemEntry> entries;
        try
        {
            entries = SafeFileSystem.ListBoundedDirectory(_cacheDir);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "掃描安裝器快取目錄失敗: {Path}", _cacheDir);
            return null;
        }

        var candidates = entries
            .Where(static entry => !entry.IsDirectory)
            .Select(entry => (entry.FullPath, Name: Path.GetFileName(entry.FullPath)))
            .Where(item => IsInstallerFileName(item.Name, policy))
            .Select(item => (item.FullPath, Version: item.Name[policy.Prefix.Length..^policy.Suffix.Length]))
            .OrderByDescending(static item => item.Version, Comparer<string>.Create(FlexVersion.Compare));

        foreach ((string fullPath, _) in candidates)
        {
            if (await IsCachedInstallerIntactAsync(fullPath, fullPath + ".sha256", cancellationToken).ConfigureAwait(false))
            {
                return fullPath;
            }
        }

        return null;
    }

    private void CleanupOldInstallers(LoaderKind loader, string currentJarPath)
    {
        if (!Policies.TryGetValue(loader, out var policy))
        {
            return;
        }

        try
        {
            string currentJarName = Path.GetFileName(currentJarPath);
            var groups = new Dictionary<string, (FileSystemEntry? Jar, List<(string Path, bool IsPart)> Artifacts)>(StringComparer.OrdinalIgnoreCase);

            foreach (FileSystemEntry entry in SafeFileSystem.ListBoundedDirectory(_cacheDir))
            {
                if (entry.IsDirectory)
                {
                    continue;
                }

                string fileName = Path.GetFileName(entry.FullPath);
                bool isPart = false;
                bool isJar = false;
                string jarName = fileName;
                if (fileName.EndsWith(".sha256", StringComparison.OrdinalIgnoreCase))
                {
                    jarName = fileName[..^".sha256".Length];
                }
                else if (fileName.EndsWith(".part", StringComparison.OrdinalIgnoreCase))
                {
                    jarName = fileName[..^".part".Length];
                    isPart = true;
                }
                else
                {
                    isJar = true;
                }

                // 其他安裝流程正在下載或使用中的檔案不清理
                if (!IsInstallerFileName(jarName, policy)
                    || (_activeInstallers.ContainsKey(jarName) && !string.Equals(jarName, currentJarName, StringComparison.OrdinalIgnoreCase)))
                {
                    continue;
                }

                if (!groups.TryGetValue(jarName, out var group))
                {
                    group = (null, []);
                }

                group.Artifacts.Add((entry.FullPath, isPart));
                groups[jarName] = (isJar ? entry : group.Jar, group.Artifacts);
            }

            var kept = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { currentJarName };
            int keepOther = Math.Max(0, policy.KeepCount - 1);
            if (keepOther > 0)
            {
                foreach (var (jarName, _) in groups
                    .Where(kv => !string.Equals(kv.Key, currentJarName, StringComparison.OrdinalIgnoreCase) && kv.Value.Jar is not null)
                    .OrderByDescending(static kv => kv.Value.Jar!.LastWriteTimeUtc)
                    .ThenByDescending(static kv => kv.Value.Jar!.CreationTimeUtc)
                    .ThenBy(static kv => kv.Key, StringComparer.OrdinalIgnoreCase)
                    .Take(keepOther))
                {
                    kept.Add(jarName);
                }
            }

            foreach (var (jarName, (_, artifacts)) in groups)
            {
                bool keepGroup = kept.Contains(jarName);
                foreach (var (path, isPart) in artifacts)
                {
                    if ((!keepGroup || isPart) && !SafeFileSystem.TryDeleteFile(path))
                    {
                        Logger.Warning("無法刪除舊版安裝器快取檔案: {Path}", path);
                    }
                }
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "清理 {Loader} 舊版安裝器快取時發生錯誤", loader);
        }
    }

    private static bool IsInstallerFileName(string name, InstallerPolicy policy) =>
        ModHelpers.IsJarFileName(name) &&
        name.StartsWith(policy.Prefix, StringComparison.OrdinalIgnoreCase) &&
        name.EndsWith(policy.Suffix, StringComparison.OrdinalIgnoreCase) &&
        name.Length > policy.Prefix.Length + policy.Suffix.Length;

    /// <summary>取得遠端雜湊檔內容；無檔、格式不符或連線失敗回傳 null</summary>
    private async Task<string?> TryFetchInstallerHashAsync(string hashUrl, int hexLength, CancellationToken cancellationToken)
    {
        try
        {
            return ExtractValidHexHash(await _httpPort.GetTextAsync(new Uri(hashUrl), cancellationToken).ConfigureAwait(false), hexLength);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "取得安裝器雜湊檔失敗: {Url}", hashUrl);
            return null;
        }
    }

    private static async Task<bool> IsCachedInstallerIntactAsync(string jarPath, string hashSidecar, CancellationToken cancellationToken)
    {
        if (!SafeFileSystem.FileExists(jarPath) || !SafeFileSystem.FileExists(hashSidecar))
        {
            return false;
        }

        string recorded;
        try
        {
            recorded = (await SafeFileSystem.ReadAllTextAsync(hashSidecar, cancellationToken: cancellationToken).ConfigureAwait(false)).Trim();
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Warning(ex, "讀取安裝器雜湊記錄失敗，將重新下載: {Path}", hashSidecar);
            return false;
        }

        // 記錄格式不符時不必計算整個檔案雜湊
        if (!HashCalculator.IsHexDigest(recorded, 64))
        {
            Logger.Warning("安裝器雜湊記錄格式無效，將重新下載: {Path}", hashSidecar);
            return false;
        }

        string actual = await HashCalculator.ComputeFileHashAsync(jarPath, cancellationToken: cancellationToken).ConfigureAwait(false);
        if (actual.Length > 0 && string.Equals(recorded, actual, StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        Logger.Warning("快取安裝器雜湊不符，將重新下載: {Path}", jarPath);
        return false;
    }

    private static string? ExtractValidHexHash(string? text, int expectedLength)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return null;
        }

        ReadOnlySpan<char> span = text.AsSpan().Trim();
        int separatorIdx = span.IndexOfAny(HashSeparators);
        ReadOnlySpan<char> firstToken = separatorIdx >= 0 ? span[..separatorIdx] : span;

        if (!HashCalculator.IsHexDigest(firstToken, expectedLength))
        {
            return null;
        }

        return firstToken.ToString();
    }
}
