using CommunityToolkit.Mvvm.ComponentModel;
using Microsoft.UI.Xaml;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 伺服器列表欄位寬度管理：提供表頭與清單列強型別雙向同步與動態寬度調整
/// </summary>
public sealed partial class ServerListColumns : ObservableObject
{
    public static ServerListColumns Current { get; } = new();

    public static readonly double DefaultNameWidth = 180;
    public static readonly double DefaultVersionWidth = 90;
    public static readonly double DefaultLoaderWidth = 100;
    public static readonly double DefaultStatusWidth = 110;
    public static readonly double DefaultSizeWidth = 100;
    public static readonly double DefaultModifiedWidth = 140;
    public static readonly double DefaultBackupWidth = 100;
    public static readonly double DefaultPathWidth = 180;

    [ObservableProperty] public partial GridLength NameWidth { get; set; } = new(180);
    [ObservableProperty] public partial GridLength VersionWidth { get; set; } = new(90);
    [ObservableProperty] public partial GridLength LoaderWidth { get; set; } = new(100);
    [ObservableProperty] public partial GridLength StatusWidth { get; set; } = new(110);
    [ObservableProperty] public partial GridLength SizeWidth { get; set; } = new(100);
    [ObservableProperty] public partial GridLength ModifiedWidth { get; set; } = new(140);
    [ObservableProperty] public partial GridLength BackupWidth { get; set; } = new(100);
    [ObservableProperty] public partial GridLength PathWidth { get; set; } = new(1, GridUnitType.Star);

    public void ResetAll()
    {
        NameWidth = new(DefaultNameWidth);
        VersionWidth = new(DefaultVersionWidth);
        LoaderWidth = new(DefaultLoaderWidth);
        StatusWidth = new(DefaultStatusWidth);
        SizeWidth = new(DefaultSizeWidth);
        ModifiedWidth = new(DefaultModifiedWidth);
        BackupWidth = new(DefaultBackupWidth);
        PathWidth = new(1, GridUnitType.Star);
    }
}

/// <summary>
/// 本地模組列表欄位寬度管理
/// </summary>
public sealed partial class LocalModListColumns : ObservableObject
{
    public static LocalModListColumns Current { get; } = new();

    public const double DefaultEnabledWidth = 60;
    public const double DefaultNameWidth = 200;
    public const double DefaultVersionWidth = 110;
    public const double DefaultAuthorWidth = 120;
    public const double DefaultLoaderWidth = 90;
    public const double DefaultPlatformWidth = 95;
    public const double DefaultSizeWidth = 100;
    public const double DefaultModifiedWidth = 140;
    public const double DefaultDescriptionWidth = 200;

    [ObservableProperty] public partial GridLength EnabledWidth { get; set; } = new(DefaultEnabledWidth);
    [ObservableProperty] public partial GridLength NameWidth { get; set; } = new(DefaultNameWidth);
    [ObservableProperty] public partial GridLength VersionWidth { get; set; } = new(DefaultVersionWidth);
    [ObservableProperty] public partial GridLength AuthorWidth { get; set; } = new(DefaultAuthorWidth);
    [ObservableProperty] public partial GridLength LoaderWidth { get; set; } = new(DefaultLoaderWidth);
    [ObservableProperty] public partial GridLength PlatformWidth { get; set; } = new(DefaultPlatformWidth);
    [ObservableProperty] public partial GridLength SizeWidth { get; set; } = new(DefaultSizeWidth);
    [ObservableProperty] public partial GridLength ModifiedWidth { get; set; } = new(DefaultModifiedWidth);
    [ObservableProperty] public partial GridLength DescriptionWidth { get; set; } = new(1, GridUnitType.Star);
}

/// <summary>
/// 線上模組瀏覽列表欄位寬度管理
/// </summary>
public sealed partial class OnlineModListColumns : ObservableObject
{
    public static OnlineModListColumns Current { get; } = new();

    public const double DefaultTitleWidth = 220;
    public const double DefaultAuthorWidth = 120;
    public const double DefaultDownloadsWidth = 100;
    public const double DefaultVersionWidth = 120;
    public const double DefaultDescriptionWidth = 220;

