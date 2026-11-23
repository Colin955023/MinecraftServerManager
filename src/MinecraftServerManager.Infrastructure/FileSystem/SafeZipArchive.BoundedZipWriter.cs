using System.Buffers;
using System.IO.Compression;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.FileSystem;

public static partial class SafeZipArchive
{
    public sealed class BoundedZipWriter : IDisposable
    {
        private readonly string _targetPath;
        private readonly string _temporaryPath;
        private readonly FileStream _stream;
        private readonly ZipArchive _archive;
        private readonly int _maxMembers;
        private readonly long _maxTotalBytes;
        private readonly long _maxMemberBytes;
        private readonly PathCollisionTracker _collisions = new();
        private long _totalBytes;
        private bool _archiveClosed;
        private bool _completed;
        private bool _disposed;

        internal BoundedZipWriter(string targetPath, int maxMembers, long maxTotalBytes, long maxMemberBytes)
        {
            ArgumentOutOfRangeException.ThrowIfNegative(maxMembers);
            _targetPath = SafeFileSystem.ResolveStablePath(targetPath, createParent: true);
            _temporaryPath = AtomicFileWriter.CreateTempSiblingPath(_targetPath);
            _maxMembers = maxMembers;
            _maxTotalBytes = maxTotalBytes;
            _maxMemberBytes = maxMemberBytes;
            FileStream? stream = null;
            try
            {
                stream = new FileStream(
                    _temporaryPath,
                    FileMode.CreateNew,
                    FileAccess.ReadWrite,
                    FileShare.None,
                    1024 * 1024,
                    FileOptions.None);
                _archive = new ZipArchive(stream, ZipArchiveMode.Create, leaveOpen: true);
                _stream = stream;
            }
            catch (Exception)
            {
                // 建構失敗不會呼叫 Dispose：自行釋放串流並清除暫存檔
                stream?.Dispose();
                SafeFileSystem.TryDeleteFile(_temporaryPath);
                throw;
            }
        }

        public void SetComment(string comment)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            _archive.Comment = comment;
        }

        public long WriteFile(string memberName, string sourcePath)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            ThrowIfCompleted();
            // 單次開啟：以同一串流取得長度並讀取，避免檢查後檔案被替換
            using var input = SafeFileSystem.OpenRead(sourcePath, FileShare.Read);
            string source = input.Name;
            long fileLength = input.Length;
            string normalized = PrepareMember(memberName, fileLength);
            // ZIP 規範要求成員名稱以 '/' 分隔，其他解壓工具才能正確還原目錄結構
            var entry = _archive.CreateEntry(normalized.Replace(Path.DirectorySeparatorChar, '/'), CompressionLevel.Fastest);
            using var output = entry.Open();
            byte[] buffer = ArrayPool<byte>.Shared.Rent(81920);
            long copied = 0L;
            try
            {
                while (copied < fileLength)
                {
                    long remaining = fileLength - copied;
                    int requested = (int)Math.Min(buffer.Length, remaining + 1);
                    int read = input.Read(buffer, 0, requested);
                    if (read == 0)
                    {
                        break;
                    }

                    copied += read;
                    if (copied > fileLength)
                    {
                        throw new SafeArchiveException($"壓縮來源檔案在讀取期間成長： {source}");
                    }

                    output.Write(buffer, 0, read);
                }

                if (copied != fileLength)
                {
                    throw new SafeArchiveException($"壓縮來源檔案在讀取期間縮短： {source}");
                }

                // 確認已達 EOF（涵蓋 0 位元組檔案於讀取期間成長）
                if (input.ReadByte() != -1)
                {
                    throw new SafeArchiveException($"壓縮來源檔案在讀取期間成長： {source}");
                }
            }
            finally
            {
                ArrayPool<byte>.Shared.Return(buffer);
            }

            return copied;
        }

        public void Complete()
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            ThrowIfCompleted();
            if (_archiveClosed)
            {
                throw new InvalidOperationException("ZIP 寫入器已關閉，無法再次完成");
            }

            CloseArchive(flushToDisk: true);
            if (!AtomicFileWriter.ReplaceFile(_temporaryPath, _targetPath))
            {
                throw new SafeArchiveException($"無法完成 ZIP 原子替換： {_targetPath}");
            }

            _completed = true;
        }

        public void Dispose()
        {
            if (_disposed)
            {
                return;
            }

            _disposed = true;
            if (!_completed)
            {
                CloseArchive(flushToDisk: false);
                SafeFileSystem.TryDeleteFile(_temporaryPath);
            }
        }

        private void ThrowIfCompleted()
        {
            if (_completed)
            {
                throw new InvalidOperationException("ZIP 寫入器已完成");
            }
        }

        /// <summary>只關閉一次封存與串流，避免重複處置</summary>
        private void CloseArchive(bool flushToDisk)
        {
            if (_archiveClosed)
            {
                return;
            }

            _archiveClosed = true;
            try
            {
                _archive.Dispose();
                if (flushToDisk)
                {
                    _stream.Flush(true);
                }
            }
            finally
            {
                _stream.Dispose();
            }
        }

        private string PrepareMember(string memberName, long size)
        {
            if (size < 0 || size > _maxMemberBytes)
            {
                throw new SafeArchiveException($"壓縮檔成員過大： {memberName}");
            }

            if (_collisions.Count >= _maxMembers || _totalBytes > _maxTotalBytes - size)
            {
                throw new SafeArchiveException("壓縮檔輸出超過安全上限");
            }

            string normalized = SanitizeMemberName(memberName);
            _collisions.Add(normalized, isDirectory: false, memberName);
            _totalBytes += size;
            return normalized;
        }
    }

    private sealed record PreparedMember(ZipArchiveEntry Entry, string RelativePath);
}
