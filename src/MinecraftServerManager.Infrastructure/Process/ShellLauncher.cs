using System.Collections.Frozen;
using System.Diagnostics;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Process;

/// <summary>以殼層開啟資料夾、檔案與網址；殼層啟動動作由建構子注入</summary>
public sealed class ShellLauncher : IExternalLauncher
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ShellLauncher));

    private static readonly FrozenSet<string> AllowedOpenFileExtensions = FrozenSet.Create(
        StringComparer.OrdinalIgnoreCase,
        ".txt", ".log", ".json", ".toml", ".properties", ".yml", ".yaml", ".ini", ".cfg", ".md", ".csv", ".html", ".htm", ".xlsx", ".xml");

    private static readonly string ExplorerPath = Path.Combine(RuntimePaths.GetWindowsDir(), "explorer.exe");

    private readonly Action<ProcessStartInfo> _startShell;

    public ShellLauncher(Action<ProcessStartInfo> startShell)
    {
        ArgumentNullException.ThrowIfNull(startShell);
        _startShell = startShell;
    }

    /// <summary>正式環境的殼層啟動動作</summary>
    public static void StartShellProcess(ProcessStartInfo startInfo) =>
        System.Diagnostics.Process.Start(startInfo)?.Dispose();

    public bool OpenFolder(string folderPath)
    {
        if (string.IsNullOrWhiteSpace(folderPath) || !SafeFileSystem.DirectoryExists(folderPath))
        {
            Logger.Warning("開啟資料夾失敗，路徑不存在或為空: {Path}", folderPath);
            return false;
        }

        return ExecuteAndLog(CreateShellStartInfo(Path.GetFullPath(folderPath)), folderPath, "開啟資料夾");
    }

    public bool ShowInFolder(string filePath)
    {
        if (string.IsNullOrWhiteSpace(filePath) || !SafeFileSystem.FileExists(filePath))
        {
            Logger.Warning("在資料夾中顯示失敗，檔案不存在或為空: {Path}", filePath);
            return false;
        }

        // 固定系統目錄的 explorer.exe，參數經 ArgumentList 轉義，不經殼層解析
        var startInfo = new ProcessStartInfo { FileName = ExplorerPath, UseShellExecute = false };
        startInfo.ArgumentList.Add("/select,");
        startInfo.ArgumentList.Add(Path.GetFullPath(filePath));
        return ExecuteAndLog(startInfo, filePath, "在資料夾中顯示檔案");
    }

    public bool OpenFile(string filePath, bool isTrusted = false)
    {
        if (string.IsNullOrWhiteSpace(filePath) || !SafeFileSystem.FileExists(filePath))
        {
            Logger.Warning("開啟檔案失敗，檔案不存在或為空: {Path}", filePath);
            return false;
        }

        // 若為程式內建或受信任的產出內容，不需判斷是否拒絕開啟
        if (!isTrusted)
        {
            string ext = Path.GetExtension(filePath);
            if (!AllowedOpenFileExtensions.Contains(ext))
            {
                Logger.Warning("拒絕開啟不具備允許副檔名白名單之檔案: {Path}", filePath);
                return false;
            }
        }

        return ExecuteAndLog(CreateShellStartInfo(Path.GetFullPath(filePath)), filePath, "開啟檔案");
    }

    public bool OpenUrl(string url)
    {
        if (string.IsNullOrWhiteSpace(url) || !Uri.TryCreate(url, UriKind.Absolute, out var uri))
        {
            Logger.Warning("開啟網址失敗，無效的 URL: {Url}", url);
            return false;
        }

        // 一律只允許 HTTP/HTTPS，避免外部資料夾帶 file:、ms-settings: 等協定
        if (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps)
        {
            Logger.Warning("開啟網址被拒絕，非 HTTP/HTTPS 協定: {Url}", url);
            return false;
        }

        return ExecuteAndLog(CreateShellStartInfo(uri.AbsoluteUri), url, "開啟網址");
    }

    private static ProcessStartInfo CreateShellStartInfo(string fileName) =>
        new() { FileName = fileName, UseShellExecute = true };

    /// <summary>以殼層方式啟動目標並記錄結果；成功回傳 true，失敗記錄例外並回傳 false</summary>
    private bool ExecuteAndLog(ProcessStartInfo startInfo, string target, string actionName)
    {
        try
        {
            _startShell(startInfo);
            Logger.Information("已{Action}: {Target}", actionName, target);
            return true;
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "{Action}失敗: {Target}", actionName, target);
            return false;
        }
    }
}
