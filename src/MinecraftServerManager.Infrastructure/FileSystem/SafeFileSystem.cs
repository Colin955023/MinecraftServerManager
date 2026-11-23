using System.Text;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.FileSystem;

public sealed record FileSystemEntry(
    string FullPath,
    bool IsDirectory,
    long Length,
    DateTime LastWriteTimeUtc = default,
    DateTime CreationTimeUtc = default);

public sealed record FileSystemMetadata(
    string FullPath,
    string Name,
    long Length,
    DateTime LastWriteTimeUtc,
    DateTime CreationTimeUtc,
    FileAttributes Attributes);

public static partial class SafeFileSystem
{
    public const int DefaultMaxEntries = 100_000;
    public const long DefaultMaxTotalBytes = 128L * 1024 * 1024 * 1024;

    // 剛解壓或寫入的檔案常被防毒或索引短暫開啟，稍候重試即可成功；存取遭拒多半為永久 ACL，只短暫重試
    private const int TransientMoveMaxAttempts = 8;
    private const int AccessDeniedMoveMaxAttempts = 3;
    private const int ErrorAccessDenied = 5;
    private static readonly TimeSpan TransientMoveBaseDelay = TimeSpan.FromMilliseconds(150);

    private static readonly Encoding DefaultUtf8Encoding = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);
    private static readonly byte[] Utf8Preamble = [0xEF, 0xBB, 0xBF];

    // 與 DirectoryInfo 預設列舉一致：含隱藏／系統項目，無法存取時擲出
    private static readonly EnumerationOptions FlatEnumerationOptions = new() { AttributesToSkip = 0, IgnoreInaccessible = false, ReturnSpecialDirectories = false };
    private static readonly EnumerationOptions TreeEnumerationOptions = new() { RecurseSubdirectories = true, AttributesToSkip = 0, IgnoreInaccessible = false, ReturnSpecialDirectories = false };

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(SafeFileSystem));

    public static string ResolveStableDirectory(string path, bool create = false)
    {
        string fullPath = GetFullPath(path);
        if (create)
        {
            // 建立前先檢查，避免透過既有 junction 在邊界外建立目錄
            EnsureNoReparseAlongPath(fullPath);
            Directory.CreateDirectory(fullPath);
        }

        if (!Directory.Exists(fullPath))
        {
            throw new DirectoryNotFoundException(fullPath);
        }

        EnsureNoReparseAlongPath(fullPath);
        return fullPath;
    }

    public static string ResolveStablePath(string path, bool createParent = false)
    {
        string fullPath = GetFullPath(path);
        if (Path.GetDirectoryName(fullPath) is not { } parent)
        {
            // 路徑本身即根目錄（磁碟機根或 UNC 共用根）：沒有父資料夾，直接驗證根目錄存在
            return ResolveStableDirectory(fullPath);
        }

        ResolveStableDirectory(parent, createParent);
        EnsureNotReparsePoint(fullPath);
        return fullPath;
    }

    /// <summary>驗證一般檔案路徑後檢查檔案是否存在</summary>
    public static bool FileExists(string path)
    {
        try
        {
            return File.Exists(ResolveStablePath(path));
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or ArgumentException)
        {
            return false;
        }
    }

    /// <summary>驗證目錄路徑後檢查目錄是否存在</summary>
    public static bool DirectoryExists(string path)
    {
        try
        {
            return Directory.Exists(ResolveStablePath(path));
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or ArgumentException)
        {
            return false;
        }
    }

    /// <summary>建立經過路徑穩定性檢查的目錄</summary>
    public static string CreateDirectory(string path) => ResolveStableDirectory(path, create: true);
}
