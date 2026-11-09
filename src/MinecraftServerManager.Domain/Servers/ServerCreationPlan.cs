using MinecraftServerManager.Domain.ValueObjects;

namespace MinecraftServerManager.Domain.Servers;

/// <summary>
/// 完成驗證後可交由交易執行器提交的不可變建立計畫（記憶體等不變條件由 <see cref="ServerConfig"/> 驗證）
/// </summary>
public sealed record ServerCreationPlan(ServerConfig Config, string? UserJavaPath = null)
{
    public static ServerCreationPlan Create(
        ServerName name,
        MinecraftVersion minecraftVersion,
        LoaderKind loaderType,
        string loaderVersion = "",
        int memoryMaxMb = ServerDefaults.DefaultMemoryMaxMb,
        int? memoryMinMb = null,
        IEnumerable<string>? jvmArgs = null,
        string? userJavaPath = null) =>
        new(new ServerConfig(name, minecraftVersion, loaderType, loaderVersion, memoryMaxMb, memoryMinMb, jvmArgs: jvmArgs), userJavaPath);
}