    [ObservableProperty] public partial GridLength TitleWidth { get; set; } = new(DefaultTitleWidth);
    [ObservableProperty] public partial GridLength AuthorWidth { get; set; } = new(DefaultAuthorWidth);
    [ObservableProperty] public partial GridLength DownloadsWidth { get; set; } = new(DefaultDownloadsWidth);
    [ObservableProperty] public partial GridLength VersionWidth { get; set; } = new(DefaultVersionWidth);
    [ObservableProperty] public partial GridLength DescriptionWidth { get; set; } = new(1, GridUnitType.Star);
}

/// <summary>
/// 本機 Java 執行環境列表欄位寬度管理
/// </summary>
public sealed partial class JavaListColumns : ObservableObject
{
    public static JavaListColumns Current { get; } = new();

    public const double DefaultVersionWidth = 110;
    public const double DefaultVendorWidth = 140;
    public const double DefaultStatusWidth = 160;
    public const double DefaultPathWidth = 240;

    [ObservableProperty] public partial GridLength VersionWidth { get; set; } = new(DefaultVersionWidth);
    [ObservableProperty] public partial GridLength VendorWidth { get; set; } = new(DefaultVendorWidth);
    [ObservableProperty] public partial GridLength StatusWidth { get; set; } = new(DefaultStatusWidth);
    [ObservableProperty] public partial GridLength PathWidth { get; set; } = new(1, GridUnitType.Star);
}

/// <summary>
/// 備份還原列表欄位寬度管理
/// </summary>
public sealed partial class BackupListColumns : ObservableObject
{
    public static BackupListColumns Current { get; } = new();

    public const double DefaultFileNameWidth = 300;
    public const double DefaultSizeWidth = 120;
    public const double DefaultCreatedWidth = 170;

    [ObservableProperty] public partial GridLength FileNameWidth { get; set; } = new(DefaultFileNameWidth);
    [ObservableProperty] public partial GridLength SizeWidth { get; set; } = new(DefaultSizeWidth);
    [ObservableProperty] public partial GridLength CreatedWidth { get; set; } = new(1, GridUnitType.Star);
}

/// <summary>
/// 模組版本選擇列表欄位寬度管理
/// </summary>
public sealed partial class ModVersionListColumns : ObservableObject
{
    public static ModVersionListColumns Current { get; } = new();

    public const double DefaultVersionWidth = 150;
    public const double DefaultGameVersionWidth = 140;
    public const double DefaultLoaderWidth = 120;
    public const double DefaultDateWidth = 120;
    public const double DefaultFileNameWidth = 180;

    [ObservableProperty] public partial GridLength VersionWidth { get; set; } = new(DefaultVersionWidth);
    [ObservableProperty] public partial GridLength GameVersionWidth { get; set; } = new(DefaultGameVersionWidth);
    [ObservableProperty] public partial GridLength LoaderWidth { get; set; } = new(DefaultLoaderWidth);
    [ObservableProperty] public partial GridLength DateWidth { get; set; } = new(DefaultDateWidth);
    [ObservableProperty] public partial GridLength FileNameWidth { get; set; } = new(1, GridUnitType.Star);
}

/// <summary>
/// 待安裝模組清單欄位寬度管理
/// </summary>
public sealed partial class ModQueueListColumns : ObservableObject
{
    public static ModQueueListColumns Current { get; } = new();

    public const double DefaultActionWidth = 75;
    public const double DefaultTitleWidth = 180;
    public const double DefaultVersionWidth = 130;
    public const double DefaultFileNameWidth = 170;
    public const double DefaultReasonWidth = 160;

    [ObservableProperty] public partial GridLength ActionWidth { get; set; } = new(DefaultActionWidth);
    [ObservableProperty] public partial GridLength TitleWidth { get; set; } = new(DefaultTitleWidth);
    [ObservableProperty] public partial GridLength VersionWidth { get; set; } = new(DefaultVersionWidth);
    [ObservableProperty] public partial GridLength FileNameWidth { get; set; } = new(DefaultFileNameWidth);
    [ObservableProperty] public partial GridLength ReasonWidth { get; set; } = new(1, GridUnitType.Star);
}

/// <summary>
/// 發現模組更新列表欄位寬度管理
/// </summary>
public sealed partial class ModUpdatesListColumns : ObservableObject
{
    public static ModUpdatesListColumns Current { get; } = new();

    public const double DefaultUpdateWidth = 60;
    public const double DefaultNameWidth = 170;
    public const double DefaultCurrentVersionWidth = 110;
    public const double DefaultNewVersionWidth = 110;
    public const double DefaultPlatformWidth = 95;
    public const double DefaultFileNameWidth = 160;

