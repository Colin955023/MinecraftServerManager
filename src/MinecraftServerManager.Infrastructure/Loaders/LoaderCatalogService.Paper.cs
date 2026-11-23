using System.Globalization;
using System.Text.Json;
using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Loaders;

public sealed partial class LoaderCatalogService
{
    public async Task<IReadOnlyList<LoaderVersion>> GetPaperMinecraftVersionsAsync(
        bool forceReload = false,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (forceReload)
        {
            _memoryPaperMinecraftVersions = null;
            ClearLoaderMemory(static loader => loader == LoaderKind.Paper);
        }
        else if (TryGetFresh(_memoryPaperMinecraftVersions, out var memoryVersions))
        {
            return memoryVersions;
        }

        string cacheFile = GetPaperCacheFilePath();

        if (!forceReload && IsCacheFresh(cacheFile))
        {
            var validCached = LoadValidatedCache(cacheFile, IsValidPaperEntry);
            if (validCached.Count > 0)
            {
                _memoryPaperMinecraftVersions = CreateMemoryEntry(validCached);
                return validCached;
            }
        }

        try
        {
            string url = MojangVersionCatalog.PaperProjectUrl;
            var response = await _httpPort.GetJsonDocumentAsync(new Uri(url), cancellationToken).ConfigureAwait(false);
            if (response.IsSuccess && response.Payload is not null)
            {
                List<LoaderVersion> baseVersions;
                using (response.Payload)
                {
                    baseVersions = ParsePaperMinecraftVersions(response.Payload);
                }
                if (baseVersions.Count > 0)
                {
                    // Java major 一律依 Mojang 官方版本 JSON（Paper 與原版相同）
                    var official = new Dictionary<string, LoaderVersion>(StringComparer.OrdinalIgnoreCase);
                    foreach (var mc in await GetMinecraftVersionsAsync(includeSnapshots: false, cancellationToken).ConfigureAwait(false))
                    {
                        official[mc.Version] = mc;
                    }

                    // 已有 JavaMajor 與 Build 的版本不重複呼叫 API；強制重新載入時仍重抓最新 STABLE Build
                    var existingMap = new Dictionary<string, (int JavaMajor, string Build)>(StringComparer.OrdinalIgnoreCase);
                    if (SafeFileSystem.FileExists(cacheFile))
                    {
                        foreach (var ev in MojangVersionCatalog.LoadCachedVersions(cacheFile))
                        {
                            if (IsValidPaperEntry(ev))
                            {
                                existingMap[ev.Version] = (ev.JavaMajor!.Value, ev.Build!);
                            }
                        }
                    }

                    var fullVersions = new LoaderVersion?[baseVersions.Count];
                    await Parallel.ForAsync(
                        0,
                        baseVersions.Count,
                        new ParallelOptions { MaxDegreeOfParallelism = 5, CancellationToken = cancellationToken },
                        async (index, token) =>
                        {
                            var v = baseVersions[index];
                            bool known = existingMap.TryGetValue(v.Version, out var existing);
                            if (known && !forceReload)
                            {
                                fullVersions[index] = v with { JavaMajor = existing.JavaMajor, Build = existing.Build };
                                return;
                            }

                            // 查詢 STABLE 建置清單；若無任何 STABLE 建置，直接剔除（不納入快取）
                            var builds = await FetchPaperBuildsAsync(v.Version, token, updateCache: false).ConfigureAwait(false);
                            if (builds.Count == 0 || string.IsNullOrWhiteSpace(builds[0].Version))
                            {
                                return;
                            }

                            int? javaMajor = known ? existing.JavaMajor : await GetOfficialJavaMajorAsync(official, v.Version, token).ConfigureAwait(false);
                            fullVersions[index] = v with { JavaMajor = javaMajor, Build = builds[0].Version };
                        }).ConfigureAwait(false);

                    var result = fullVersions
                        .OfType<LoaderVersion>()
                        .OrderByDescending(static v => VersionValue.ParseOrZero(v.Version))
                        .ToList();

                    // 只寫入完整條目；若有缺 JavaMajor 者則不寫入記憶體快取，避免 12 小時 TTL 內不重查
                    var validEntries = result.Where(IsValidPaperEntry).ToList();
                    MojangVersionCatalog.SaveCachedVersions(cacheFile, validEntries);
                    if (validEntries.Count == result.Count && validEntries.Count > 0)
                    {
                        _memoryPaperMinecraftVersions = CreateMemoryEntry(validEntries);
                    }
                    return result;
                }
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "抓取 Paper 版本清單時發生例外");
        }

        // IHttpPort 失敗時回傳失敗結果而非擲出，故一律在此改用過期快取；降級結果不寫入記憶體快取
        Logger.Warning("抓取 Paper 版本清單失敗，改用過期快取");
        return [.. MojangVersionCatalog.LoadCachedVersions(cacheFile).Where(IsValidPaperEntry)];
    }

    private static bool IsValidPaperEntry(LoaderVersion version) =>
        !string.IsNullOrWhiteSpace(version.Build) && version.JavaMajor is > 0;

