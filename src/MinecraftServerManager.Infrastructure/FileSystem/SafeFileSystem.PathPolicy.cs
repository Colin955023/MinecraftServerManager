namespace MinecraftServerManager.Infrastructure.FileSystem;

public static partial class SafeFileSystem
{
    public static bool IsReparsePoint(string path)
    {
        try
        {
            // 不存在的路徑回傳 -1 而不擲例外
            FileAttributes attributes = new FileInfo(GetFullPath(path)).Attributes;
            return attributes != (FileAttributes)(-1) && (attributes & FileAttributes.ReparsePoint) != 0;
        }
        catch (Exception ex) when (ex is FileNotFoundException or DirectoryNotFoundException)
        {
            return false;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            // 無法讀取屬性時視為 reparse point（失敗即拒絕）
            return true;
        }
    }

    /// <summary>確實讀到 reparse point 屬性才回傳 true；讀取失敗回傳 false（與 <see cref="IsReparsePoint"/> 的失敗即拒絕相反）</summary>
    public static bool IsConfirmedReparsePoint(string path)
    {
        try
        {
            return (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or ArgumentException)
        {
            return false;
        }
    }

    /// <summary>在已驗證之基準目錄下解析目標路徑並確認邊界與 reparse point 安全</summary>
    internal static bool TryResolveWithinBase(
        string resolvedBaseDir,
        string targetPath,
        bool strict,
        out string resolvedTarget)
    {
        resolvedTarget = string.Empty;
        try
        {
            string target = GetFullPath(targetPath);
            if (!IsSameOrDescendant(resolvedBaseDir, target))
            {
                return false;
            }

            if (strict && !Path.Exists(target))
            {
                return false;
            }

            string? existingParent = Path.Exists(target)
                ? target
                : Path.GetDirectoryName(target);
            if (existingParent is null)
            {
                return false;
            }

            EnsureNoReparseAlongPath(existingParent, resolvedBaseDir);
            resolvedTarget = target;
            return true;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return false;
        }
    }

    public static bool IsPathWithin(string baseDirectory, string targetPath, bool strict = true)
    {
        try
        {
            string basePath = ResolveStableDirectory(baseDirectory);
            return TryResolveWithinBase(basePath, targetPath, strict, out _);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return false;
        }
    }

    private static bool IsSameOrDescendant(string root, string candidate)
    {
        string relative = Path.GetRelativePath(root, candidate);
        return relative == "." ||
            (!Path.IsPathFullyQualified(relative) &&
             !relative.Equals("..", StringComparison.Ordinal) &&
             !relative.StartsWith(".." + Path.DirectorySeparatorChar, StringComparison.Ordinal));
    }

    private static void EnsureNoReparseAlongPath(string path, string? stopBoundary = null)
    {
        string? boundary = string.IsNullOrEmpty(stopBoundary) ? null : GetFullPath(stopBoundary);
        var current = new DirectoryInfo(GetFullPath(path));
        while (current is not null)
        {
            if (boundary is not null && string.Equals(current.FullName, boundary, StringComparison.OrdinalIgnoreCase))
            {
                break;
            }

            if (current.Parent is null)
            {
                break;
            }

            if (IsExistingReparsePoint(current))
            {
                throw new SafeFileSystemException($"路徑不可包含 reparse point： {current.FullName}");
            }

            current = current.Parent;
        }
    }

    /// <summary>既有目錄是否為 reparse point</summary>
    private static bool IsExistingReparsePoint(DirectoryInfo directory)
    {
        try
        {
            FileAttributes attributes = directory.Attributes;
            return attributes != (FileAttributes)(-1) && (attributes & FileAttributes.ReparsePoint) != 0;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return directory.Exists && IsReparsePoint(directory.FullName);
        }
    }

    internal static void EnsureNotReparsePoint(string path)
    {
        if (IsReparsePoint(path))
        {
            throw new SafeFileSystemException($"路徑不可為 reparse point： {path}");
        }
    }

    private static string GetFullPath(string path)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        return Path.GetFullPath(path);
    }
}
