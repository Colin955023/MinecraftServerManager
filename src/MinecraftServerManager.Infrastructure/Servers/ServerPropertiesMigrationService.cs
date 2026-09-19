using System.Collections.Frozen;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>
/// 舊版 server.properties 自動遷移服務
/// </summary>
public static class ServerPropertiesMigrationService
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("ServerPropertiesMigration");

    private static readonly FrozenDictionary<string, string> GamemodeMap = new Dictionary<string, string>
    {
        ["0"] = "survival",
        ["1"] = "creative",
        ["2"] = "adventure",
        ["3"] = "spectator"
    }.ToFrozenDictionary(StringComparer.OrdinalIgnoreCase);

    private static readonly FrozenDictionary<string, string> DifficultyMap = new Dictionary<string, string>
    {
        ["0"] = "peaceful",
        ["1"] = "easy",
        ["2"] = "normal",
        ["3"] = "hard"
    }.ToFrozenDictionary(StringComparer.OrdinalIgnoreCase);

    private static readonly FrozenDictionary<string, string> LevelTypeNormalizedMap = new Dictionary<string, string>
    {
        ["default"] = "minecraft:normal",
        ["flat"] = "minecraft:flat",
        ["largebiomes"] = "minecraft:large_biomes",
        ["amplified"] = "minecraft:amplified"
    }.ToFrozenDictionary(StringComparer.OrdinalIgnoreCase);

    private static readonly FrozenDictionary<string, string> DeprecatedKeys = new Dictionary<string, string>
    {
        ["max-build-height"] = "自 1.17 起移除，世界高度由資料包與世界生成控制",
        ["snooper-enabled"] = "自 1.18 起移除，遙測設定已廢棄",
        ["announce-player-achievements"] = "自 1.12 起移除，已改為遊戲規則 announceAdvancements"
    }.ToFrozenDictionary(StringComparer.OrdinalIgnoreCase);

    /// <summary>
    /// 分析現有屬性字典並產生遷移計畫
    /// </summary>
    public static ServerPropertiesMigrationPlan PlanMigration(
        IReadOnlyDictionary<string, string> properties,
        string? minecraftVersion = null)
    {
        ArgumentNullException.ThrowIfNull(properties);

        var newProps = new Dictionary<string, string>(properties, StringComparer.OrdinalIgnoreCase);
        var changes = new List<string>();

        if (newProps.Remove("texture-pack", out string? texturePackValue))
        {
            if (!newProps.ContainsKey("resource-pack"))
            {
                newProps["resource-pack"] = texturePackValue;
                changes.Add("屬性更名：texture-pack ➔ resource-pack (1.7.2+)");
            }
            else
            {
                changes.Add("移除舊版重複屬性：texture-pack (已存在 resource-pack)");
            }
        }

        if (newProps.Remove("hellworld", out string? hellworldValue))
        {
            if (!newProps.ContainsKey("allow-nether"))
            {
                newProps["allow-nether"] = hellworldValue;
                changes.Add("屬性更名：hellworld ➔ allow-nether");
            }
        }

        if (newProps.TryGetValue("gamemode", out string? rawGm) && GamemodeMap.TryGetValue(rawGm.Trim(), out string? mappedGm))
        {
            newProps["gamemode"] = mappedGm;
            changes.Add($"遊戲模式轉換：gamemode={rawGm} ➔ {mappedGm} (1.14+)");
        }

        if (newProps.TryGetValue("difficulty", out string? rawDiff) && DifficultyMap.TryGetValue(rawDiff.Trim(), out string? mappedDiff))
        {
            newProps["difficulty"] = mappedDiff;
            changes.Add($"遊戲難度轉換：difficulty={rawDiff} ➔ {mappedDiff} (1.14+)");
        }

        if (IsVersionAtLeast119(minecraftVersion) && newProps.TryGetValue("level-type", out string? rawLt))
        {
            string lookupKey = rawLt.Trim().ToLowerInvariant().Replace("_", string.Empty);
            if (LevelTypeNormalizedMap.TryGetValue(lookupKey, out string? mappedLt) && !string.Equals(rawLt, mappedLt, StringComparison.Ordinal))
            {
                newProps["level-type"] = mappedLt;
                changes.Add($"地圖類型命名空間轉換：level-type={rawLt} ➔ {mappedLt} (1.19+)");
            }
        }

        foreach (var (depKey, reason) in DeprecatedKeys)
        {
            if (newProps.Remove(depKey))
            {
                changes.Add($"移除廢棄屬性：{depKey} ({reason})");
            }
        }

        return new ServerPropertiesMigrationPlan(
            NeedsMigration: changes.Count > 0,
            Changes: changes,
            MigratedProperties: newProps);
    }

    /// <summary>
    /// 將遷移計畫套用並寫入指定伺服器目錄下的 server.properties
    /// </summary>
    public static bool ApplyMigrationToDirectory(
        string directoryPath,
        ServerPropertiesMigrationPlan plan,
        bool createBackup = true)
    {
        ArgumentNullException.ThrowIfNull(plan);
        if (string.IsNullOrWhiteSpace(directoryPath))
        {
            return false;
        }

        string stableDir = SafeFileSystem.ResolveStableDirectory(directoryPath);
        string propsPath = Path.Combine(stableDir, "server.properties");
        if (!File.Exists(propsPath))
        {
            return false;
        }

        if (createBackup)
        {
            string backupPath = Path.Combine(stableDir, "server.properties.backup");
            try
            {
                File.Copy(propsPath, backupPath, overwrite: true);
                Logger.Information("已建立 server.properties 備份：{BackupPath}", backupPath);
            }
            catch (Exception ex)
            {
                Logger.Warning("建立 server.properties.backup 失敗：{Message}", ex.Message);
            }
        }

        string serialized = PropertiesDocumentCodec.Serialize(plan.MigratedProperties);
        bool success = AtomicFileWriter.WriteText(propsPath, serialized);
        if (success)
        {
            Logger.Information("已成功套用 server.properties 遷移：共 {Count} 項更動", plan.Changes.Count);
        }

        return success;
    }

    private static bool IsVersionAtLeast119(string? version)
    {
        if (string.IsNullOrWhiteSpace(version))
        {
            return false;
        }

        string[] parts = version.Trim().Split('.');
        if (parts.Length >= 2 && int.TryParse(parts[0], out int major) && int.TryParse(parts[1], out int minor))
        {
            return major > 1 || (major == 1 && minor >= 19);
        }

        return false;
    }
}
