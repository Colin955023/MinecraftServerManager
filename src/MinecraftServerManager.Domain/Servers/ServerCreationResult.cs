namespace MinecraftServerManager.Domain.Servers;

/// <summary>伺服器建立交易的最終結果</summary>
public sealed record ServerCreationResult(bool Completed, string Message = "", ServerConfig? Config = null)
{
    public static ServerCreationResult Success(ServerConfig config, string message = "") => new(true, message, config);

    public static ServerCreationResult Failed(string message) => new(false, message);
}
