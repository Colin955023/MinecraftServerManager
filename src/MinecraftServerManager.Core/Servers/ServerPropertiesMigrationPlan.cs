namespace MinecraftServerManager.Core.Servers;

/// <summary>
/// 伺服器屬性遷移計畫
/// </summary>
public sealed record ServerPropertiesMigrationPlan(
    bool NeedsMigration,
    IReadOnlyList<string> Changes,
    IReadOnlyDictionary<string, string> MigratedProperties)
{
    public string Summary()
    {
        if (!NeedsMigration || Changes.Count == 0)
        {
            return "設定檔符合最新規範，無需遷移";
        }

        var sb = new System.Text.StringBuilder();
        sb.AppendLine(System.Globalization.CultureInfo.InvariantCulture, $"偵測到 {Changes.Count} 項需要遷移的舊版設定：");
        foreach (string change in Changes)
        {
            sb.Append("- ").AppendLine(change);
        }

        return sb.ToString().TrimEnd();
    }
}
