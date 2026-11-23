using System.Buffers;
using System.IO.Compression;
using MinecraftServerManager.Domain.ValueObjects;

namespace MinecraftServerManager.Infrastructure.FileSystem;

public static partial class SafeZipArchive
{
    // Unix 檔案類型位元：一般檔案與目錄以外（符號連結、裝置、FIFO、socket）一律拒絕
    private const int UnixFileTypeMask = 0xF000;
    private const int UnixRegularFile = 0x8000;
    private const int UnixDirectory = 0x4000;

    // Windows 檔名非法字元與控制字元
    private static readonly SearchValues<char> InvalidMemberChars = SearchValues.Create(
        "<>:\"|?*\0\u0001\u0002\u0003\u0004\u0005\u0006\u0007\b\t\n\u000B\f\r\u000E\u000F" +
        "\u0010\u0011\u0012\u0013\u0014\u0015\u0016\u0017\u0018\u0019\u001A\u001B\u001C\u001D\u001E\u001F");

    private static void ValidateEntry(ZipArchiveEntry entry)
    {
        if (IsLinkOrSpecialNode(entry))
        {
            throw new SafeArchiveException($"壓縮檔包含不支援的符號連結或特殊檔案： {entry.FullName}");
        }

        if (entry.Length < 0 || entry.CompressedLength < 0)
        {
            throw new SafeArchiveException($"壓縮檔成員大小資訊無效： {entry.FullName}");
        }

        if (entry.Length > 0 && (entry.FullName.EndsWith('/') || entry.FullName.EndsWith('\\')))
        {
            throw new SafeArchiveException($"壓縮檔目錄成員不可含資料： {entry.FullName}");
        }

        if (entry.Length > DefaultMaxMemberBytes)
        {
            throw new SafeArchiveException($"壓縮檔成員過大： {entry.FullName}");
        }

        if (entry.Length > 0 && entry.CompressedLength <= 0)
        {
            throw new SafeArchiveException($"壓縮檔成員大小資訊無效： {entry.FullName}");
        }

        // 小檔的高壓縮比無害（如其他工具壓出的全零 region 檔可達 300 以上），只對大型成員把關
        if (entry.Length > RatioCheckMinMemberBytes && entry.Length / (double)entry.CompressedLength > DefaultMaxCompressionRatio)
        {
            throw new SafeArchiveException($"壓縮檔成員壓縮比例過高： {entry.FullName}");
        }
    }

    private static string SanitizeMemberName(string memberName)
    {
        if (string.IsNullOrEmpty(memberName))
        {
            throw new SafeArchiveException($"壓縮檔包含不安全的成員名稱： {memberName}");
        }

        ReadOnlySpan<char> span = memberName.AsSpan();
        if (span[0] is '/' or '\\' || span.Contains(':'))
        {
            throw new SafeArchiveException($"壓縮檔包含不安全的成員名稱： {memberName}");
        }

        ReadOnlySpan<char> trimmed = span.TrimEnd("/\\");
        if (trimmed.IsEmpty || Path.IsPathRooted(trimmed))
        {
            throw new SafeArchiveException($"壓縮檔包含不安全的成員名稱： {memberName}");
        }

        foreach (Range range in trimmed.SplitAny("/\\"))
        {
            ReadOnlySpan<char> part = trimmed[range];
            if (part.IsEmpty ||
                part is "." or ".." ||
                part[^1] is '.' or ' ' ||
                part.ContainsAny(InvalidMemberChars) ||
                ServerName.IsWindowsDeviceName(part))
            {
                throw new SafeArchiveException($"壓縮檔包含不安全的成員名稱： {memberName}");
            }
        }

        return string.Create(trimmed.Length, trimmed, static (dst, src) =>
        {
            src.CopyTo(dst);
            dst.Replace('/', Path.DirectorySeparatorChar);
            dst.Replace('\\', Path.DirectorySeparatorChar);
        });
    }

    /// <summary>解壓與寫入共用的成員路徑衝突檢查：拒絕重複路徑，以及同一路徑同時作為檔案與目錄</summary>
    private sealed class PathCollisionTracker
    {
        private readonly Dictionary<string, bool> _paths = new(StringComparer.OrdinalIgnoreCase);
        private readonly HashSet<string> _parentPaths = new(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<string, bool>.AlternateLookup<ReadOnlySpan<char>> _pathsLookup;
        private readonly HashSet<string>.AlternateLookup<ReadOnlySpan<char>> _parentLookup;

        public PathCollisionTracker()
        {
            _pathsLookup = _paths.GetAlternateLookup<ReadOnlySpan<char>>();
            _parentLookup = _parentPaths.GetAlternateLookup<ReadOnlySpan<char>>();
        }

        public int Count => _paths.Count;

        /// <summary>登錄已正規化的成員路徑；衝突時擲出</summary>
        public void Add(string relativePath, bool isDirectory, string displayName)
        {
            ReadOnlySpan<char> span = relativePath.AsSpan();
            if (_pathsLookup.TryGetValue(span, out bool existingIsDirectory))
            {
                if (isDirectory && existingIsDirectory)
                {
                    return;
                }

                throw new SafeArchiveException($"壓縮檔包含重複或路徑衝突： {displayName}");
            }

            if (!isDirectory && _parentLookup.Contains(span))
            {
                throw new SafeArchiveException($"壓縮檔包含重複或路徑衝突： {displayName}");
            }

            int separatorIndex = span.IndexOf(Path.DirectorySeparatorChar);
            while (separatorIndex >= 0)
            {
                ReadOnlySpan<char> parentSpan = span[..separatorIndex];
                if (_pathsLookup.TryGetValue(parentSpan, out bool parentIsDirectory) && !parentIsDirectory)
                {
                    throw new SafeArchiveException($"壓縮檔包含檔案／目錄路徑衝突： {displayName}");
                }

                _parentLookup.Add(parentSpan);
                int next = span[(separatorIndex + 1)..].IndexOf(Path.DirectorySeparatorChar);
                separatorIndex = next >= 0 ? separatorIndex + 1 + next : -1;
            }

            _paths[relativePath] = isDirectory;
        }
    }

    /// <summary>是否為符號連結、裝置、FIFO、socket 或帶 Windows reparse point 屬性的成員</summary>
    private static bool IsLinkOrSpecialNode(ZipArchiveEntry entry)
    {
        int unixType = (entry.ExternalAttributes >> 16) & UnixFileTypeMask;
        if (unixType is not (0 or UnixRegularFile or UnixDirectory))
        {
            return true;
        }

        return (entry.ExternalAttributes & (int)FileAttributes.ReparsePoint) != 0;
    }
}
