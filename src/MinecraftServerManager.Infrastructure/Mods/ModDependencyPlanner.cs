using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;

namespace MinecraftServerManager.Infrastructure.Mods;

/// <summary>
/// 模組版本相容性與依賴關係分析規劃實作
/// </summary>
public sealed class ModDependencyPlanner : IModDependencyPlanner
{
    public OnlineModCompatibilityReport EvaluateCompatibility(
        OnlineModVersion targetVersion,
        string serverMinecraftVersion,
        string serverLoader,
        IReadOnlyList<LocalModInfo> installedMods)
    {
        ArgumentNullException.ThrowIfNull(targetVersion);

        var hardErrors = new List<string>();
        var warnings = new List<string>();
        var notes = new List<string>();
        var missingRequired = new List<string>();
        var optional = new List<string>();
        var incompatible = new List<string>();

        string normalizedServerLoader = ModHelpers.NormalizeIdentifier(serverLoader);
        string normalizedServerMcVer = ModHelpers.NormalizeIdentifier(serverMinecraftVersion);

        // 1. Loader 相容性檢查
        if (!string.IsNullOrEmpty(normalizedServerLoader) && normalizedServerLoader != "vanilla")
        {
            var targetLoaders = targetVersion.Loaders.Select(ModHelpers.NormalizeIdentifier).ToHashSet();
            if (targetLoaders.Count > 0 && !targetLoaders.Contains(normalizedServerLoader))
            {
                hardErrors.Add($"此版本不支援目前的伺服器載入器 {serverLoader}（僅支援: {string.Join(", ", targetVersion.Loaders)}）");
            }
        }

        // 2. Minecraft 版本相容性檢查
        if (!string.IsNullOrEmpty(normalizedServerMcVer) && normalizedServerMcVer != "未知")
        {
            var targetMcVersions = targetVersion.GameVersions.Select(ModHelpers.NormalizeIdentifier).ToHashSet();
            if (targetMcVersions.Count > 0 && !targetMcVersions.Contains(normalizedServerMcVer))
            {
                hardErrors.Add($"此版本不支援目前的 Minecraft 版本 {serverMinecraftVersion}");
            }
        }

        // 3. 本地模組識別字集合
        var installedIdentifiers = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var mod in installedMods ?? [])
        {
            if (!string.IsNullOrWhiteSpace(mod.Id))
            {
                installedIdentifiers.Add(ModHelpers.NormalizeIdentifier(mod.Id));
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
        }

        // 4. 相依性檢查
        if (targetVersion.Dependencies is not null)
        {
            foreach (var dep in targetVersion.Dependencies)
            {
                string depName = dep.ProjectId ?? dep.VersionId ?? dep.FileName ?? "未知依賴";
                string? idToMatch = dep.ProjectId ?? dep.VersionId;
                bool isInstalled = (!string.IsNullOrEmpty(idToMatch) && installedIdentifiers.Contains(ModHelpers.NormalizeIdentifier(idToMatch))) ||
                                  (!string.IsNullOrEmpty(dep.FileName) && installedIdentifiers.Contains(ModHelpers.NormalizeIdentifier(ModHelpers.ModFilenameStem(dep.FileName))));

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
                }
            }
        }

        if (missingRequired.Count > 0)
        {
            hardErrors.Add($"缺少必要依賴模組：{string.Join(", ", missingRequired)}");
        }

        return new OnlineModCompatibilityReport(hardErrors, warnings, notes, missingRequired, optional, incompatible);
    }
}
