using MinecraftServerManager.Domain.ValueObjects;

namespace MinecraftServerManager.Domain.Servers;

/// <summary>已驗證的不可變建立計畫</summary>
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
