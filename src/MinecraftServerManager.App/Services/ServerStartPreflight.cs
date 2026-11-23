using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.App.Services;

/// <summary>伺服器啟動前置檢查：連接埠衝突與啟動前自動備份；回傳是否可繼續啟動</summary>
public sealed class ServerStartPreflight
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerStartPreflight));

    private readonly IUiService _ui;
    private readonly ISettingsManager _settings;
    private readonly IServerBackupService _backupService;
    private readonly IServerPropertiesStore _propertiesStore;
    private readonly IServerRuntimeHost _runtimeHost;

    public ServerStartPreflight(
        IUiService ui,
        ISettingsManager settings,
        IServerBackupService backupService,
        IServerPropertiesStore propertiesStore,
        IServerRuntimeHost runtimeHost)
    {
        ArgumentNullException.ThrowIfNull(ui);
        ArgumentNullException.ThrowIfNull(settings);
        ArgumentNullException.ThrowIfNull(backupService);
        ArgumentNullException.ThrowIfNull(propertiesStore);
        ArgumentNullException.ThrowIfNull(runtimeHost);

        _ui = ui;
        _settings = settings;
        _backupService = backupService;
        _propertiesStore = propertiesStore;
        _runtimeHost = runtimeHost;
    }

    /// <summary>執行前置檢查；回傳 true 表示可繼續啟動。自動備份期間可能有其他伺服器啟動，備份後重新檢查連接埠</summary>
    public async Task<bool> RunAsync(ServerConfig server, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(server);
        string name = server.Name.Value;

        if (!await CheckPortAsync(name, cancellationToken))
        {
            return false;
        }

        if (!_settings.IsAutoBackupBeforeStartEnabled())
        {
            return true;
        }

        return await RunAutoBackupAsync(server, name, cancellationToken)
            && await CheckPortAsync(name, cancellationToken);
    }

    private async Task<bool> CheckPortAsync(string name, CancellationToken cancellationToken)
    {
        var others = _runtimeHost.GetRunningServerNames()
            .Where(n => !string.Equals(n, name, StringComparison.OrdinalIgnoreCase))
            .ToList();
        if (others.Count == 0)
        {
            return true;
        }

        string[] ports = await Task.WhenAll(others.Prepend(name).Select(n => ReadPortAsync(n, cancellationToken)));
        string port = ports[0];
        for (int i = 0; i < others.Count; i++)
        {
            string other = others[i];
            if (string.Equals(ports[i + 1], port, StringComparison.Ordinal))
            {
                _ui.ShowNotification(
                    $"伺服器「{other}」正在使用連接埠 {port}，無法同時啟動「{name}」。\n請先於「屬性設定」修改其中一台的 server-port。",
                    "連接埠衝突",
                    NotificationType.Warning);
                return false;
            }
        }

        return true;
    }

    private async Task<string> ReadPortAsync(string serverName, CancellationToken cancellationToken)
    {
        var (_, port) = await ServerPropertiesAddressHelper.ReadAddressAsync(_propertiesStore, serverName, cancellationToken).ConfigureAwait(false);
        return port;
    }

    private async Task<bool> RunAutoBackupAsync(ServerConfig server, string name, CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(server.BackupPath) || await _backupService.ValidateBackupDestinationAsync(server.BackupPath, cancellationToken) is not null)
        {
            return await _ui.ConfirmAsync(
                $"已啟用「啟動前自動備份」，但伺服器「{name}」尚未設定有效的備份資料夾，無法備份。\n\n是否仍要啟動伺服器？",
                "無法執行自動備份",
                UiMessageLevel.Warning);
        }

        try
        {
            string destinationPath = await _backupService.PrepareBackupFilePathAsync(name, server.BackupPath, cancellationToken);
            ServerBackupInfo backup;
            using (var session = _ui.ShowServerBackupProgress(name))
            {
                backup = await _backupService.CreateBackupAsync(name, destinationPath: destinationPath, progress: session.Progress, cancellationToken: cancellationToken);
            }

            _ui.Notify($"已完成啟動前自動備份：{backup.FileName}", NotificationType.Success);
            return true;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "啟動前自動備份失敗");
            return await _ui.ConfirmAsync(
                $"啟動前自動備份失敗：{ex.Message}\n\n是否仍要啟動伺服器？",
                "自動備份失敗",
                UiMessageLevel.Warning);
        }
    }
}
