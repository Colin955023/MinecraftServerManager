using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Text.RegularExpressions;
using System.Xml.Linq;
using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.UnitTests.Architecture;

namespace MinecraftServerManager.UnitTests.UI;

/// <summary>呈現層共用工具測試：記錄行緩衝、通知呈現規則、主題資源鍵與表格排序鍵涵蓋</summary>
public sealed partial class PresentationHelpersTests
{
    [GeneratedRegex("SortPropertyName=\"(?<name>[A-Za-z]+)\"")]
    private static partial Regex SortPropertyNameRegex();

    [Fact]
    public void LogLineBuffer_Full_DropsOldest()
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
    public void LogLineBuffer_DrainWithLimit_RespectsMaxLines()
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
    public void LogLineBuffer_FlushOverHighWatermark_TrimsToLowWatermark()
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
    public void LogLineBuffer_Clear_DiscardsPending()
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
    public void NotificationPresentation_Type_ChoosesDialogOrInfoBar(NotificationType type, bool usesDialog, InfoBarSeverity severity, int seconds)
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
    public void GetDefaultTitle_Type_MatchesType(NotificationType type, string title) =>
        Assert.Equal(title, NotificationPresentation.GetDefaultTitle(type));

    [Fact]
    public void UiBindHelpers_States_ReturnThemeResourceKeys()
    {
        Assert.Equal(UiBindHelpers.DangerTextBrushKey, UiBindHelpers.ErrorBrushKey(true));
        Assert.Equal(UiBindHelpers.MutedTextBrushKey, UiBindHelpers.ErrorBrushKey(false));
        Assert.Equal(UiBindHelpers.SuccessTextBrushKey, UiBindHelpers.FormatStatusBrushKey(true));
        Assert.Equal(UiBindHelpers.MutedTextBrushKey, UiBindHelpers.FormatStatusBrushKey(false));
    }

    [Fact]
    public void ThemeResourceKeys_AllKeys_DefinedInBothThemes()
    {
        string appXaml = File.ReadAllText(Path.Combine(SourceScanner.SolutionRoot, "src", "MinecraftServerManager.App", "App.xaml"));
        var doc = XDocument.Parse(SourceScanner.StripXamlComments(appXaml));
        XNamespace xNs = "http://schemas.microsoft.com/winfx/2006/xaml";

        var themeDictionaries = doc.Descendants().Where(static e => e.Name.LocalName == "ResourceDictionary" && e.Parent?.Name.LocalName == "ResourceDictionary.ThemeDictionaries").ToList();
        var defaultDict = themeDictionaries.FirstOrDefault(e => (string?)e.Attribute(xNs + "Key") == "Default");
        var lightDict = themeDictionaries.FirstOrDefault(e => (string?)e.Attribute(xNs + "Key") == "Light");

        Assert.NotNull(defaultDict);
        Assert.NotNull(lightDict);

        string[] requiredKeys = [UiBindHelpers.SuccessTextBrushKey, UiBindHelpers.DangerTextBrushKey, UiBindHelpers.WarningTextBrushKey, UiBindHelpers.MutedTextBrushKey, "NotificationBackgroundBrush"];
        foreach (string key in requiredKeys)
        {
            bool inDefault = defaultDict.Descendants().Any(e => (string?)e.Attribute(xNs + "Key") == key);
            bool inLight = lightDict.Descendants().Any(e => (string?)e.Attribute(xNs + "Key") == key);

            Assert.True(inDefault, $"主題資源 {key} 必須定義於深色 (Default) 主題字典");
            Assert.True(inLight, $"主題資源 {key} 必須定義於淺色 (Light) 主題字典");
        }
    }

