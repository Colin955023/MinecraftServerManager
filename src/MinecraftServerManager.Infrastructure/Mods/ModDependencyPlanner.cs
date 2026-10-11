using System.Collections.Frozen;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Mods;

/// <summary>
/// 模組版本相容性與相依性關係分析規劃實作（比照 Prism Launcher 標準）
/// </summary>
public sealed class ModDependencyPlanner : IModDependencyPlanner
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("ModDependencyPlanner");

    /// <summary>
    /// 常見核心相依庫之 Modrinth Project ID 與本地 Mod ID / Slug 別名對映表
    /// </summary>
    private static readonly FrozenDictionary<string, string> KnownModProjectAliases = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
    {
        ["P7dR8mAc"] = "fabric-api",
        ["qvIfYCYJ"] = "qsl",
        ["9s6osm5g"] = "cloth-config",
        ["lhGA9TYQ"] = "architectury-api",
        ["FvdACJGu"] = "forge-config-api-port",
        ["gu7yAYhd"] = "kotlin-for-forge",
        ["Ha28R6CL"] = "fabric-language-kotlin",
        ["mOgUt4GM"] = "modmenu",
        ["AANobbMI"] = "sodium",
        ["YL57xq9U"] = "iris",
        ["gvQqBUqZ"] = "lithium",
        ["Orvt0mRa"] = "indium",
        ["8BmcYKbN"] = "geckolib"
    }.ToFrozenDictionary(StringComparer.OrdinalIgnoreCase);

    /// <summary>
    /// 外掛類型伺服器載入器集合（不支援常規 Forge/Fabric Mod）
    /// </summary>
    private static readonly FrozenSet<string> PluginServerLoaders = new[]
    {
        "paper", "spigot", "purpur", "bukkit", "velocity", "bungeecord", "waterfall"
    }.ToFrozenSet(StringComparer.OrdinalIgnoreCase);

    public OnlineModCompatibilityReport EvaluateCompatibility(
        OnlineModVersion targetVersion,
        string serverMinecraftVersion,
        string serverLoader,
        IReadOnlyList<LocalModInfo> installedMods,
        string? serverSide = null)
    {
        ArgumentNullException.ThrowIfNull(targetVersion);

        var hardErrors = new List<string>();
        var warnings = new List<string>();
        var notes = new List<string>();
        var missingRequired = new List<string>();
        var optional = new List<string>();
        var incompatible = new List<string>();
        var embedded = new List<string>();

        string normalizedServerLoader = ModHelpers.NormalizeIdentifier(serverLoader);
        string normalizedServerMcVer = ModHelpers.NormalizeIdentifier(serverMinecraftVersion);

        // 0. 伺服器端環境相容性檢查 (比照 Prism Launcher：純用戶端模組不可在伺服器運作)
        if (!string.IsNullOrWhiteSpace(serverSide) && string.Equals(serverSide.Trim(), "unsupported", StringComparison.OrdinalIgnoreCase))
        {
            hardErrors.Add("此模組僅支援用戶端，不相容伺服器環境 (server_side: unsupported)");
        }

        // 1. Loader 相容性檢查
        if (!string.IsNullOrEmpty(normalizedServerLoader) && normalizedServerLoader != "vanilla")
        {
            var targetLoaders = targetVersion.Loaders.Select(ModHelpers.NormalizeIdentifier).ToHashSet();
            if (!IsLoaderCompatible(normalizedServerLoader, targetLoaders, normalizedServerMcVer))
            {
                hardErrors.Add($"此版本不支援目前的伺服器載入器 {serverLoader}（僅支援: {string.Join(", ", targetVersion.Loaders)}）");
            }
        }

        // 2. Minecraft 版本相容性檢查
        if (!string.IsNullOrEmpty(normalizedServerMcVer) && normalizedServerMcVer != "未知")
        {
            var targetMcVersions = targetVersion.GameVersions.Select(ModHelpers.NormalizeIdentifier).ToHashSet();
            if (targetMcVersions.Count > 0 && !IsMinecraftVersionCompatible(normalizedServerMcVer, targetMcVersions))
            {
                hardErrors.Add($"此版本不支援目前的 Minecraft 版本 {serverMinecraftVersion}");
            }
        }

        // 3. 本地模組識別字集合建立 (包含 ID, Name, PlatformId, PlatformSlug 與別名)
        var installedIdentifiers = BuildInstalledIdentifiers(installedMods);

        // 4. 相依性檢查
        if (targetVersion.Dependencies is not null)
        {
            foreach (var dep in targetVersion.Dependencies)
            {
                string depName = dep.ProjectId ?? dep.VersionId ?? dep.FileName ?? "未知相依項";
                string? idToMatch = dep.ProjectId ?? dep.VersionId;
                bool isInstalled = IsModMatched(idToMatch, dep.FileName, installedIdentifiers);

                switch (dep.DependencyType)
                {
                    case ModDependencyType.Required:
                        if (!isInstalled)
                        {
                            missingRequired.Add(depName);
                        }
                        break;

                    case ModDependencyType.Incompatible:
                        if (isInstalled)
                        {
                            incompatible.Add(depName);
                            hardErrors.Add($"與目前已安裝之模組衝突：{depName}");
                        }
                        break;

                    case ModDependencyType.Optional:
                        if (!isInstalled)
                        {
                            optional.Add(depName);
                        }
                        break;

                    case ModDependencyType.Embedded:
                        // 內嵌相依模組已封裝於模組檔案內，不需另行安裝，僅供顯示參考
                        embedded.Add(depName);
                        break;
                }
            }
        }

        if (missingRequired.Count > 0)
        {
            hardErrors.Add($"缺少必要相依模組：{string.Join(", ", missingRequired)}");
        }

        return new OnlineModCompatibilityReport(
            hardErrors,
            warnings,
            notes,
            missingRequired,
            optional,
            incompatible,
            embeddedDependencies: embedded);
    }

    public async Task<IReadOnlyList<ModDependencyPlanItem>> ResolveDependenciesRecursivelyAsync(
        IModrinthClient modrinthClient,
        IReadOnlyList<OnlineModDependency> initialDependencies,
        string serverMinecraftVersion,
        string serverLoader,
        IReadOnlyList<LocalModInfo> installedMods,
        int maxDepth = 5,
        int maxItems = 20,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(modrinthClient);
        if (initialDependencies is null || initialDependencies.Count == 0 || maxDepth <= 0 || maxItems <= 0)
        {
            return [];
        }

        var visited = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var resolvedPlans = new List<ModDependencyPlanItem>();
        var queue = new Queue<(OnlineModDependency dep, int depth)>();

        foreach (var dep in initialDependencies)
        {
            if (dep.DependencyType == ModDependencyType.Required)
            {
                queue.Enqueue((dep, 1));
            }
        }

        string normalizedLoader = serverLoader?.ToLowerInvariant() ?? string.Empty;

        while (queue.Count > 0 && resolvedPlans.Count < maxItems)
        {
            cancellationToken.ThrowIfCancellationRequested();

            var (currentDep, currentDepth) = queue.Dequeue();
            if (currentDepth > maxDepth)
            {
                continue;
            }

            string? targetKey = currentDep.ProjectId ?? currentDep.VersionId;
            if (string.IsNullOrWhiteSpace(targetKey))
            {
                continue;
            }

            string normalizedKey = ModHelpers.NormalizeIdentifier(targetKey);
            if (visited.Contains(normalizedKey))
            {
                continue;
            }

            visited.Add(normalizedKey);
            if (KnownModProjectAliases.TryGetValue(targetKey, out string? alias))
            {
                visited.Add(ModHelpers.NormalizeIdentifier(alias));
            }

            try
            {
                var versions = await modrinthClient.GetProjectVersionsAsync(
                    targetKey,
                    loader: normalizedLoader,
                    minecraftVersion: serverMinecraftVersion,
                    cancellationToken: cancellationToken).ConfigureAwait(false);

                if (versions.Count == 0 && string.Equals(normalizedLoader, "quilt", StringComparison.OrdinalIgnoreCase))
                {
                    versions = await modrinthClient.GetProjectVersionsAsync(
                        targetKey,
                        loader: "fabric",
                        minecraftVersion: serverMinecraftVersion,
                        cancellationToken: cancellationToken).ConfigureAwait(false);
                }

                if (versions.Count == 0)
                {
                    Logger.Warning("相依項目「{TargetKey}」在 MC {MC} / {Loader} 下無相容版本", targetKey, serverMinecraftVersion, normalizedLoader);
                    continue;
                }

                var matchedVersion = SelectBestCompatibleVersion(versions, serverMinecraftVersion, normalizedLoader);
                if (matchedVersion is null)
                {
                    Logger.Warning("相依項目「{TargetKey}」找不到具備有效 JAR 檔案的相容版本", targetKey);
                    continue;
                }

                if (!string.IsNullOrWhiteSpace(matchedVersion.VersionId))
                {
                    visited.Add(ModHelpers.NormalizeIdentifier(matchedVersion.VersionId));
                }

                var localMod = FindMatchingInstalledMod(targetKey, currentDep.FileName, installedMods);
                if (localMod is not null)
                {
                    bool isSameVersion = !string.IsNullOrWhiteSpace(localMod.Version) &&
                        string.Equals(localMod.Version.Trim(), matchedVersion.VersionNumber.Trim(), StringComparison.OrdinalIgnoreCase);

                    if (isSameVersion)
                    {
                        continue;
                    }

                    resolvedPlans.Add(new ModDependencyPlanItem(
                        matchedVersion,
                        ModInstallAction.Update,
                        localMod,
                        $"升級相依模組 ({localMod.Version} ➔ {matchedVersion.VersionNumber})"));
                }
                else
                {
                    resolvedPlans.Add(new ModDependencyPlanItem(
                        matchedVersion,
                        ModInstallAction.Install,
                        null,
                        "全新安裝相依模組"));
                }

                if (currentDepth < maxDepth && matchedVersion.Dependencies is not null)
                {
                    foreach (var childDep in matchedVersion.Dependencies)
                    {
                        if (childDep.DependencyType == ModDependencyType.Required)
                        {
                            string? childKey = childDep.ProjectId ?? childDep.VersionId;
                            if (!string.IsNullOrWhiteSpace(childKey))
                            {
                                string normChild = ModHelpers.NormalizeIdentifier(childKey);
                                if (!visited.Contains(normChild))
                                {
                                    queue.Enqueue((childDep, currentDepth + 1));
                                }
                            }
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Logger.Warning("查詢相依專案「{TargetKey}」失敗: {Message}", targetKey, ex.Message);
            }
        }

        return resolvedPlans;
    }

    private static HashSet<string> BuildInstalledIdentifiers(IReadOnlyList<LocalModInfo>? installedMods)
    {
        var installedIdentifiers = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var mod in installedMods ?? [])
        {
            if (!string.IsNullOrWhiteSpace(mod.Id))
            {
                string norm = ModHelpers.NormalizeIdentifier(mod.Id);
                installedIdentifiers.Add(norm);
                if (KnownModProjectAliases.TryGetValue(mod.Id, out string? a1))
                {
                    installedIdentifiers.Add(ModHelpers.NormalizeIdentifier(a1));
                }
            }

            if (!string.IsNullOrWhiteSpace(mod.Name))
            {
                installedIdentifiers.Add(ModHelpers.NormalizeIdentifier(mod.Name));
            }

            if (!string.IsNullOrWhiteSpace(mod.PlatformId))
            {
                installedIdentifiers.Add(ModHelpers.NormalizeIdentifier(mod.PlatformId));
            }

            if (!string.IsNullOrWhiteSpace(mod.PlatformSlug))
            {
                installedIdentifiers.Add(ModHelpers.NormalizeIdentifier(mod.PlatformSlug));
            }

            if (!string.IsNullOrWhiteSpace(mod.Filename))
            {
                installedIdentifiers.Add(ModHelpers.NormalizeIdentifier(ModHelpers.ModFilenameStem(mod.Filename)));
            }
        }

        return installedIdentifiers;
    }

    private static bool IsModMatched(string? idToMatch, string? fileName, HashSet<string> installedIdentifiers)
    {
        if (!string.IsNullOrEmpty(idToMatch))
        {
            string normId = ModHelpers.NormalizeIdentifier(idToMatch);
            if (installedIdentifiers.Contains(normId))
            {
                return true;
            }

            if (KnownModProjectAliases.TryGetValue(idToMatch, out string? alias) &&
                installedIdentifiers.Contains(ModHelpers.NormalizeIdentifier(alias)))
            {
                return true;
            }
        }

        if (!string.IsNullOrEmpty(fileName))
        {
            string stem = ModHelpers.NormalizeIdentifier(ModHelpers.ModFilenameStem(fileName));
            if (installedIdentifiers.Contains(stem))
            {
                return true;
            }
        }

        return false;
    }

    private static LocalModInfo? FindMatchingInstalledMod(string? idToMatch, string? fileName, IReadOnlyList<LocalModInfo> installedMods)
    {
        if (installedMods is null || installedMods.Count == 0)
        {
            return null;
        }

        string? normId = !string.IsNullOrEmpty(idToMatch) ? ModHelpers.NormalizeIdentifier(idToMatch) : null;
        string? aliasNorm = null;
        if (!string.IsNullOrEmpty(idToMatch) && KnownModProjectAliases.TryGetValue(idToMatch, out string? alias))
        {
            aliasNorm = ModHelpers.NormalizeIdentifier(alias);
        }

        string? fileStem = !string.IsNullOrEmpty(fileName) ? ModHelpers.NormalizeIdentifier(ModHelpers.ModFilenameStem(fileName)) : null;

        foreach (var mod in installedMods)
        {
            if (normId is not null)
            {
                if ((!string.IsNullOrWhiteSpace(mod.Id) && string.Equals(ModHelpers.NormalizeIdentifier(mod.Id), normId, StringComparison.OrdinalIgnoreCase)) ||
                    (!string.IsNullOrWhiteSpace(mod.Name) && string.Equals(ModHelpers.NormalizeIdentifier(mod.Name), normId, StringComparison.OrdinalIgnoreCase)) ||
                    (!string.IsNullOrWhiteSpace(mod.PlatformId) && string.Equals(ModHelpers.NormalizeIdentifier(mod.PlatformId), normId, StringComparison.OrdinalIgnoreCase)) ||
                    (!string.IsNullOrWhiteSpace(mod.PlatformSlug) && string.Equals(ModHelpers.NormalizeIdentifier(mod.PlatformSlug), normId, StringComparison.OrdinalIgnoreCase)))
                {
                    return mod;
                }

                if (aliasNorm is not null &&
                    ((!string.IsNullOrWhiteSpace(mod.Id) && string.Equals(ModHelpers.NormalizeIdentifier(mod.Id), aliasNorm, StringComparison.OrdinalIgnoreCase)) ||
                     (!string.IsNullOrWhiteSpace(mod.Name) && string.Equals(ModHelpers.NormalizeIdentifier(mod.Name), aliasNorm, StringComparison.OrdinalIgnoreCase))))
                {
                    return mod;
                }
            }

            if (fileStem is not null && !string.IsNullOrWhiteSpace(mod.Filename))
            {
                string installedStem = ModHelpers.NormalizeIdentifier(ModHelpers.ModFilenameStem(mod.Filename));
                if (string.Equals(installedStem, fileStem, StringComparison.OrdinalIgnoreCase))
                {
                    return mod;
                }
            }
        }

        return null;
    }

    private static bool IsLoaderCompatible(string serverLoader, HashSet<string> targetLoaders, string minecraftVersion)
    {
        if (targetLoaders.Count == 0 || targetLoaders.Contains(serverLoader))
        {
            return true;
        }

        if (PluginServerLoaders.Contains(serverLoader))
        {
            return false;
        }

        // Quilt 伺服器向下相容 Fabric 模組
        if (string.Equals(serverLoader, "quilt", StringComparison.OrdinalIgnoreCase) && targetLoaders.Contains("fabric"))
        {
            return true;
        }

        // NeoForge 伺服器在 1.20.1 早期可向下相容 Forge 模組
        if (string.Equals(serverLoader, "neoforge", StringComparison.OrdinalIgnoreCase) &&
            targetLoaders.Contains("forge") &&
            minecraftVersion.StartsWith("1.20.1", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        // 資料包模組相容
        if (targetLoaders.Contains("datapack"))
        {
            return true;
        }

        return false;
    }

    private static bool IsMinecraftVersionCompatible(string serverMcVer, HashSet<string> targetMcVersions)
    {
        if (targetMcVersions.Count == 0 || targetMcVersions.Contains(serverMcVer))
        {
            return true;
        }

        // 比照 Prism Launcher：相容 1.20 與 1.20.0 語意
        if (serverMcVer.EndsWith(".0", StringComparison.Ordinal) &&
            targetMcVersions.Contains(serverMcVer[..^2]))
        {
            return true;
        }

        if (!serverMcVer.EndsWith(".0", StringComparison.Ordinal) &&
            targetMcVersions.Contains(serverMcVer + ".0"))
        {
            return true;
        }

        return false;
    }

    private static OnlineModVersion? SelectBestCompatibleVersion(
        IReadOnlyList<OnlineModVersion> versions,
        string serverMinecraftVersion,
        string serverLoader)
    {
        if (versions.Count == 0)
        {
            return null;
        }

        string normLoader = ModHelpers.NormalizeIdentifier(serverLoader);
        string normMc = ModHelpers.NormalizeIdentifier(serverMinecraftVersion);

        // 1. 優先選取環境相容且為 Release 之版本
        var releaseCandidate = versions.FirstOrDefault(v =>
            string.Equals(v.VersionType, "release", StringComparison.OrdinalIgnoreCase) &&
            v.PrimaryFile is not null &&
            !string.IsNullOrWhiteSpace(v.PrimaryFile.Url) &&
            IsVersionMatchingEnvironment(v, normMc, normLoader));

        if (releaseCandidate is not null)
        {
            return releaseCandidate;
        }

        // 2. 次選任意環境相容且具備有效 PrimaryFile 的版本
        var anyCompatibleCandidate = versions.FirstOrDefault(v =>
            v.PrimaryFile is not null &&
            !string.IsNullOrWhiteSpace(v.PrimaryFile.Url) &&
            IsVersionMatchingEnvironment(v, normMc, normLoader));

        if (anyCompatibleCandidate is not null)
        {
            return anyCompatibleCandidate;
        }

        // 3. 備援選取具備有效 PrimaryFile 的最新版本
        return versions.FirstOrDefault(v => v.PrimaryFile is not null && !string.IsNullOrWhiteSpace(v.PrimaryFile.Url));
    }

    private static bool IsVersionMatchingEnvironment(OnlineModVersion v, string normMc, string normLoader)
    {
        bool loaderOk = string.IsNullOrEmpty(normLoader) ||
                        normLoader == "vanilla" ||
                        v.Loaders.Count == 0 ||
                        IsLoaderCompatible(normLoader, [.. v.Loaders.Select(ModHelpers.NormalizeIdentifier)], normMc);

        bool mcOk = string.IsNullOrEmpty(normMc) ||
                    normMc == "未知" ||
                    v.GameVersions.Count == 0 ||
                    IsMinecraftVersionCompatible(normMc, [.. v.GameVersions.Select(ModHelpers.NormalizeIdentifier)]);

        return loaderOk && mcOk;
    }
}
