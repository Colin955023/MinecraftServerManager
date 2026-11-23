using System.Collections.Frozen;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>舊版 server.properties 自動遷移服務</summary>
public static class ServerPropertiesMigrationService
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerPropertiesMigrationService));

    // 舊版以數字 0–3 表示，索引即數值
    private static readonly string[] GamemodeNames = ["survival", "creative", "adventure", "spectator"];

    private static readonly string[] DifficultyNames = ["peaceful", "easy", "normal", "hard"];

    private static readonly FrozenDictionary<string, string> LevelTypeNormalizedMap = new Dictionary<string, string>
    {
        ["default"] = "minecraft:normal",
        ["flat"] = "minecraft:flat",
        ["largebiomes"] = "minecraft:large_biomes",
        ["large_biomes"] = "minecraft:large_biomes",
        ["amplified"] = "minecraft:amplified"
    }.ToFrozenDictionary(StringComparer.OrdinalIgnoreCase);

    private static readonly FrozenDictionary<string, string>.AlternateLookup<ReadOnlySpan<char>> LevelTypeSpanLookup =
        LevelTypeNormalizedMap.GetAlternateLookup<ReadOnlySpan<char>>();

    private static readonly FrozenDictionary<string, (VersionValue MinRemovedVersion, string Reason)> DeprecatedKeys =
        new Dictionary<string, (VersionValue MinRemovedVersion, string Reason)>
        {
            ["max-build-height"] = (new VersionValue(1, 17, 0), "自 1.17 起移除，世界高度由資料包與世界生成控制"),
            ["snooper-enabled"] = (new VersionValue(1, 18, 0), "自 1.18 起移除，遙測設定已廢棄"),
            ["max-achievements"] = (new VersionValue(1, 12, 0), "自 1.12 起移除，已改為進度系統"),
            ["announce-player-achievements"] = (new VersionValue(1, 12, 0), "自 1.12 起移除，已改為遊戲規則 announceAdvancements"),
        }.ToFrozenDictionary(StringComparer.OrdinalIgnoreCase);

    /// <summary>分析現有屬性字典並產生遷移計畫</summary>
    public static ServerPropertiesMigrationPlan PlanMigration(
        IReadOnlyDictionary<string, string> properties,
        string? minecraftVersion = null)
    {
        ArgumentNullException.ThrowIfNull(properties);

        var newProps = new Dictionary<string, string>(properties, StringComparer.OrdinalIgnoreCase);
        var changes = new List<string>();
        VersionValue? parsedVersion = !string.IsNullOrWhiteSpace(minecraftVersion) && VersionValue.TryParse(minecraftVersion, out var parsed)
            ? parsed
            : null;

        RenameKeyIfPresent(newProps, "texture-pack", "resource-pack", changes, "1.7.2+");
        RenameKeyIfPresent(newProps, "hellworld", "allow-nether", changes);

        // 1.12 以下僅接受數字形式，不轉換為名稱
        bool acceptsNamedModes = parsedVersion is null || parsedVersion >= Min113Version;
        if (acceptsNamedModes && newProps.TryGetValue("gamemode", out string? rawGm) && TryMapLegacyIndex(rawGm, GamemodeNames, out string? mappedGm))
        {
            newProps["gamemode"] = mappedGm;
            changes.Add($"遊戲模式轉換：gamemode={rawGm} ➔ {mappedGm} (1.13+)");
        }

        if (acceptsNamedModes && newProps.TryGetValue("difficulty", out string? rawDiff) && TryMapLegacyIndex(rawDiff, DifficultyNames, out string? mappedDiff))
        {
            newProps["difficulty"] = mappedDiff;
            changes.Add($"遊戲難度轉換：difficulty={rawDiff} ➔ {mappedDiff} (1.13+)");
        }

        if (parsedVersion is not null && parsedVersion >= Min119Version && newProps.TryGetValue("level-type", out string? rawLt))
        {
            if (LevelTypeSpanLookup.TryGetValue(rawLt.AsSpan().Trim(), out string? mappedLt) && !string.Equals(rawLt, mappedLt, StringComparison.Ordinal))
            {
                newProps["level-type"] = mappedLt;
                changes.Add($"地圖類型命名空間轉換：level-type={rawLt} ➔ {mappedLt} (1.19+)");
            }
        }

        foreach (var (depKey, (minRemovedVersion, reason)) in DeprecatedKeys)
        {
            if ((parsedVersion is null || parsedVersion >= minRemovedVersion) && newProps.Remove(depKey))
            {
                changes.Add($"移除廢棄屬性：{depKey} ({reason})");
            }
        }

        return new ServerPropertiesMigrationPlan(
            NeedsMigration: changes.Count > 0,
            Changes: changes,
            MigratedProperties: newProps);
    }

    private static void RenameKeyIfPresent(
        Dictionary<string, string> properties,
        string oldKey,
        string newKey,
        List<string> changes,
        string? versionNote = null)
    {
        if (!properties.Remove(oldKey, out string? oldValue))
        {
            return;
        }

        if (properties.TryAdd(newKey, oldValue))
        {
            string suffix = string.IsNullOrEmpty(versionNote) ? string.Empty : $" ({versionNote})";
            changes.Add($"屬性更名：{oldKey} ➔ {newKey}{suffix}");
        }
        else
        {
            changes.Add($"移除舊版重複屬性：{oldKey} (已存在 {newKey})");
        }
    }

    /// <summary>將遷移計畫套用並寫入指定伺服器目錄下的 server.properties</summary>
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
        string propsPath = Path.Combine(stableDir, ServerDefaults.ServerPropertiesFileName);
        if (!SafeFileSystem.FileExists(propsPath))
        {
            return false;
        }

        if (createBackup)
        {
            string backupPath = Path.Combine(stableDir, ServerDefaults.ServerPropertiesFileName + ".backup");
            try
            {
                SafeFileSystem.CopyFile(propsPath, backupPath, overwrite: true);
                Logger.Information("已建立 server.properties 備份: {BackupPath}", backupPath);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Warning(ex, "建立 server.properties.backup 失敗");
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

    private static bool TryMapLegacyIndex(string raw, string[] names, [System.Diagnostics.CodeAnalysis.NotNullWhen(true)] out string? mapped)
    {
        ReadOnlySpan<char> trimmed = raw.AsSpan().Trim();
        if (trimmed.Length == 1 && char.IsAsciiDigit(trimmed[0]) && trimmed[0] - '0' < names.Length)
        {
            mapped = names[trimmed[0] - '0'];
            return true;
        }

        mapped = null;
        return false;
    }

    private static readonly VersionValue Min119Version = new(1, 19, 0);
    private static readonly VersionValue Min113Version = new(1, 13, 0);
}
