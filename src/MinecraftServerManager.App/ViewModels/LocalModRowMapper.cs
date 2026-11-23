using System.Globalization;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>本機模組資料與清單列、匯出列、複製文字之間的轉換</summary>
internal static class LocalModRowMapper
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(LocalModRowMapper));

    internal static LocalModRowItem ToRowItem(LocalModInfo mod) => new()
    {
        Id = mod.Id,
        Name = mod.Name,
        Version = string.IsNullOrWhiteSpace(mod.Version) ? "-" : mod.Version,
        FileName = mod.FileName,
        FileSize = mod.FileSize > 0 ? UnitFormatter.FormatBytes(mod.FileSize) : "-",
        Author = string.IsNullOrWhiteSpace(mod.Author) ? "-" : mod.Author,
        LoaderType = string.IsNullOrWhiteSpace(mod.LoaderType) ? "-" : mod.LoaderType,
        MinecraftVersion = string.IsNullOrWhiteSpace(mod.MinecraftVersion) ? "-" : mod.MinecraftVersion,
        RawFileSize = mod.FileSize,
        ModifiedTime = FormatModTime(mod.FileMtime),
        Description = mod.Description,
        IsEnabled = mod.Status == ModStatus.Enabled,
        SourcePlatform = mod.Platform == ModPlatform.CurseForge ? "CurseForge" : "Modrinth",
        CurrentHash = mod.CurrentHash,
        HashAlgorithm = mod.HashAlgorithm,
    };

    internal static string FormatModTime(double unixSeconds)
    {
        if (unixSeconds <= 0)
        {
            return "-";
        }

        try
        {
            return DateTimeOffset.FromUnixTimeSeconds((long)unixSeconds)
                .ToLocalTime()
                .ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "轉換模組發布時間失敗");
            return "-";
        }
    }

    /// <summary>組合模組資訊純文字（略過空白或 "-" 欄位）</summary>
    public static string BuildModInfoText(LocalModRowItem target)
    {
        ArgumentNullException.ThrowIfNull(target);
        var lines = new List<string>();
        AddLine(lines, "模組名稱", target.Name);
        AddLine(lines, "版本", target.Version);
        lines.Add($"狀態：{(target.IsEnabled ? "啟用" : "停用")}");
        AddLine(lines, "作者", target.Author);
        AddLine(lines, "載入器", target.LoaderType);
        AddLine(lines, "檔案大小", target.FileSize);
        AddLine(lines, "修改時間", target.ModifiedTime);
        AddLine(lines, "描述", target.Description);
        return string.Join(Environment.NewLine, lines);

        static void AddLine(List<string> lines, string label, string? value)
        {
            if (!string.IsNullOrWhiteSpace(value) && value != "-")
            {
                lines.Add($"{label}：{value.Trim()}");
            }
        }
    }

    internal static ModListExportRow ToExportRow(LocalModRowItem m) => new(
        Id: m.Id,
        Name: m.Name,
        Version: m.Version,
        FileName: m.FileName,
        FileSize: m.FileSize,
        Author: m.Author,
        LoaderType: m.LoaderType,
        MinecraftVersion: m.MinecraftVersion,
        ModifiedTime: m.ModifiedTime,
        Description: m.Description,
        IsEnabled: m.IsEnabled);
}
