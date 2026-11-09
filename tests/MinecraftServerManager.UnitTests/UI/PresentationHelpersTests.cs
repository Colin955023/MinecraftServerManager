using System.Text.RegularExpressions;
using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using Xunit;

namespace MinecraftServerManager.UnitTests.UI;

/// <summary>
/// 呈現層共用工具測試：記錄行緩衝、通知呈現規則、主題資源鍵與表格排序鍵涵蓋
/// </summary>
public sealed partial class PresentationHelpersTests
{
    [GeneratedRegex("SortPropertyName=\"(?<name>[A-Za-z]+)\"")]
    private static partial Regex SortPropertyNameRegex();

    [Fact]
    public void LogLineBuffer_DropsOldestWhenFull()
    {
        var buffer = new LogLineBuffer(3);
        foreach (string line in (string[])["a", "b", "c", "d", "e"])
        {
            buffer.Post(line);
        }

        var drained = new List<string>();
        Assert.Equal(3, buffer.DrainTo(drained));
        Assert.Equal(["c", "d", "e"], drained);
        Assert.Equal(0, buffer.Count);
    }

    [Fact]
    public void LogLineBuffer_DrainRespectsMaxLines()
    {
        var buffer = new LogLineBuffer(10);
        for (int i = 0; i < 5; i++)
        {
            buffer.Post($"L{i}");
        }

        var batch = new List<string>();
        Assert.Equal(2, buffer.DrainTo(batch, maxLines: 2));
        Assert.Equal(3, buffer.Count);
        Assert.Equal(["L0", "L1"], batch);
    }

    [Fact]
    public void LogLineBuffer_FlushTrimsToLowWatermark()
    {
        var buffer = new LogLineBuffer(100);
        var target = new BulkObservableCollection<string>();
        for (int i = 0; i < 30; i++)
        {
            buffer.Post($"L{i}");
        }

        Assert.True(buffer.FlushTo(target, highWatermark: 20, lowWatermark: 10));
        Assert.Equal(10, target.Count);
        Assert.Equal("L20", target[0]);
        Assert.Equal("L29", target[^1]);
        Assert.False(buffer.FlushTo(target, 20, 10));
    }

    [Fact]
    public void LogLineBuffer_ClearDiscardsPending()
    {
        var buffer = new LogLineBuffer(10);
        buffer.Post("x");
        buffer.Clear();

        Assert.Equal(0, buffer.Count);
        Assert.Throws<ArgumentOutOfRangeException>(static () => new LogLineBuffer(0));
    }

    [Theory]
    [InlineData(NotificationType.Info, false, InfoBarSeverity.Informational, 3)]
    [InlineData(NotificationType.Success, false, InfoBarSeverity.Success, 3)]
    [InlineData(NotificationType.Warning, false, InfoBarSeverity.Warning, 8)]
    [InlineData(NotificationType.Error, true, InfoBarSeverity.Informational, 3)]
    public void Notification_ErrorsUseDialogsAndOthersUseInfoBar(NotificationType type, bool usesDialog, InfoBarSeverity severity, int seconds)
    {
        Assert.Equal(usesDialog, NotificationPresentation.UsesDialog(type));
        Assert.Equal(severity, NotificationPresentation.ToSeverity(type));
        Assert.Equal(seconds, NotificationPresentation.GetDisplaySeconds(type));
    }

    [Theory]
    [InlineData(NotificationType.Info, "提示")]
    [InlineData(NotificationType.Success, "完成")]
    [InlineData(NotificationType.Warning, "警告")]
    [InlineData(NotificationType.Error, "錯誤")]
    public void Notification_DefaultTitleMatchesType(NotificationType type, string title) =>
        Assert.Equal(title, NotificationPresentation.GetDefaultTitle(type));

    [Fact]
    public void UiBindHelpers_ReturnThemeResourceKeys()
    {
        Assert.Equal(UiBindHelpers.DangerTextBrushKey, UiBindHelpers.ErrorBrushKey(true));
        Assert.Equal(UiBindHelpers.MutedTextBrushKey, UiBindHelpers.ErrorBrushKey(false));
        Assert.Equal(UiBindHelpers.SuccessTextBrushKey, UiBindHelpers.FormatStatusBrushKey(true));
        Assert.Equal(UiBindHelpers.MutedTextBrushKey, UiBindHelpers.FormatStatusBrushKey(false));
    }