    [ObservableProperty] public partial GridLength UpdateWidth { get; set; } = new(DefaultUpdateWidth);
    [ObservableProperty] public partial GridLength NameWidth { get; set; } = new(DefaultNameWidth);
    [ObservableProperty] public partial GridLength CurrentVersionWidth { get; set; } = new(DefaultCurrentVersionWidth);
    [ObservableProperty] public partial GridLength NewVersionWidth { get; set; } = new(DefaultNewVersionWidth);
    [ObservableProperty] public partial GridLength PlatformWidth { get; set; } = new(DefaultPlatformWidth);
    [ObservableProperty] public partial GridLength FileNameWidth { get; set; } = new(1, GridUnitType.Star);
}

/// <summary>
/// 管理員名單 (ops.json) 欄位寬度管理
/// </summary>
public sealed partial class OperatorListColumns : ObservableObject
{
    public static OperatorListColumns Current { get; } = new();

    public const double DefaultIsOpWidth = 75;
    public const double DefaultNameWidth = 140;
    public const double DefaultLevelWidth = 110;
    public const double DefaultBypassWidth = 120;
    public const double DefaultUuidWidth = 220;

    [ObservableProperty] public partial GridLength IsOpWidth { get; set; } = new(DefaultIsOpWidth);
    [ObservableProperty] public partial GridLength NameWidth { get; set; } = new(DefaultNameWidth);
    [ObservableProperty] public partial GridLength LevelWidth { get; set; } = new(DefaultLevelWidth);
    [ObservableProperty] public partial GridLength BypassWidth { get; set; } = new(DefaultBypassWidth);
    [ObservableProperty] public partial GridLength UuidWidth { get; set; } = new(1, GridUnitType.Star);
}

/// <summary>
/// 白名單 (whitelist.json) 欄位寬度管理
/// </summary>
public sealed partial class WhitelistListColumns : ObservableObject
{
    public static WhitelistListColumns Current { get; } = new();

    public const double DefaultNameWidth = 180;
    public const double DefaultUuidWidth = 240;
    public const double DefaultActionWidth = 90;

    [ObservableProperty] public partial GridLength NameWidth { get; set; } = new(DefaultNameWidth);
    [ObservableProperty] public partial GridLength UuidWidth { get; set; } = new(1, GridUnitType.Star);
    [ObservableProperty] public partial GridLength ActionWidth { get; set; } = new(DefaultActionWidth);
}

/// <summary>
/// 封鎖玩家名單 (banned-players.json) 欄位寬度管理
/// </summary>
public sealed partial class BannedPlayerListColumns : ObservableObject
{
    public static BannedPlayerListColumns Current { get; } = new();

    public const double DefaultNameWidth = 140;
    public const double DefaultReasonWidth = 180;
    public const double DefaultCreatedWidth = 155;
    public const double DefaultUuidWidth = 200;
    public const double DefaultActionWidth = 95;

    [ObservableProperty] public partial GridLength NameWidth { get; set; } = new(DefaultNameWidth);
    [ObservableProperty] public partial GridLength ReasonWidth { get; set; } = new(DefaultReasonWidth);
    [ObservableProperty] public partial GridLength CreatedWidth { get; set; } = new(DefaultCreatedWidth);
    [ObservableProperty] public partial GridLength UuidWidth { get; set; } = new(1, GridUnitType.Star);
    [ObservableProperty] public partial GridLength ActionWidth { get; set; } = new(DefaultActionWidth);
}

/// <summary>
/// 封鎖 IP 名單 (banned-ips.json) 欄位寬度管理
/// </summary>
public sealed partial class BannedIpListColumns : ObservableObject
{
    public static BannedIpListColumns Current { get; } = new();

    public const double DefaultIpWidth = 180;
    public const double DefaultReasonWidth = 200;
    public const double DefaultCreatedWidth = 170;
    public const double DefaultActionWidth = 95;

    [ObservableProperty] public partial GridLength IpWidth { get; set; } = new(DefaultIpWidth);
    [ObservableProperty] public partial GridLength ReasonWidth { get; set; } = new(DefaultReasonWidth);
    [ObservableProperty] public partial GridLength CreatedWidth { get; set; } = new(1, GridUnitType.Star);
    [ObservableProperty] public partial GridLength ActionWidth { get; set; } = new(DefaultActionWidth);
}
