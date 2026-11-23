using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>載入器檔案配置之實體路徑組合（Domain 不接觸檔案系統）</summary>
internal static class LoaderLayoutPaths
{
    /// <summary>組出伺服器目錄下此載入器的函式庫目錄；無函式庫配置時為 libraries 根目錄</summary>
    internal static string GetLibraryDirectory(this LoaderLayout layout, string serverDirectory) =>
        Path.Combine([serverDirectory, ServerDefaults.LibrariesDirectoryName, .. layout.LibrarySegments]);
}
