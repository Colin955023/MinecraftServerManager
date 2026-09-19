using System.Globalization;
using System.Text;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Mods;

/// <summary>
/// 模組管理外觀服務實作
/// </summary>
public sealed class ModManager(
    ILocalModScanner scanner,
    IModFileInstaller installer) : IModManager
{
    public async Task<IReadOnlyList<LocalModInfo>> GetModsAsync(
        string serverDirectory,
        bool includeDisabled = true,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);
        string stableServerDir = SafeFileSystem.ResolveStableDirectory(serverDirectory, create: true);
        string modsDir = Path.Combine(stableServerDir, "mods");

        var mods = await scanner.ScanModsAsync(modsDir, cancellationToken).ConfigureAwait(false);
        return includeDisabled ? mods : mods.Where(m => m.Status == ModStatus.Enabled).ToList();
    }

    public Task<LocalModMutationResult> SetModStateAsync(
        string serverDirectory,
        string modId,
        bool enable,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);
        string stableServerDir = SafeFileSystem.ResolveStableDirectory(serverDirectory, create: true);
        string modsDir = Path.Combine(stableServerDir, "mods");
        return installer.SetModStateAsync(modsDir, modId, enable, cancellationToken);
    }

    public Task<LocalModMutationResult> DeleteModsAsync(
        string serverDirectory,
        IReadOnlyList<string> modIds,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);
        string stableServerDir = SafeFileSystem.ResolveStableDirectory(serverDirectory, create: true);
        string modsDir = Path.Combine(stableServerDir, "mods");
        return installer.DeleteModsAsync(modsDir, modIds, cancellationToken);
    }

    public Task<LocalModMutationResult> ImportModAsync(
        string serverDirectory,
        string sourceFilePath,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);
        string stableServerDir = SafeFileSystem.ResolveStableDirectory(serverDirectory, create: true);
        string modsDir = Path.Combine(stableServerDir, "mods");
        return installer.ImportLocalModAsync(modsDir, sourceFilePath, cancellationToken);
    }

    public Task<ModFileOperationResult> InstallOnlineModAsync(
        string serverDirectory,
        string downloadUrl,
        string fileName,
        string? expectedHash = null,
        string? hashAlgorithm = null,
        IProgress<int>? progress = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);
        string stableServerDir = SafeFileSystem.ResolveStableDirectory(serverDirectory, create: true);
        string modsDir = Path.Combine(stableServerDir, "mods");
        return installer.InstallRemoteModAsync(modsDir, downloadUrl, fileName, expectedHash, hashAlgorithm, progress, cancellationToken);
    }

    public async Task<string> ExportModListAsync(
        string serverDirectory,
        string format = "text",
        CancellationToken cancellationToken = default)
    {
        var mods = await GetModsAsync(serverDirectory, includeDisabled: true, cancellationToken).ConfigureAwait(false);
        string normFormat = (format ?? "text").Trim().ToLowerInvariant();

        return normFormat switch
        {
            "json" => JsonCodec.Serialize(mods, indented: true),
            "html" => BuildHtml(mods),
            "csv" => BuildCsv(mods),
            _ => BuildText(mods)
        };
    }

    private static string BuildText(IReadOnlyList<LocalModInfo> mods)
    {
        var sb = new StringBuilder();
        sb.AppendLine("# 模組清單");
        sb.AppendLine();
        foreach (var mod in mods)
        {
            string status = mod.Status == ModStatus.Enabled ? "✅" : "❌";
            string author = !string.IsNullOrEmpty(mod.Author) ? $" - by {mod.Author}" : string.Empty;
            sb.AppendLine(CultureInfo.InvariantCulture, $"{status} {mod.Name} ({mod.Version}){author}");
        }
        return sb.ToString();
    }

    private static string BuildHtml(IReadOnlyList<LocalModInfo> mods)
    {
        var sb = new StringBuilder();
        sb.AppendLine("<!DOCTYPE html><html lang=\"zh-TW\"><head><meta charset=\"UTF-8\"><title>模組列表</title>");
        sb.AppendLine("<style>table{border-collapse:collapse;width:100%;}th,td{border:1px solid #ccc;padding:8px;text-align:left;}th{background:#f4f4f4;}</style></head><body>");
        sb.AppendLine("<h2>模組清單</h2><table><tr><th>狀態</th><th>名稱</th><th>版本</th><th>MC版本</th><th>作者</th><th>檔名</th></tr>");
        foreach (var m in mods)
        {
            string st = m.Status == ModStatus.Enabled ? "✅" : "❌";
            sb.AppendLine(CultureInfo.InvariantCulture, $"<tr><td>{st}</td><td>{System.Net.WebUtility.HtmlEncode(m.Name)}</td><td>{System.Net.WebUtility.HtmlEncode(m.Version)}</td><td>{System.Net.WebUtility.HtmlEncode(m.MinecraftVersion)}</td><td>{System.Net.WebUtility.HtmlEncode(m.Author)}</td><td>{System.Net.WebUtility.HtmlEncode(m.Filename)}</td></tr>");
        }
        sb.AppendLine("</table></body></html>");
        return sb.ToString();
    }

    private static string BuildCsv(IReadOnlyList<LocalModInfo> mods)
    {
        var sb = new StringBuilder();
        sb.AppendLine("狀態,名稱,版本,MC版本,載入器,作者,檔名");
        foreach (var m in mods)
        {
            string st = m.Status == ModStatus.Enabled ? "啟用" : "停用";
            sb.AppendLine(CultureInfo.InvariantCulture, $"\"{st}\",\"{EscapeCsv(m.Name)}\",\"{EscapeCsv(m.Version)}\",\"{EscapeCsv(m.MinecraftVersion)}\",\"{EscapeCsv(m.LoaderType)}\",\"{EscapeCsv(m.Author)}\",\"{EscapeCsv(m.Filename)}\"");
        }
        return sb.ToString();
    }

    private static string EscapeCsv(string value) =>
        (value ?? string.Empty).Replace("\"", "\"\"");
}
