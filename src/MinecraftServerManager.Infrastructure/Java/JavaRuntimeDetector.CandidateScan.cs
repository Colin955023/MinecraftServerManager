using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.Infrastructure.Java;

public sealed partial class JavaRuntimeDetector
{
    /// <summary>解析系統 PATH 環境變數中的所有有效目錄路徑</summary>
    private List<string> EnumeratePathDirectories()
    {
        string? pathEnv = _sources.GetEnvironmentVariable("PATH");
        if (string.IsNullOrWhiteSpace(pathEnv))
        {
            return [];
        }

        var list = new List<string>();
        foreach (var range in pathEnv.AsSpan().Split(Path.PathSeparator))
        {
            var folderSpan = pathEnv.AsSpan(range).Trim();
            if (!folderSpan.IsEmpty)
            {
                list.Add(folderSpan.ToString());
            }
        }

        return list;
    }

    private HashSet<string> EnumerateCandidates()
    {
        var candidates = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        string? javaHome = _sources.GetEnvironmentVariable("JAVA_HOME");
        if (!string.IsNullOrWhiteSpace(javaHome))
        {
            AddCandidate(candidates, Path.Combine(javaHome, "bin", "java.exe"));
        }

        foreach (string folder in EnumeratePathDirectories())
        {
            AddCandidate(candidates, Path.Combine(folder, "java.exe"));
        }

        foreach (string root in _sources.InstallRoots)
        {
            foreach (string vendor in CommonVendors)
            {
                string vendorRoot = Path.Combine(root, vendor);
                if (!SafeFileSystem.DirectoryExists(vendorRoot))
                {
                    continue;
                }

                IReadOnlyList<FileSystemEntry> entries;
                try
                {
                    // 只取子目錄；單一 reparse 子項不應使整個廠牌目錄被略過，改為逐項跳過
                    entries = SafeFileSystem.ListBoundedDirectory(vendorRoot, maxEntries: MaxJavaDirectoryEntries, rejectReparse: false);
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                {
                    Logger.Warning(ex, "列舉 Java 廠牌目錄失敗: {Path}", vendorRoot);
                    continue;
                }

                AddDirectoryCandidates(candidates, entries);
            }
        }

        // 使用者目錄
        string? userProfile = _sources.UserProfileDirectory;
        if (!string.IsNullOrWhiteSpace(userProfile))
        {
            string jdksDir = Path.Combine(userProfile, ".jdks");
            if (SafeFileSystem.DirectoryExists(jdksDir))
            {
                try
                {
                    AddDirectoryCandidates(candidates, SafeFileSystem.ListBoundedDirectory(jdksDir, maxEntries: MaxJavaDirectoryEntries, rejectReparse: false));
                }
                catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
                {
                    Logger.Warning(ex, "列舉 JDK 目錄失敗: {Path}", jdksDir);
                }
            }
        }

        return candidates;
    }

    private static void AddDirectoryCandidates(HashSet<string> candidates, IReadOnlyList<FileSystemEntry> entries)
    {
        foreach (var entry in entries)
        {
            if (entry.IsDirectory && !SafeFileSystem.IsReparsePoint(entry.FullPath))
            {
                AddCandidate(candidates, Path.Combine(entry.FullPath, "bin", "java.exe"));
            }
        }
    }

    private static void AddCandidate(HashSet<string> candidates, string path)
    {
        if (string.IsNullOrWhiteSpace(path) || !Path.IsPathFullyQualified(path))
        {
            return;
        }

        // FileExists 經穩定路徑檢查，路徑或任一上層為 reparse point 時回傳 false，路徑即為實體檔案
        if (!IsIgnoredJavaPath(path) && SafeFileSystem.FileExists(path) && !IsShimLauncher(path))
        {
            candidates.Add(Path.GetFullPath(path));
        }
    }

    private static bool IsIgnoredJavaPath(string path) =>
        path.Contains(@"\Oracle\Java\javapath", StringComparison.OrdinalIgnoreCase) ||
        path.Contains(@"\Oracle\Java\java8path", StringComparison.OrdinalIgnoreCase) ||
        path.Contains(@"\Common Files\Oracle\Java\", StringComparison.OrdinalIgnoreCase);

    /// <summary>呼叫端須先確認檔案存在</summary>
    private static bool IsShimLauncher(string path)
    {
        try
        {
            var vi = System.Diagnostics.FileVersionInfo.GetVersionInfo(path);
            if (string.Equals(vi.OriginalFilename, "shimconsole.exe", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(vi.OriginalFilename, "shim.exe", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(vi.InternalName, "Shim Console Launcher", StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "檢查 Shim 可執行檔資訊失敗: {Path}", path);
        }

        return false;
    }
}