    /// <summary>各檢視檔的 SortPropertyName 與排序鍵對照</summary>
    private static bool IsSortKeyRegistered(string viewFile, string column) => viewFile switch
    {
        "ManageServerView.xaml" => TableSortKeys.Servers.TryGetSelector(column, out _),
        "ModsView.xaml" => TableSortKeys.LocalMods.TryGetSelector(column, out _) || TableSortKeys.OnlineMods.TryGetSelector(column, out _),
        "ModInstallQueueWindow.xaml" => TableSortKeys.InstallQueue.TryGetSelector(column, out _),
        "ModUpdatesWindow.xaml" => TableSortKeys.UpdateCandidates.TryGetSelector(column, out _),
        "ModVersionPickerWindow.xaml" => TableSortKeys.ModVersions.TryGetSelector(column, out _),
        "ManageJavaWindow.xaml" => TableSortKeys.Javas.TryGetSelector(column, out _),
        "RestoreBackupWindow.xaml" => TableSortKeys.Backups.TryGetSelector(column, out _),
        "PlayerManagementWindow.xaml" => TableSortKeys.Operators.TryGetSelector(column, out _)
            || TableSortKeys.Whitelist.TryGetSelector(column, out _)
            || TableSortKeys.BannedPlayers.TryGetSelector(column, out _)
            || TableSortKeys.BannedIps.TryGetSelector(column, out _),
        _ => throw new ArgumentOutOfRangeException(nameof(viewFile), viewFile, "未知的檢視檔"),
    };

    [Fact]
    public void TableSortKeys_AllSortableHeaders_AreCovered()
    {
        var viewFiles = SourceScanner.GetSourceFiles("src/MinecraftServerManager.App/Views", "*.xaml");
        Assert.NotEmpty(viewFiles);

        foreach (var (relativePath, fullPath) in viewFiles)
        {
            string fileName = Path.GetFileName(fullPath);
            string xaml = File.ReadAllText(fullPath);
            var matches = SortPropertyNameRegex().Matches(xaml);
            if (matches.Count == 0)
            {
                continue;
            }

            var missing = matches
                .Select(static m => m.Groups["name"].Value)
                .Where(name => !IsSortKeyRegistered(fileName, name))
                .Distinct(StringComparer.Ordinal)
                .ToList();

            Assert.True(missing.Count == 0, $"{fileName} 的排序欄位未登錄於 TableSortKeys：{string.Join(", ", missing)}");
        }
    }

    [Fact]
    public void ServerSizeSortKey_Placeholder_SortsFirstByRawBytes()
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
    public void CompareSortKeys_NullsAndMixedTypes_OrdersConsistently()
    {
        Assert.Equal(0, NaturalSortHelper.CompareSortKeys(null, null));
        Assert.True(NaturalSortHelper.CompareSortKeys(null, "a") < 0);
        Assert.True(NaturalSortHelper.CompareSortKeys(2, 10) < 0);
        Assert.True(NaturalSortHelper.CompareSortKeys(false, true) < 0);
        Assert.True(NaturalSortHelper.CompareSortKeys(2, "10") < 0);
    }

    private sealed class NamedItem
    {
        public string Name { get; init; } = string.Empty;
    }

    [Fact]
    public void NaturalSort_StringsWithNumbers_OrdersNaturally()
    {
        var items = new List<NamedItem>
        {
            new() { Name = "file10.txt" },
            new() { Name = "file2.txt" },
            new() { Name = "file1.txt" },
            new() { Name = "file20.txt" }
        };

        items = [.. items.OrderBy(static i => (object?)i.Name, SortKeyComparer.Instance)];

        Assert.Equal(["file1.txt", "file2.txt", "file10.txt", "file20.txt"], items.Select(static i => i.Name));
    }

    [Fact]
    public void NaturalSort_FileSize_OrdersByRawBytes()
    {
        var items = new List<LocalModRowItem>
        {
            new() { FileName = "b.jar", FileSize = "1.5 MB", RawFileSize = 1_500_000 },
            new() { FileName = "a.jar", FileSize = "200 KB", RawFileSize = 200_000 },
            new() { FileName = "c.jar", FileSize = "10 MB", RawFileSize = 10_000_000 }
        };

        Assert.True(TableSortKeys.LocalMods.TryGetSelector("FileSize", out var selector));
        items = [.. items.OrderBy(selector, SortKeyComparer.Instance)];

        Assert.Equal(["a.jar", "b.jar", "c.jar"], items.Select(static i => i.FileName));
    }