    [Fact]
    public void ThemeResourceKeys_AreDefinedInBothThemeDictionaries()
    {
        string appXaml = File.ReadAllText(Path.Combine(FindRepositoryRoot(), "src", "MinecraftServerManager.App", "App.xaml"));
        foreach (string key in (string[])["SuccessTextBrush", "DangerTextBrush", "WarningBrush", "MutedTextBrush", "ConsoleBackgroundBrush", "ConsoleForegroundBrush", "ConsoleMutedTextBrush"])
        {
            int count = Regex.Count(appXaml, $"x:Key=\"{key}\"");
            Assert.True(count >= 2, $"主題資源 {key} 必須同時定義於深色與淺色主題字典（目前 {count} 處）");
        }
    }

    /// <summary>
    /// 每個檢視檔內的 SortPropertyName 對應之排序鍵對照表（含同一檔案內多張表格）
    /// </summary>
    private static bool IsSortKeyRegistered(string viewFile, string column) => viewFile switch
    {
        "ManageServerView.xaml" => TableSortKeys.Servers.TryGetSelector(column, out _),
        "ModsView.xaml" => TableSortKeys.LocalMods.TryGetSelector(column, out _) || TableSortKeys.OnlineMods.TryGetSelector(column, out _),
        "ModInstallQueueDialog.xaml" => TableSortKeys.InstallQueue.TryGetSelector(column, out _),
        "ModUpdatesDialog.xaml" => TableSortKeys.UpdateCandidates.TryGetSelector(column, out _),
        "ModVersionPickerDialog.xaml" => TableSortKeys.ModVersions.TryGetSelector(column, out _),
        "ManageJavaDialog.xaml" => TableSortKeys.Javas.TryGetSelector(column, out _),
        "RestoreBackupDialog.xaml" => TableSortKeys.Backups.TryGetSelector(column, out _),
        "PlayerManagementDialog.xaml" => TableSortKeys.Operators.TryGetSelector(column, out _)
            || TableSortKeys.Whitelist.TryGetSelector(column, out _)
            || TableSortKeys.BannedPlayers.TryGetSelector(column, out _)
            || TableSortKeys.BannedIps.TryGetSelector(column, out _),
        _ => throw new ArgumentOutOfRangeException(nameof(viewFile), viewFile, "未知的檢視檔"),
    };

    [Theory]
    [InlineData("ManageServerView.xaml")]
    [InlineData("ModsView.xaml")]
    [InlineData("ModInstallQueueDialog.xaml")]
    [InlineData("ModUpdatesDialog.xaml")]
    [InlineData("ModVersionPickerDialog.xaml")]
    [InlineData("ManageJavaDialog.xaml")]
    [InlineData("RestoreBackupDialog.xaml")]
    [InlineData("PlayerManagementDialog.xaml")]
    public void TableSortKeys_CoverEverySortableHeader(string viewFile)
    {
        string xaml = File.ReadAllText(Path.Combine(FindRepositoryRoot(), "src", "MinecraftServerManager.App", "Views", viewFile));

        var missing = SortPropertyNameRegex().Matches(xaml)
            .Select(static m => m.Groups["name"].Value)
            .Where(name => !IsSortKeyRegistered(viewFile, name))
            .Distinct(StringComparer.Ordinal)
            .ToList();

        Assert.True(missing.Count == 0, $"{viewFile} 的排序欄位未登錄於 TableSortKeys：{string.Join(", ", missing)}");
    }

    [Fact]
    public void ServerSizeSortKey_UsesRawBytesSoPlaceholderSortsFirst()
    {
        var items = new List<ServerRowItem>
        {
            new() { Name = "Big", Size = "1.2 GB", RawSizeBytes = 1_288_490_188 },
            new() { Name = "Pending", Size = "-", RawSizeBytes = -1 },
            new() { Name = "Small", Size = "900 MB", RawSizeBytes = 943_718_400 },
        };

        Assert.True(TableSortKeys.Servers.TryGetSelector("size", out var selector));
        items = [.. items.OrderBy(selector, SortKeyComparer.Instance)];

        Assert.Equal(["Pending", "Small", "Big"], items.Select(static i => i.Name));
    }

    [Fact]
    public void CompareSortKeys_HandlesNullsAndMixedTypes()
    {
        Assert.Equal(0, NaturalSortHelper.CompareSortKeys(null, null));
        Assert.True(NaturalSortHelper.CompareSortKeys(null, "a") < 0);
        Assert.True(NaturalSortHelper.CompareSortKeys(2, 10) < 0);
        Assert.True(NaturalSortHelper.CompareSortKeys(false, true) < 0);
        Assert.True(NaturalSortHelper.CompareSortKeys(2, "10") < 0);
    }

    private static string FindRepositoryRoot()
    {
        string? dir = AppContext.BaseDirectory;
        while (dir is not null && !File.Exists(Path.Combine(dir, "MinecraftServerManager.slnx")))
        {
            dir = Path.GetDirectoryName(dir);
        }

        return dir ?? throw new DirectoryNotFoundException("找不到儲存庫根目錄");
    }
}
