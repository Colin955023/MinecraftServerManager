using System.Collections.Concurrent;
using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.Infrastructure.Utilities;

public static class AtomicFileWriter
{
    private static readonly ConcurrentDictionary<string, object> PathLocks = new(StringComparer.OrdinalIgnoreCase);

    public static bool WriteBytes(string filePath, ReadOnlySpan<byte> content, bool skipIfUnchanged = false)
    {
        string target;
        try
        {
            target = SafeFileSystem.ResolveStablePath(filePath, createParent: true);
        }
        catch (IOException)
        {
            return false;
        }
        catch (UnauthorizedAccessException)
        {
            return false;
        }

        lock (PathLocks.GetOrAdd(target, static _ => new object()))
        {
            if (skipIfUnchanged && File.Exists(target))
            {
                byte[]? existing = FileSafety.ReadRegularFile(target, content.Length);
                if (existing is not null && existing.AsSpan().SequenceEqual(content))
                {
                    return true;
                }
            }

            string temporary = target + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                SafeFileSystem.ResolveStablePath(target, createParent: true);
                using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None, 64 * 1024, FileOptions.WriteThrough))
                {
                    stream.Write(content);
                    stream.Flush(true);
                }

                if (File.Exists(target))
                {
                    File.Move(temporary, target, overwrite: true);
                }
                else
                {
                    File.Move(temporary, target);
                }

                return true;
            }
            catch (IOException)
            {
                return false;
            }
            catch (UnauthorizedAccessException)
            {
                return false;
            }
            finally
            {
                if (File.Exists(temporary))
                {
                    File.Delete(temporary);
                }
            }
        }
    }

    public static bool WriteText(string filePath, string content, bool skipIfUnchanged = false) => WriteBytes(filePath, System.Text.Encoding.UTF8.GetBytes(content), skipIfUnchanged);

    public static bool WriteJson(string filePath, object? value, bool indented = true, bool skipIfUnchanged = false)
    {
        byte[]? payload = JsonCodec.SerializeToUtf8Bytes(value, indented);
        return payload is not null && WriteBytes(filePath, payload, skipIfUnchanged);
    }

    public static bool ReplaceFile(string sourcePath, string targetPath)
    {
        string source;
        string target;
        try
        {
            source = SafeFileSystem.ResolveStablePath(sourcePath);
            target = SafeFileSystem.ResolveStablePath(targetPath, createParent: true);
        }
        catch (IOException)
        {
            return false;
        }
        catch (UnauthorizedAccessException)
        {
            return false;
        }

        if (!File.Exists(source))
        {
            return false;
        }

        try
        {
            File.Move(source, target, overwrite: true);
            return true;
        }
        catch (IOException)
        {
            return false;
        }
        catch (UnauthorizedAccessException)
        {
            return false;
        }
    }

    public static bool ReplaceFileWithin(string baseDirectory, string sourcePath, string targetPath)
    {
        string source;
        string target;
        try
        {
            source = Path.GetFullPath(sourcePath);
            target = Path.GetFullPath(targetPath);
        }
        catch (ArgumentException)
        {
            return false;
        }

        if (string.Equals(source, Path.GetFullPath(baseDirectory), StringComparison.OrdinalIgnoreCase)
            || string.Equals(target, Path.GetFullPath(baseDirectory), StringComparison.OrdinalIgnoreCase)
            || !SafeFileSystem.IsPathWithin(baseDirectory, source)
            || !SafeFileSystem.IsPathWithin(baseDirectory, target, strict: false))
        {
            return false;
        }

        return ReplaceFile(source, target);
    }
}
