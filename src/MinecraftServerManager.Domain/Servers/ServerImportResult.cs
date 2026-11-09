namespace MinecraftServerManager.Domain.Servers;

/// <summary>
/// 單一伺服器匯入交易結果
/// </summary>
public sealed record ServerImportResult(bool Completed, string Name, string Message = "", ServerConfig? Config = null)
{
    public static ServerImportResult Success(string name, ServerConfig config, string message = "") => new(true, name, message, config);

    public static ServerImportResult Failed(string name, string message) => new(false, name, message);
}