    [Fact]
    public void NaturalSort_Downloads_OrdersByRawCount()
    {
        var items = new List<OnlineModRowItem>
        {
            new() { Title = "Mod B", Downloads = "2,000", DownloadCountRaw = 2000 },
            new() { Title = "Mod A", Downloads = "500", DownloadCountRaw = 500 },
            new() { Title = "Mod C", Downloads = "15,000", DownloadCountRaw = 15000 }
        };

        Assert.True(TableSortKeys.OnlineMods.TryGetSelector("Downloads", out var selector));
        items = [.. items.OrderBy(selector, SortKeyComparer.Instance)];

        Assert.Equal(["Mod A", "Mod B", "Mod C"], items.Select(static i => i.Title));
    }

    [Fact]
    public void TableSortExtensions_BothDirections_SortsNaturally()
    {
        var items = new ObservableCollection<NamedItem>
        {
            new() { Name = "Server 10" },
            new() { Name = "Server 2" },
            new() { Name = "Server 1" },
        };

        var keys = new SortKeyMap<NamedItem>((nameof(NamedItem.Name), static r => r.Name));

        items.SortBy(keys, nameof(NamedItem.Name), ListSortDirection.Ascending);
        Assert.Equal(["Server 1", "Server 2", "Server 10"], items.Select(static i => i.Name));

        items.SortBy(keys, nameof(NamedItem.Name), ListSortDirection.Descending);
        Assert.Equal(["Server 10", "Server 2", "Server 1"], items.Select(static i => i.Name));

        items.SortBy(keys, "Unknown", ListSortDirection.Ascending);
        Assert.Equal(["Server 10", "Server 2", "Server 1"], items.Select(static i => i.Name));
    }

    private static double MeasureTenPerChar(string text) => text.Length * 10.0;

    [Theory]
    [InlineData("01234567890123456789", 232.0)]
    [InlineData("0123456789", 132.0)]
    [InlineData("短", 100.0)]
    public void CalculateAutoFitWidth_Items_UsesWidestMeasurement(string value, double expected) =>
        Assert.Equal(expected, SortableTableHeader.CalculateAutoFitWidth(100.0, [value], MeasureTenPerChar));

    [Fact]
    public void CalculateAutoFitWidth_WideHeader_IncludesHeaderText() =>
        Assert.Equal(160.0, SortableTableHeader.CalculateAutoFitWidth(100.0, ["a"], MeasureTenPerChar, new string('h', 12)));

    [Fact]
    public void CalculateAutoFitWidth_WithEmptyOrNullValues_KeepsDefaultWidth() =>
        Assert.Equal(100.0, SortableTableHeader.CalculateAutoFitWidth(100.0, [null, string.Empty, "   "], MeasureTenPerChar));

    [Fact]
    public void CalculateAutoFitWidth_WhenWidthExceedsMaxCap_ClampsToMaxColumnWidth() =>
        Assert.Equal(SortableTableHeader.DefaultMaxColumnWidth, SortableTableHeader.CalculateAutoFitWidth(100.0, [new string('伺', 200)], MeasureTenPerChar));

    [Fact]
    public void GetDisplayTexts_OverrideAndSortKey_PrefersOverride()
    {
        ServerRowItem[] rows = [new() { Name = "Alpha", Size = "1.5 GB", RawSizeBytes = 1_500_000_000 }];
        LocalModRowItem[] mods = [new() { IsEnabled = true }];

        Assert.Equal(["1.5 GB"], TableSortKeys.Servers.GetDisplayTexts(rows, "Size"));
        Assert.Equal(["Alpha"], TableSortKeys.Servers.GetDisplayTexts(rows, "Name"));
        Assert.Empty(TableSortKeys.Servers.GetDisplayTexts(rows, "Unknown"));
        Assert.Equal([bool.TrueString], TableSortKeys.LocalMods.GetDisplayTexts(mods, "IsEnabled"));
    }

    [Fact]
    public void LogLineBuffer_FlushBelowHighWatermark_KeepsExisting()
    {
        var buffer = new LogLineBuffer(100);
        var target = new BulkObservableCollection<string>(["A", "B"]);
        for (int i = 0; i < 5; i++)
        {
            buffer.Post($"L{i}");
        }

        Assert.True(buffer.FlushTo(target, highWatermark: 20, lowWatermark: 10));
        Assert.Equal(["A", "B", "L0", "L1", "L2", "L3", "L4"], target);
        Assert.Equal(0, buffer.Count);
    }
}
