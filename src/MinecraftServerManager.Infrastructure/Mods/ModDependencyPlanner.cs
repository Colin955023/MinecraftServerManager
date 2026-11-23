using System.Collections.Frozen;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Mods;

/// <summary>模組相容性評估與必要相依遞迴解析</summary>
public sealed class ModDependencyPlanner : IModDependencyPlanner
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ModDependencyPlanner));

    /// <summary>常見核心相依庫的 Modrinth Project ID 與別名對映</summary>
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

    private readonly IModrinthClient _modrinthClient;

    public ModDependencyPlanner(IModrinthClient modrinthClient)
    {
        ArgumentNullException.ThrowIfNull(modrinthClient);
        _modrinthClient = modrinthClient;
    }

    public OnlineModCompatibilityReport EvaluateCompatibility(
        OnlineModVersion targetVersion,
        string serverMinecraftVersion,
        LoaderKind serverLoader,
        IReadOnlyList<LocalModInfo> installedMods,
        string? serverSide = null)
    {
        ArgumentNullException.ThrowIfNull(targetVersion);

        var hardErrors = new List<string>();
        var environmentErrors = new List<string>();
        var missingRequired = new List<string>();
        var incompatible = new List<string>();

        string serverLoaderId = LoaderKinds.ToModrinthId(serverLoader);
        string normalizedServerMcVer = MinecraftVersion.TryParse(serverMinecraftVersion, out var parsedServerMc)
            ? parsedServerMc.Value
            : string.Empty;

        // 0. 伺服器端環境相容性檢查 (純用戶端模組不可在伺服器運作)
        if (!string.IsNullOrWhiteSpace(serverSide) && string.Equals(serverSide.Trim(), "unsupported", StringComparison.OrdinalIgnoreCase))
        {
            environmentErrors.Add("此模組僅支援用戶端，不相容伺服器環境 (server_side: unsupported)");
        }

        // 1. Loader 相容性檢查
        if (serverLoader != LoaderKind.Vanilla)
        {
            if (targetVersion.Loaders.Count > 0 && !LoaderCompatibility.IsCompatible(serverLoader, targetVersion.Loaders, normalizedServerMcVer))
            {
                environmentErrors.Add($"此版本不支援目前的伺服器載入器 {serverLoaderId}（僅支援: {string.Join(", ", targetVersion.Loaders)}）");
            }
        }

        // 2. Minecraft 版本相容性檢查
        if (!string.IsNullOrEmpty(normalizedServerMcVer))
        {
            if (targetVersion.GameVersions.Count > 0 && !IsMinecraftVersionCompatible(normalizedServerMcVer, targetVersion.GameVersions))
            {
                environmentErrors.Add($"此版本不支援目前的 Minecraft 版本 {serverMinecraftVersion}");
            }
        }

        // 3. 本地模組識別索引建立 (包含 ID, Name, PlatformId, PlatformSlug 與別名；停用模組不計入)
        var installedIndex = InstalledModIndex.Create(installedMods);

        // 4. 相依性檢查
        if (targetVersion.Dependencies is not null)
        {
            foreach (var dep in targetVersion.Dependencies)
            {
                string depName = dep.ProjectId ?? dep.VersionId ?? dep.FileName ?? "未知相依項";
                string? idToMatch = dep.ProjectId ?? dep.VersionId;
                bool isInstalled = installedIndex.Contains(idToMatch, dep.FileName);

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

                }
            }
        }

        hardErrors.InsertRange(0, environmentErrors);

        if (missingRequired.Count > 0)
        {
            hardErrors.Add($"缺少必要相依模組：{string.Join(", ", missingRequired)}");
        }

        return new OnlineModCompatibilityReport(hardErrors, missingRequired, incompatible, environmentErrors);
    }

    public async Task<IReadOnlyList<ModDependencyPlanItem>> ResolveDependenciesRecursivelyAsync(
        IReadOnlyList<OnlineModDependency> initialDependencies,
        string serverMinecraftVersion,
        LoaderKind serverLoader,
        IReadOnlyList<LocalModInfo> installedMods,
        string? rootProjectId = null,
        int maxDepth = 5,
        int maxItems = 20,
        bool upgradeInstalled = true,
        CancellationToken cancellationToken = default)
    {
        if (initialDependencies is null || initialDependencies.Count == 0 || maxDepth <= 0 || maxItems <= 0)
        {
            return [];
        }

        // 停用的模組不載入，不能滿足相依
        var installedIndex = InstalledModIndex.Create(installedMods);
        var visited = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (!string.IsNullOrWhiteSpace(rootProjectId))
        {
            visited.Add(ModHelpers.NormalizeIdentifier(rootProjectId));
        }

        var resolvedPlans = new List<ModDependencyPlanItem>();
        var queue = new Queue<(OnlineModDependency dep, int depth)>();

        foreach (var dep in initialDependencies)
        {
            if (dep.DependencyType == ModDependencyType.Required)
            {
                queue.Enqueue((dep, 1));
            }
        }

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
            var localMod = installedIndex.TryFind(targetKey, currentDep.FileName);
            if (!upgradeInstalled && localMod is not null)
            {
                // 已安裝即視為滿足，不查詢也不升級（僅補齊缺少的必要相依）
                continue;
            }

            if (KnownModProjectAliases.TryGetValue(targetKey, out string? alias))
            {
                visited.Add(ModHelpers.NormalizeIdentifier(alias));
            }

            try
            {
                IReadOnlyList<OnlineModVersion> versions;
                if (currentDep.ProjectId is null && !string.IsNullOrWhiteSpace(currentDep.VersionId))
                {
                    // 僅指定版本 ID 的相依直接查詢該版本
                    var pinned = await _modrinthClient.GetVersionAsync(currentDep.VersionId, cancellationToken).ConfigureAwait(false);
                    versions = pinned is null ? [] : [pinned];
                }
                else
                {
                    versions = await _modrinthClient.GetProjectVersionsAsync(
                        targetKey,
                        loader: serverLoader,
                        minecraftVersion: serverMinecraftVersion,
                        cancellationToken: cancellationToken).ConfigureAwait(false);
                }

                LoaderKind? fallbackLoader = currentDep.ProjectId is null ? null : LoaderCompatibility.GetFallbackLoader(serverLoader, serverMinecraftVersion);
                if (versions.Count == 0 && fallbackLoader is { } fallback)
                {
                    // Quilt 可載入 Fabric 模組；NeoForge 1.20.1 可載入 Forge 模組
                    versions = await _modrinthClient.GetProjectVersionsAsync(
                        targetKey,
                        loader: fallback,
                        minecraftVersion: serverMinecraftVersion,
                        cancellationToken: cancellationToken).ConfigureAwait(false);
                }

                if (versions.Count == 0)
                {
                    Logger.Warning("相依模組「{Name}」在 MC {MC} / {Loader} 下無相容版本", targetKey, serverMinecraftVersion, LoaderKinds.ToModrinthId(serverLoader));
                    continue;
                }

                var matchedVersion = SelectBestCompatibleVersion(versions, serverMinecraftVersion, serverLoader);
                if (matchedVersion is null)
                {
                    Logger.Warning("相依模組「{Name}」找不到具備有效 JAR 檔案的相容版本", targetKey);
                    continue;
                }

                if (!string.IsNullOrWhiteSpace(matchedVersion.VersionId))
                {
                    visited.Add(ModHelpers.NormalizeIdentifier(matchedVersion.VersionId));
                }

                if (localMod is not null)
                {
                    // 雜湊相同或本機版本不舊於候選版時不降級，但仍展開其子相依
                    if (!ModHelpers.HashMatches(matchedVersion.PrimaryFile, localMod.CurrentHash)
                        && FlexVersion.Compare(matchedVersion.VersionNumber, localMod.Version) > 0)
                    {
                        resolvedPlans.Add(new ModDependencyPlanItem(
                        matchedVersion,
                        ModInstallAction.Update,
                        localMod,
                        $"升級相依模組 ({localMod.Version} ➔ {matchedVersion.VersionNumber})"));
                    }
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
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Warning(ex, "查詢相依模組「{Name}」失敗", targetKey);
            }
        }

        return resolvedPlans;
    }

    private sealed class InstalledModIndex
    {
        private readonly Dictionary<string, LocalModInfo> _index = new(StringComparer.OrdinalIgnoreCase);

        public static InstalledModIndex Create(IReadOnlyList<LocalModInfo>? installedMods)
        {
            var result = new InstalledModIndex();
            if (installedMods is null)
            {
                return result;
            }

            foreach (var mod in installedMods)
            {
                if (mod.Status != ModStatus.Enabled)
                {
                    continue;
                }

                void Register(string? raw)
                {
                    if (string.IsNullOrWhiteSpace(raw))
                    {
                        return;
                    }

                    string norm = ModHelpers.NormalizeIdentifier(raw);
                    if (norm.Length > 0)
                    {
                        result._index.TryAdd(norm, mod);
                    }
                }

                Register(mod.Id);
                if (!string.IsNullOrWhiteSpace(mod.Id) && KnownModProjectAliases.TryGetValue(mod.Id, out string? a1))
                {
                    Register(a1);
                }

                Register(mod.Name);
                Register(mod.PlatformId);
                Register(mod.PlatformSlug);
                if (!string.IsNullOrWhiteSpace(mod.FileName))
                {
                    Register(ModHelpers.ModFilenameStem(mod.FileName));
                }
            }

            return result;
        }

        public bool Contains(string? idToMatch, string? fileName) => TryFind(idToMatch, fileName) is not null;

        public LocalModInfo? TryFind(string? idToMatch, string? fileName)
        {
            if (!string.IsNullOrWhiteSpace(idToMatch))
            {
                string normId = ModHelpers.NormalizeIdentifier(idToMatch);
                if (_index.TryGetValue(normId, out var mod))
                {
                    return mod;
                }

                if (KnownModProjectAliases.TryGetValue(idToMatch, out string? alias))
                {
                    string normAlias = ModHelpers.NormalizeIdentifier(alias);
                    if (_index.TryGetValue(normAlias, out var aliasMod))
                    {
                        return aliasMod;
                    }
                }
            }

            if (!string.IsNullOrWhiteSpace(fileName))
            {
                string normStem = ModHelpers.NormalizeIdentifier(ModHelpers.ModFilenameStem(fileName));
                if (_index.TryGetValue(normStem, out var fileMod))
                {
                    return fileMod;
                }
            }

            return null;
        }
    }

    private static bool IsMinecraftVersionCompatible(string serverMcVer, IReadOnlyList<string> targetMcVersions)
    {
        if (targetMcVersions.Count == 0)
        {
            return true;
        }

        bool serverEndsWithDot0 = serverMcVer.EndsWith(".0", StringComparison.Ordinal);
        string serverTrimmedDot0 = serverEndsWithDot0 ? serverMcVer[..^2] : string.Empty;
        string serverWithDot0 = !serverEndsWithDot0 ? serverMcVer + ".0" : string.Empty;

        for (int i = 0; i < targetMcVersions.Count; i++)
        {
            string v = targetMcVersions[i];
            if (string.Equals(v, serverMcVer, StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }

            if (serverEndsWithDot0 && string.Equals(v, serverTrimmedDot0, StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }

            if (!serverEndsWithDot0 && string.Equals(v, serverWithDot0, StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }

        return false;
    }

    private static OnlineModVersion? SelectBestCompatibleVersion(
        IReadOnlyList<OnlineModVersion> versions,
        string serverMinecraftVersion,
        LoaderKind serverLoader)
    {
        if (versions.Count == 0)
        {
            return null;
        }

        string normMc = ModHelpers.NormalizeIdentifier(serverMinecraftVersion);

        OnlineModVersion? anyCompatible = null;

        for (int i = 0; i < versions.Count; i++)
        {
            var v = versions[i];
            if (v.PrimaryFile is null || string.IsNullOrWhiteSpace(v.PrimaryFile.Url))
            {
                continue;
            }

            if (IsVersionMatchingEnvironment(v, normMc, serverLoader))
            {
                if (string.Equals(v.VersionType, "release", StringComparison.OrdinalIgnoreCase))
                {
                    return v;
                }

                anyCompatible ??= v;
            }
        }

        // 無相容版本時回傳 null，不可安裝環境不符的版本
        return anyCompatible;
    }

    private static bool IsVersionMatchingEnvironment(OnlineModVersion v, string normMc, LoaderKind serverLoader)
    {
        bool loaderOk = serverLoader == LoaderKind.Vanilla ||
                        v.Loaders.Count == 0 ||
                        LoaderCompatibility.IsCompatible(serverLoader, v.Loaders, normMc);

        bool mcOk = string.IsNullOrEmpty(normMc) ||
                    !MinecraftVersion.TryParse(normMc, out var validMc) ||
                    v.GameVersions.Count == 0 ||
                    IsMinecraftVersionCompatible(validMc.Value, v.GameVersions);

        return loaderOk && mcOk;
    }
}
