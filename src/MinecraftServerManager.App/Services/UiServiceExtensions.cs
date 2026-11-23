using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.App.Services;

/// <summary><see cref="IUiService"/> 與進度回報擴充方法</summary>
public static class UiServiceExtensions
{
    /// <summary>以預設標題顯示通知</summary>
    public static void Notify(this IUiService ui, string message, NotificationType type = NotificationType.Info)
    {
        ArgumentNullException.ThrowIfNull(ui);
        ui.ShowNotification(message, NotificationPresentation.GetDefaultTitle(type), type);
    }

    /// <summary>以預設瀏覽器開啟網址；失敗時顯示警告</summary>
    public static void OpenUrlOrWarn(this IUiService ui, IExternalLauncher launcher, string url)
    {
        ArgumentNullException.ThrowIfNull(launcher);
        if (!launcher.OpenUrl(url))
        {
            ui.Notify($"無法開啟連結：{url}", NotificationType.Warning);
        }
    }

    /// <summary>以檔案總管開啟資料夾；失敗時顯示警告</summary>
    public static void OpenFolderOrWarn(this IUiService ui, IExternalLauncher launcher, string folderPath)
    {
        ArgumentNullException.ThrowIfNull(launcher);
        if (!launcher.OpenFolder(folderPath))
        {
            ui.Notify($"無法開啟資料夾：{folderPath}", NotificationType.Warning);
        }
    }

    /// <summary>以預設程式開啟檔案；失敗時顯示警告，<paramref name="title"/> 為空則用預設標題</summary>
    public static void OpenFileOrWarn(this IUiService ui, IExternalLauncher launcher, string filePath, bool isTrusted = false, string? title = null)
    {
        ArgumentNullException.ThrowIfNull(launcher);
        if (!launcher.OpenFile(filePath, isTrusted))
        {
            ui.ShowNotification($"無法開啟檔案：{filePath}", title ?? NotificationPresentation.GetDefaultTitle(NotificationType.Warning), NotificationType.Warning);
        }
    }

    /// <summary>以檔案總管開啟並選取檔案；失敗時顯示警告</summary>
    public static void ShowInFolderOrWarn(this IUiService ui, IExternalLauncher launcher, string filePath)
    {
        ArgumentNullException.ThrowIfNull(launcher);
        if (!launcher.ShowInFolder(filePath))
        {
            ui.Notify($"無法在資料夾中顯示：{filePath}", NotificationType.Warning);
        }
    }

    /// <summary>建立轉接至 <see cref="IOperationProgress"/> 的同步進度報告器</summary>
    public static IProgress<(int Percent, string Message)> CreateProgress(this IOperationProgress dialog)
    {
        ArgumentNullException.ThrowIfNull(dialog);
        return new SynchronousProgress<(int Percent, string Message)>(p => dialog.UpdateProgress(p.Percent, 100, p.Message));
    }

    /// <summary>檢查執行條件；若為執行中則顯示警告通知並回傳 false</summary>
    public static bool EnsureServerStopped(this IUiService ui, bool isRunning, string message, string? title = null)
    {
        ArgumentNullException.ThrowIfNull(ui);
        if (isRunning)
        {
            ui.ShowNotification(message, title ?? NotificationPresentation.GetDefaultTitle(NotificationType.Warning), NotificationType.Warning);
            return false;
        }

        return true;
    }

    /// <summary>檢查指定伺服器是否未在執行；若執行中則顯示警告通知並回傳 false</summary>
    public static bool EnsureServerStopped(this IUiService ui, IServerRuntimeHost runtimeHost, string serverName, string action, string? title = null)
    {
        ArgumentNullException.ThrowIfNull(runtimeHost);
        return ui.EnsureServerStopped(
            runtimeHost.IsRunning(serverName),
            $"伺服器「{serverName}」正在執行中，請先停止伺服器再{action}",
            title);
    }

    /// <summary>讀取伺服器設定；找不到時顯示警告通知並回傳 null</summary>
    public static async Task<ServerConfig?> GetServerOrWarnAsync(
        this IUiService ui,
        IServerManager serverManager,
        string serverName,
        NotificationType notificationType = NotificationType.Warning)
    {
        ArgumentNullException.ThrowIfNull(ui);
        ArgumentNullException.ThrowIfNull(serverManager);
        var config = await serverManager.GetServerAsync(serverName);
        if (config is null)
        {
            ui.Notify($"找不到伺服器「{serverName}」的設定，請重新整理清單", notificationType);
        }

        return config;
    }
}
