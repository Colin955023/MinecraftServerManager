namespace MinecraftServerManager.App.ViewModels;

/// <summary>主導覽頁面鍵與導覽動作鍵；供 <see cref="MainViewModel"/> 與主視窗導覽共用（XAML Tag 須與之保持相同字串）</summary>
public static class PageKeys
{
    public const string Create = "create";
    public const string Manage = "manage";
    public const string Mods = "mods";
    public const string AboutPreferences = "about_preferences";

    /// <summary>導覽動作（非頁面）：匯入伺服器</summary>
    public const string Import = "import";

    /// <summary>導覽動作（非頁面）：開啟伺服器資料夾</summary>
    public const string OpenFolder = "open_folder";
}
