using System.Globalization;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.App.Services;

/// <summary>伺服器啟動前置檢查：連接埠衝突與啟動前自動備份；回傳是否可繼續啟動</summary>
public sealed class ServerStartPreflight(
    IUiService ui,
    SettingsManager settings,
    IServerBackupService backupService,
    IServerPropertiesStore propertiesStore,
    IServerRuntimeHost runtimeHost)
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerStartPreflight));

    /// <summary>執行前置檢查；回傳 true 表示可繼續啟動</summary>
    public async Task<bool> RunAsync(ServerConfig server)
    {
        ArgumentNullException.ThrowIfNull(server);
        string name = server.Name.Value;

        if (!await CheckPortAsync(name).ConfigureAwait(true))
        {
            return false;
        }

        return await RunAutoBackupAsync(server, name).ConfigureAwait(true);
    }

    private async Task<bool> CheckPortAsync(string name)
    {
        var others = runtimeHost.GetRunningServerNames()
            .Where(n => !string.Equals(n, name, StringComparison.OrdinalIgnoreCase))
            .ToList();
        if (others.Count == 0)
        {
            return true;
        }

        string port = await ReadPortAsync(name).ConfigureAwait(true);
        foreach (string other in others)
        {
            if (string.Equals(await ReadPortAsync(other).ConfigureAwait(true), port, StringComparison.Ordinal))
            {
                ui.ShowNotification(
                    $"伺服器「{other}」正在使用連接埠 {port}，無法同時啟動「{name}」。\n請先於「屬性設定」修改其中一台的 server-port。",
                    "連接埠衝突",
                    NotificationType.Warning);
                return false;
            }
        }

        return true;
    }

    private async Task<string> ReadPortAsync(string serverName)
    {
        try
        {
            var snapshot = await propertiesStore.ReadAsync(serverName).ConfigureAwait(true);
            if (snapshot.Readable
                && snapshot.Properties.TryGetValue("server-port", out string? value)
                && int.TryParse(value.Trim(), NumberStyles.None, CultureInfo.InvariantCulture, out int port))
            {
                return port.ToString(CultureInfo.InvariantCulture);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "讀取伺服器「{Server}」連接埠失敗，視為預設連接埠", serverName);
        }

        return ServerDefaults.DefaultPort;
    }

    private async Task<bool> RunAutoBackupAsync(ServerConfig server, string name)
    {
        if (!settings.IsAutoBackupBeforeStartEnabled())
        {
            return true;
        }

        if (string.IsNullOrWhiteSpace(server.BackupPath) || backupService.ValidateBackupDestination(server.BackupPath) is not null)
        {
            return await ui.ConfirmAsync(
                $"已啟用「啟動前自動備份」，但伺服器「{name}」尚未設定有效的備份資料夾，無法備份。\n\n是否仍要啟動伺服器？",
                "無法執行自動備份",
                UiMessageLevel.Warning).ConfigureAwait(true);
        }

        try
        {
            string destinationPath = backupService.PrepareBackupFilePath(name, server.BackupPath);
            ServerBackupInfo backup;
            using (var session = ui.ShowServerBackupProgress(name))
            {
                backup = await backupService.CreateBackupAsync(name, destinationPath: destinationPath, progress: session.Progress).ConfigureAwait(true);
            }

            ui.Notify($"已完成啟動前自動備份：{backup.FileName}", NotificationType.Success);
            return true;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "啟動前自動備份失敗");
            return await ui.ConfirmAsync(
                $"啟動前自動備份失敗：{ex.Message}\n\n是否仍要啟動伺服器？",
                "自動備份失敗",
                UiMessageLevel.Warning).ConfigureAwait(true);
        }
    }
}
