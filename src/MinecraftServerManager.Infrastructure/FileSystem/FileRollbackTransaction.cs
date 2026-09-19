using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.FileSystem;

public sealed class FileRollbackTransaction : IDisposable
{
    private readonly string _baseDirectory;
    private readonly string _journalDirectory;
    private readonly List<CapturedFile> _capturedFiles = [];
    private bool _finalized;

    public FileRollbackTransaction(string baseDirectory)
    {
        _baseDirectory = SafeFileSystem.ResolveStableDirectory(baseDirectory);
        _journalDirectory = Path.Combine(_baseDirectory, ".msm-rollback-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_journalDirectory);
        SafeFileSystem.ResolveStableDirectory(_journalDirectory);
    }

    public void ReplaceFile(string sourcePath, string targetPath)
    {
        ThrowIfFinalized();
        string source = RequireChildFile(sourcePath, "替換來源");
        string target = RequireChildPath(targetPath, "替換目標");
        Capture(target);
        if (!AtomicFileWriter.ReplaceFileWithin(_baseDirectory, source, target))
        {
            throw new SafeFileSystemException($"無法替換檔案： {target}");
        }
    }

    public void Rollback()
    {
        ThrowIfFinalized();
        var failures = new List<Exception>();
        for (int index = _capturedFiles.Count - 1; index >= 0; index--)
        {
            var captured = _capturedFiles[index];
            try
            {
                if (captured.ExistedBefore)
                {
                    if (!AtomicFileWriter.ReplaceFile(captured.BackupPath, captured.TargetPath))
                    {
                        throw new SafeFileSystemException($"無法還原檔案： {captured.TargetPath}");
                    }
                }
                else if (File.Exists(captured.TargetPath))
                {
                    string safeTarget = SafeFileSystem.ResolveStablePath(captured.TargetPath);
                    File.Delete(safeTarget);
                }
            }
            catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
            {
                failures.Add(exception);
            }
        }

        if (failures.Count > 0)
        {
            throw new SafeFileSystemException("檔案回滾失敗", new AggregateException(failures));
        }

        CleanupJournal();
        _finalized = true;
    }

    public void Commit()
    {
        ThrowIfFinalized();
        CleanupJournal();
        _finalized = true;
    }

    public void Dispose()
    {
        if (_finalized)
        {
            return;
        }

        Rollback();
    }

    private void Capture(string targetPath)
    {
        if (_capturedFiles.Any(file => string.Equals(file.TargetPath, targetPath, StringComparison.OrdinalIgnoreCase)))
        {
            return;
        }

        bool existedBefore = File.Exists(targetPath);
        string backupPath = Path.Combine(_journalDirectory, _capturedFiles.Count + ".bak");
        if (existedBefore)
        {
            string safeBackupPath = SafeFileSystem.ResolveStablePath(backupPath, createParent: true);
            try
            {
                File.Copy(targetPath, safeBackupPath, overwrite: false);
            }
            catch (IOException exception)
            {
                throw new SafeFileSystemException($"無法建立回滾備份： {targetPath}", exception);
            }
            catch (UnauthorizedAccessException exception)
            {
                throw new SafeFileSystemException($"無法建立回滾備份： {targetPath}", exception);
            }
        }

        _capturedFiles.Add(new CapturedFile(targetPath, backupPath, existedBefore));
    }

    private string RequireChildFile(string path, string description)
    {
        string safePath = RequireChildPath(path, description);
        if (!File.Exists(safePath))
        {
            throw new FileNotFoundException($"找不到{description}", safePath);
        }

        return safePath;
    }

    private string RequireChildPath(string path, string description)
    {
        string fullPath = Path.GetFullPath(path);
        if (string.Equals(fullPath, _baseDirectory, StringComparison.OrdinalIgnoreCase)
            || !SafeFileSystem.IsPathWithin(_baseDirectory, fullPath, strict: false))
        {
            throw new SafeFileSystemException($"{description}必須位於交易根目錄內： {path}");
        }

        return SafeFileSystem.ResolveStablePath(fullPath);
    }

    private void CleanupJournal()
    {
        if (Directory.Exists(_journalDirectory))
        {
            SafeFileSystem.ResolveStableDirectory(_journalDirectory);
            Directory.Delete(_journalDirectory, recursive: true);
        }
    }

    private void ThrowIfFinalized()
    {
        if (_finalized)
        {
            throw new InvalidOperationException("檔案回滾交易已結束");
        }
    }

    private sealed record CapturedFile(string TargetPath, string BackupPath, bool ExistedBefore);
}