    private static List<LoaderVersion> ParsePaperMinecraftVersions(JsonDocument doc)
    {
        if (!doc.RootElement.TryGetProperty("versions", JsonValueKind.Object, out var versionsProp))
        {
            return [];
        }

        var set = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var group in versionsProp.EnumerateObject())
        {
            if (group.Value.ValueKind == JsonValueKind.Array)
            {
                foreach (var item in group.Value.EnumerateArray())
                {
                    string? ver = item.GetStringValue();
                    if (!string.IsNullOrWhiteSpace(ver))
                    {
                        string trimmed = ver.Trim();
                        // 只保留正式發布版號
                        if (MinecraftVersionSemantics.IsOfficialReleaseVersion(trimmed))
                        {
                            set.Add(trimmed);
                        }
                    }
                }
            }
        }

        return [.. set
            .OrderByDescending(static v => VersionValue.ParseOrZero(v))
            .Select(static v => new LoaderVersion(v, Stable: true, MinecraftVersion: v))];
    }

    private async Task<IReadOnlyList<LoaderVersion>> FetchPaperBuildsAsync(
        string minecraftVersion,
        CancellationToken cancellationToken,
        bool updateCache = true)
    {
        Uri buildsUrl = MojangVersionCatalog.PaperBuildsUri(minecraftVersion);
        var response = await _httpPort.GetJsonDocumentAsync(buildsUrl, cancellationToken).ConfigureAwait(false);
        if (!response.IsSuccess || response.Payload is null)
        {
            return [];
        }

        using var doc = response.Payload;
        if (doc.RootElement.ValueKind != JsonValueKind.Array)
        {
            return [];
        }

        var list = new List<LoaderVersion>();
        foreach (var buildElem in doc.RootElement.EnumerateArray())
        {
            if (buildElem.GetInt32OrNull("id") is not int buildId)
            {
                continue;
            }

            bool isStable = string.Equals(buildElem.GetStringOrNull("channel"), "STABLE", StringComparison.OrdinalIgnoreCase);
            string? downloadUrl = MojangVersionCatalog.TryGetPaperDownload(buildElem, out var download)
                ? download.GetStringOrNull("url")
                : null;

            list.Add(new LoaderVersion(
                Version: buildId.ToString(CultureInfo.InvariantCulture),
                Url: downloadUrl,
                Stable: isStable,
                MinecraftVersion: minecraftVersion));
        }

        // PaperMC: 只保留最新正式版（篩選 stable 且排除預發布關鍵字）
        var stableList = list
            .Where(static b => b.Stable && !ContainsPreReleaseKeyword(b.Version))
            .OrderByDescending(static b => int.TryParse(b.Version, NumberStyles.None, CultureInfo.InvariantCulture, out int id) ? id : 0)
            .ToList();

        if (stableList.Count > 0)
        {
            var latestBuild = stableList[0];
            if (updateCache)
            {
                UpdatePaperVersionLatestBuild(minecraftVersion, latestBuild.Version);
            }
            return [latestBuild];
        }

        if (updateCache)
        {
            RemovePaperVersionIfNoStableBuild(minecraftVersion);
        }
        return [];
    }

    private void RemovePaperVersionIfNoStableBuild(string minecraftVersion)
    {
        if (ApplyPaperCacheChange(minecraftVersion, build: null))
        {
            Logger.Information("Paper 版本 {Version} 因無 STABLE 建置已自快取與清單中剔除", minecraftVersion);
        }
    }

    private void UpdatePaperVersionLatestBuild(string minecraftVersion, string build) =>
        ApplyPaperCacheChange(minecraftVersion, build);

    /// <summary>於快取鎖內合併更新 Paper 版本清單並同步記憶體快照；<paramref name="build"/> 為 null 表示移除該版本</summary>
    private bool ApplyPaperCacheChange(string minecraftVersion, string? build)
    {
        try
        {
            bool changed = false;
            MojangVersionCatalog.UpdateCachedVersions(GetPaperCacheFilePath(), current =>
            {
                var updated = ApplyPaperChange(current, minecraftVersion, build);
                changed |= updated is not null;
                return updated;
            });

            while (_memoryPaperMinecraftVersions is { } entry
                && ApplyPaperChange(entry.Versions, minecraftVersion, build) is { } updatedMemory)
            {
                if (Interlocked.CompareExchange(ref _memoryPaperMinecraftVersions, entry with { Versions = [.. updatedMemory] }, entry) == entry)
                {
                    changed = true;
                    break;
                }
            }

            return changed;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "更新 Paper 版本快取失敗: {Version}", minecraftVersion);
            return false;
        }
    }

    /// <summary>回傳套用後的新清單；無變更時回傳 null</summary>
    private static List<LoaderVersion>? ApplyPaperChange(IReadOnlyList<LoaderVersion> versions, string minecraftVersion, string? build)
    {
        var result = new List<LoaderVersion>(versions.Count);
        bool changed = false;
        foreach (var v in versions)
        {
            if (!string.Equals(v.Version, minecraftVersion, StringComparison.OrdinalIgnoreCase))
            {
                result.Add(v);
            }
            else if (build is null)
            {
                changed = true;
            }
            else if (v.Build != build)
            {
                result.Add(v with { Build = build });
                changed = true;
            }
            else
            {
                result.Add(v);
            }
        }

        return changed ? result : null;
    }
}
