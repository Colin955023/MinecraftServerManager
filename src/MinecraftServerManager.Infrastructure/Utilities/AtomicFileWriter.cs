using Microsoft.Win32.SafeHandles;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Utilities;

/// <summary>關鍵檔案原子寫入：先寫入同目錄暫存檔並寫入磁碟，再以 Replace／Move 一次替換目標</summary>
public static class AtomicFileWriter
{
    /// <summary>原子寫入暫存檔副檔名</summary>
    public const string TempFileExtension = ".tmp";

    /// <summary>產生與目標同目錄、不可預測之暫存檔路徑（target.{guid}.tmp），供原子替換使用</summary>
    public static string CreateTempSiblingPath(string targetPath) =>
        $"{targetPath}.{Guid.NewGuid():N}{TempFileExtension}";

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(AtomicFileWriter));

    private const int StripeCount = 128;
    private static readonly Lock[] StripeLocks = [.. Enumerable.Range(0, StripeCount).Select(static _ => new Lock())];

    private static Lock GetLockForPath(string path)
    {
        uint hash = (uint)StringComparer.OrdinalIgnoreCase.GetHashCode(path);
        return StripeLocks[hash % StripeCount];
    }

    public static bool WriteBytes(string filePath, ReadOnlySpan<byte> content, bool skipIfUnchanged = false)
    {
        if (TryResolveTarget(filePath) is not { } target)
        {
            return false;
        }

        lock (GetLockForPath(target))
        {
            if (skipIfUnchanged && IsUnchanged(target, content))
            {
                return true;
            }

            string temporary = CreateTempSiblingPath(target);
            try
            {
                using (SafeFileHandle handle = File.OpenHandle(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None, FileOptions.None, content.Length))
                {
                    RandomAccess.Write(handle, content, fileOffset: 0);
                    RandomAccess.FlushToDisk(handle);
                }

                CommitReplace(temporary, target);
                return true;
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                Logger.Warning(ex, "原子寫入失敗: {Path}", target);
                return false;
            }
            finally
            {
                SafeFileSystem.TryDeleteFile(temporary);
            }
        }
    }

    public static async Task<bool> WriteBytesAsync(
        string filePath,
        ReadOnlyMemory<byte> content,
        bool skipIfUnchanged = false,
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (TryResolveTarget(filePath) is not { } target)
        {
            return false;
        }

        if (skipIfUnchanged && IsUnchanged(target, content.Span))
        {
            return true;
        }

        string temporary = CreateTempSiblingPath(target);
        try
        {
            using (SafeFileHandle handle = File.OpenHandle(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None, FileOptions.Asynchronous, content.Length))
            {
                await RandomAccess.WriteAsync(handle, content, fileOffset: 0, cancellationToken).ConfigureAwait(false);
                RandomAccess.FlushToDisk(handle);
            }

            lock (GetLockForPath(target))
            {
                CommitReplace(temporary, target);
            }

            return true;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Warning(ex, "原子寫入失敗: {Path}", target);
            return false;
        }
        finally
        {
            SafeFileSystem.TryDeleteFile(temporary);
        }
    }

    public static bool WriteText(string filePath, string content, bool skipIfUnchanged = false) => WriteBytes(filePath, System.Text.Encoding.UTF8.GetBytes(content), skipIfUnchanged);

    public static bool WriteJson<T>(string filePath, T? value, bool indented = true, bool skipIfUnchanged = false)
    {
        byte[]? payload = JsonCodec.SerializeToUtf8Bytes(value, indented);
        return payload is not null && WriteBytes(filePath, payload, skipIfUnchanged);
    }

    /// <summary>寫入失敗時擲出 <see cref="IOException"/>；供不可靜默失敗的關鍵檔案（登錄檔、啟動腳本、初始設定）使用</summary>
    public static void WriteTextOrThrow(string filePath, string content)
    {
        if (!WriteText(filePath, content))
        {
            throw new IOException($"無法寫入檔案：{filePath}");
        }
    }

    /// <summary>寫入失敗時擲出 <see cref="IOException"/>；供不可靜默失敗的關鍵檔案使用</summary>
    public static void WriteJsonOrThrow<T>(string filePath, T? value, bool indented = true)
    {
        if (!WriteJson(filePath, value, indented))
        {
            throw new IOException($"無法寫入檔案：{filePath}");
        }
    }

    public static bool ReplaceFile(string sourcePath, string targetPath)
    {
        try
        {
            string source = SafeFileSystem.ResolveStablePath(sourcePath);
            string target = SafeFileSystem.ResolveStablePath(targetPath, createParent: true);
            if (!File.Exists(source))
            {
                return false;
            }

            CommitReplace(source, target);
            return true;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Warning(ex, "原子替換失敗: {SourcePath} -> {TargetPath}", sourcePath, targetPath);
            return false;
        }
    }

    private static string? TryResolveTarget(string filePath)
    {
        try
        {
            return SafeFileSystem.ResolveStablePath(filePath, createParent: true);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return null;
        }
    }

    private static bool IsUnchanged(string target, ReadOnlySpan<byte> content) =>
        SafeFileSystem.FileExists(target) && SafeFileSystem.ReadRegularFile(target) is { } existing && existing.AsSpan().SequenceEqual(content);

    private static void CommitReplace(string source, string target)
    {
        if (File.Exists(target))
        {
            File.Replace(source, target, null);
        }
        else
        {
            File.Move(source, target);
        }
    }
}
