namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>已解析之 Java 執行檔與其主版號；主版號即 Minecraft 版本官方指定者，與實際啟動所用執行檔一致</summary>
internal sealed record ResolvedJavaRuntime(string ExecutablePath, int MajorVersion);
