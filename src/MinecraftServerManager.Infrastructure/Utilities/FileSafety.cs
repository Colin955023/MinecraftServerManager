namespace MinecraftServerManager.Infrastructure.Utilities;

internal static class FileSafety
{
    public static byte[]? ReadRegularFile(string filePath, long maxBytes)
    {
        string? safePath = ResolveSafePath(filePath, createParent: false);
        if (safePath is null || !File.Exists(safePath) || IsReparsePoint(safePath))
        {
            return null;
        }

        var info = new FileInfo(safePath);
        if (info.Length > maxBytes)
        {
            return null;
        }

        using var stream = new FileStream(safePath, FileMode.Open, FileAccess.Read, FileShare.Read, 64 * 1024, FileOptions.SequentialScan);
        if (stream.Length > maxBytes)
        {
            return null;
        }

        if (stream.Length > int.MaxValue)
        {
            return null;
        }

        byte[] buffer = new byte[(int)stream.Length];
        int offset = 0;
        while (offset < buffer.Length)
        {
            int read = stream.Read(buffer, offset, buffer.Length - offset);
            if (read == 0)
            {
                return null;
            }

            offset += read;
        }

        return buffer;
    }

    public static string? ResolveSafePath(string filePath, bool createParent)
    {
        if (string.IsNullOrWhiteSpace(filePath))
        {
            return null;
        }

        string fullPath = Path.GetFullPath(filePath);
        string? parent = Directory.GetParent(fullPath)?.FullName;
        if (parent is null)
        {
            return null;
        }

        if (createParent)
        {
            Directory.CreateDirectory(parent);
        }

        return IsSafeDirectory(parent) ? fullPath : null;
    }

    public static bool IsReparsePoint(string path)
    {
        try
        {
            return (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0;
        }
        catch (FileNotFoundException)
        {
            return false;
        }
        catch (DirectoryNotFoundException)
        {
            return false;
        }
    }

    public static bool IsSafeDirectory(string path)
    {
        var current = new DirectoryInfo(Path.GetFullPath(path));
        while (current is not null)
        {
            if (current.Exists && IsReparsePoint(current.FullName))
            {
                return false;
            }

            current = current.Parent;
        }

        return true;
    }
}
