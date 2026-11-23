using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Domain.ValueObjects;
using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.UnitTests.TestSupport;

/// <summary>測試用伺服器設定與啟動計畫工廠，預設值為 1.21.4 原版、2048 MB，不碰檔案系統</summary>
internal static class TestServerConfigs
{
    public static ServerConfig Create(
        string name = "TestServer",
        string minecraftVersion = "1.21.4",
        LoaderKind loader = LoaderKind.Vanilla,
        string loaderVersion = "",
        int memoryMaxMb = 2048,
        int? memoryMinMb = null,
        string path = "",
        IEnumerable<string>? jvmArgs = null,
        string backupPath = "") =>
        new(
            ServerName.Parse(name),
            MinecraftVersion.Parse(minecraftVersion),
            loader,
            loaderVersion,
            memoryMaxMb,
            memoryMinMb,
            path,
            jvmArgs,
            backupPath);

    public static ServerConfig With(
        this ServerConfig source,
        string? name = null,
        string? minecraftVersion = null,
        LoaderKind? loader = null,
        string? loaderVersion = null,
        int? memoryMaxMb = null,
        int? memoryMinMb = null,
        string? path = null,
        IEnumerable<string>? jvmArgs = null,
        string? backupPath = null) =>
        new(
            name is not null ? ServerName.Parse(name) : source.Name,
            minecraftVersion is not null ? MinecraftVersion.Parse(minecraftVersion) : source.MinecraftVersion,
            loader ?? source.LoaderType,
            loaderVersion ?? source.LoaderVersion,
            memoryMaxMb ?? source.MemoryMaxMb,
            memoryMinMb ?? source.MemoryMinMb,
            path ?? source.Path,
            jvmArgs ?? source.JvmArgs,
            backupPath ?? source.BackupPath);

    public static ServerLaunchPlan CreatePlan(
        string name,
        string path,
        string target = "server.jar",
        string javaPath = "java.exe",
        int memoryMaxMb = 1024,
        int? memoryMinMb = null,
        IEnumerable<string>? jvmArgs = null) =>
        new ServerLaunchPlanner().CreatePlan(
            Create(name, path: path, memoryMaxMb: memoryMaxMb, memoryMinMb: memoryMinMb, jvmArgs: jvmArgs),
            target,
            javaPath);
}
