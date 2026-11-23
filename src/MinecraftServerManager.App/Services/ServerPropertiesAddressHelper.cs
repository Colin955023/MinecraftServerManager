using System.Globalization;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.Services;

/// <summary>伺服器設定檔 (server.properties) 連線位址與連接埠讀取輔助</summary>
public static class ServerPropertiesAddressHelper
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerPropertiesAddressHelper));

    /// <summary>非同步讀取指定伺服器的 IP 與 Port，發生例外或未設定時降級為預設連接埠 (25565) 與空 IP</summary>
    public static async Task<(string ServerIp, string ServerPort)> ReadAddressAsync(
        IServerPropertiesStore propertiesStore,
        string serverName,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(propertiesStore);
        string serverPort = ServerDefaults.DefaultPort;
        string serverIp = string.Empty;

        try
        {
            var snapshot = await propertiesStore.ReadAsync(serverName, cancellationToken).ConfigureAwait(false);
            if (snapshot.Readable)
            {
                if (snapshot.Properties.TryGetValue("server-port", out string? port)
                    && !string.IsNullOrWhiteSpace(port)
                    && int.TryParse(port.Trim(), NumberStyles.None, CultureInfo.InvariantCulture, out int parsedPort))
                {
                    serverPort = parsedPort.ToString(CultureInfo.InvariantCulture);
                }

                if (snapshot.Properties.TryGetValue("server-ip", out string? ip) && !string.IsNullOrWhiteSpace(ip))
                {
                    serverIp = ip.Trim();
                }
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "讀取伺服器「{Server}」server.properties 連線位址失敗，降級採用預設連接埠", serverName);
        }

        return (serverIp, serverPort);
    }
}
