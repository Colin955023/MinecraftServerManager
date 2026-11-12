using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.App.Controls;

/// <summary>各表格欄位之型別化排序鍵（欄位名稱須與 XAML SortPropertyName 一致；容量與下載量採原始數值排序）</summary>
public static class TableSortKeys
{
    public static readonly SortKeyMap<ServerRowItem> Servers = new SortKeyMap<ServerRowItem>(
        ("Name", static r => r.Name),
        ("Version", static r => r.Version),
        ("Loader", static r => r.Loader),
        ("Status", static r => r.Status),
        ("Size", static r => r.RawSizeBytes),
        ("LastModified", static r => r.RawLastModifiedTicks),
        ("BackupStatus", static r => r.BackupStatus),
        ("RelativePath", static r => r.RelativePath))
        .WithDisplay(
            ("Size", static r => r.Size),
            ("LastModified", static r => r.LastModified));

    public static readonly SortKeyMap<LocalModRowItem> LocalMods = new SortKeyMap<LocalModRowItem>(
        ("IsEnabled", static r => r.IsEnabled),
        ("Name", static r => r.Name),
        ("Version", static r => r.Version),
        ("Author", static r => r.Author),
        ("LoaderType", static r => r.LoaderType),
        ("SourcePlatform", static r => r.SourcePlatform),
        ("FileSize", static r => r.RawFileSize),
        ("ModifiedTime", static r => r.ModifiedTime),
        ("Description", static r => r.Description))
        .WithDisplay(("FileSize", static r => r.FileSize));

    public static readonly SortKeyMap<OnlineModRowItem> OnlineMods = new SortKeyMap<OnlineModRowItem>(
        ("Title", static r => r.Title),
        ("Author", static r => r.Author),
        ("Downloads", static r => r.DownloadCountRaw),
        ("LatestVersion", static r => r.LatestVersion),
        ("Description", static r => r.Description))
        .WithDisplay(("Downloads", static r => r.Downloads));

    public static readonly SortKeyMap<ModInstallQueueItem> InstallQueue = new(
        ("ActionText", static r => r.ActionText),
        ("Title", static r => r.Title),
        ("VersionDisplay", static r => r.VersionDisplay),
        ("FileName", static r => r.FileName),
        ("Reason", static r => r.Reason));

    public static readonly SortKeyMap<ModUpdateCandidateItem> UpdateCandidates = new(
        ("IsSelected", static r => r.IsSelected),
        ("ModName", static r => r.ModName),
        ("CurrentVersion", static r => r.CurrentVersion),
        ("NewVersion", static r => r.NewVersion),
        ("FileName", static r => r.FileName),
        ("SourcePlatform", static r => r.SourcePlatform));

    public static readonly SortKeyMap<ModVersionDisplayItem> ModVersions = new(
        ("VersionNumber", static r => r.VersionNumber),
        ("GameVersions", static r => r.GameVersions),
        ("Loaders", static r => r.Loaders),
        ("DatePublished", static r => r.DatePublished),
        ("FileName", static r => r.FileName));

    public static readonly SortKeyMap<JavaItemViewModel> Javas = new SortKeyMap<JavaItemViewModel>(
        ("MajorVersion", static r => r.MajorVersion),
        ("Vendor", static r => r.Vendor),
        ("StatusText", static r => r.StatusText),
        ("ExecutablePath", static r => r.ExecutablePath))
        .WithDisplay(("MajorVersion", static r => r.DisplayName));

    public static readonly SortKeyMap<BackupDisplayItem> Backups = new SortKeyMap<BackupDisplayItem>(
        ("FileName", static r => r.FileName),
        ("SizeFormatted", static r => r.SizeBytes),
        ("CreatedAtFormatted", static r => r.CreatedAtTicks))
        .WithDisplay(("SizeFormatted", static r => r.SizeFormatted), ("CreatedAtFormatted", static r => r.CreatedAtFormatted));

    public static readonly SortKeyMap<OperatorRowItem> Operators = new(
        ("IsOp", static r => r.IsOp),
        ("Name", static r => r.Name),
        ("Level", static r => r.Level),
        ("BypassesPlayerLimit", static r => r.BypassesPlayerLimit),
        ("Uuid", static r => r.Uuid));

    public static readonly SortKeyMap<ServerWhitelistEntry> Whitelist = new(
        ("Name", static r => r.Name),
        ("Uuid", static r => r.Uuid));

    public static readonly SortKeyMap<ServerBannedPlayerEntry> BannedPlayers = new(
        ("Name", static r => r.Name),
        ("Reason", static r => r.Reason),
        ("FormattedCreated", static r => r.FormattedCreated),
        ("Uuid", static r => r.Uuid));

    public static readonly SortKeyMap<ServerBannedIpEntry> BannedIps = new(
        ("Ip", static r => r.Ip),
        ("Reason", static r => r.Reason),
        ("FormattedCreated", static r => r.FormattedCreated));
}
