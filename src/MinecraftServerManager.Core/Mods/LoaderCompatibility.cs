using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.Core.Mods;

/// <summary>伺服器載入器與模組支援載入器之相容性判斷（以 LoaderKind 運作）</summary>
public static class LoaderCompatibility
{
    /// <summary>載入器可向下載入的備援模組來源：Quilt 載入 Fabric 模組，NeoForge 1.20.1 載入 Forge 模組</summary>
    public static LoaderKind? GetFallbackLoader(LoaderKind loader, string minecraftVersion) => loader switch
    {
        LoaderKind.Quilt => LoaderKind.Fabric,
        LoaderKind.NeoForge when MinecraftVersionSemantics.IsNeoForgeForgeCompatible(minecraftVersion) => LoaderKind.Forge,
        _ => null,
    };

    /// <summary>模組支援的載入器清單（Modrinth 識別字）是否可於此伺服器載入；清單為空視為相容</summary>
    public static bool IsCompatible(LoaderKind serverLoader, IReadOnlyList<string> targetLoaders, string minecraftVersion)
    {
        if (targetLoaders.Count == 0)
        {
            return true;
        }

        bool hasFabric = false;
        bool hasForge = false;
        bool hasDatapack = false;
        foreach (string target in targetLoaders)
        {
            if (LoaderKinds.TryParseModrinthId(target, out var targetKind))
            {
                if (targetKind == serverLoader)
                {
                    return true;
                }

                hasFabric |= targetKind == LoaderKind.Fabric;
                hasForge |= targetKind == LoaderKind.Forge;
            }
            else if (string.Equals(target, "datapack", StringComparison.OrdinalIgnoreCase))
            {
                hasDatapack = true;
            }
        }

        // 外掛類型伺服器（Paper）不載入一般 Fabric／Forge 模組
        if (serverLoader == LoaderKind.Paper)
        {
            return false;
        }

        // Quilt 伺服器向下相容 Fabric 模組
        if (serverLoader == LoaderKind.Quilt && hasFabric)
        {
            return true;
        }

        // NeoForge 伺服器僅於 1.20.1 可向下相容 Forge 模組
        if (serverLoader == LoaderKind.NeoForge && hasForge && MinecraftVersionSemantics.IsNeoForgeForgeCompatible(minecraftVersion))
        {
            return true;
        }

        // 資料包模組相容
        return hasDatapack;
    }
}
