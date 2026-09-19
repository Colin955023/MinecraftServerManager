using System.Diagnostics;
using System.Text;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Process;

public sealed class ProcessRunner : IProcessRunner, IExternalLauncher
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("ProcessRunner");

    public bool OpenFolder(string folderPath)
    {
        if (string.IsNullOrWhiteSpace(folderPath) || !Directory.Exists(folderPath))
        {
            Logger.Warning("開啟資料夾失敗，路徑不存在或為空: {Path}", folderPath);
            return false;
        }

        try
        {
            using var process = System.Diagnostics.Process.Start(new ProcessStartInfo
            {
                FileName = folderPath,
                UseShellExecute = true,
            });
            Logger.Information("已開啟資料夾: {Path}", folderPath);
            return true;
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "開啟資料夾異常: {Path}", folderPath);
            return false;
        }
    }

    public bool OpenUrl(string url)
    {
        if (string.IsNullOrWhiteSpace(url) || !Uri.TryCreate(url, UriKind.Absolute, out var uri))
        {
            Logger.Warning("開啟網址失敗，無效的 URL: {Url}", url);
            return false;
        }

        if (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps)
        {
            Logger.Warning("開啟網址被拒絕，非 HTTP/HTTPS 協議: {Url}", url);
            return false;
        }

        try
        {
            using var process = System.Diagnostics.Process.Start(new ProcessStartInfo
            {
                FileName = url,
                UseShellExecute = true,
            });
            Logger.Information("已開啟網址: {Url}", url);
            return true;
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "開啟網址異常: {Url}", url);
            return false;
        }
    }

    public Task<IManagedProcess> StartAsync(
        ProcessStartSpec specification,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(specification);
        cancellationToken.ThrowIfCancellationRequested();
        string resolvedFileName = ResolveAndValidateExecutable(specification);

        Logger.Information("準備啟動子程序: {FileName} (工作目錄: {WorkingDirectory})", resolvedFileName, specification.WorkingDirectory);

        var startInfo = new ProcessStartInfo
        {
            FileName = resolvedFileName,
            WorkingDirectory = specification.WorkingDirectory ?? Environment.CurrentDirectory,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };
        foreach (string argument in specification.Arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        if (specification.Environment is not null)
        {
            foreach (var (key, value) in specification.Environment)
            {
                if (string.IsNullOrWhiteSpace(key))
                {
                    throw new ArgumentException("環境變數名稱不得為空", nameof(specification));
                }

                if (value is null)
                {
                    startInfo.Environment.Remove(key);
                }
                else
                {
                    startInfo.Environment[key] = value;
                }
            }
        }

        var process = new System.Diagnostics.Process { StartInfo = startInfo };
        try
        {
            if (!process.Start())
            {
                Logger.Error("無法啟動子程序: {FileName}", resolvedFileName);
                throw new InvalidOperationException("無法啟動子程序");
            }

            Logger.Information("子程序啟動成功，PID: {Pid} ({FileName})", process.Id, resolvedFileName);
            return Task.FromResult<IManagedProcess>(new ManagedProcess(process));
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "啟動子程序失敗: {FileName}", resolvedFileName);
            process.Dispose();
            throw;
        }
    }

    private static string ResolveAndValidateExecutable(ProcessStartSpec specification)
    {
        if (string.IsNullOrWhiteSpace(specification.FileName))
        {
            throw new ArgumentException("執行檔名稱不得為空", nameof(specification));
        }

        string fileName = specification.FileName;

        if (specification.WorkingDirectory is not null && !Directory.Exists(specification.WorkingDirectory))
        {
            throw new DirectoryNotFoundException($"找不到工作目錄：{specification.WorkingDirectory}");
        }

        if (Path.IsPathRooted(fileName) || fileName.Contains(Path.DirectorySeparatorChar) || fileName.Contains(Path.AltDirectorySeparatorChar))
        {
            string basePath = specification.WorkingDirectory ?? Environment.CurrentDirectory;
            string fullPath = Path.GetFullPath(fileName, basePath);
            if (!File.Exists(fullPath))
            {
                throw new FileNotFoundException("找不到指定的執行檔", fileName);
            }

            if (SafeFileSystem.IsReparsePoint(fullPath) && !IsTrustedWindowsAppAlias(fullPath))
            {
                throw new SafeFileSystemException($"執行檔路徑不可為不可信任的 reparse point：{fileName}");
            }

            return fullPath;
        }

        // 純檔名搜尋，若為 winget 則額外檢查 WindowsApps 目錄
        if (string.Equals(fileName, "winget", StringComparison.OrdinalIgnoreCase) ||
            string.Equals(fileName, "winget.exe", StringComparison.OrdinalIgnoreCase))
        {
            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            if (!string.IsNullOrEmpty(localAppData))
            {
                string wingetDefault = Path.Combine(localAppData, "Microsoft", "WindowsApps", "winget.exe");
                if (File.Exists(wingetDefault))
                {
                    return wingetDefault;
                }
            }
        }

        return fileName;
    }

    private static bool IsTrustedWindowsAppAlias(string filePath)
    {
        string name = Path.GetFileName(filePath);
        if (!string.Equals(name, "winget.exe", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (string.IsNullOrEmpty(localAppData))
        {
            return false;
        }

        string expectedParent = Path.Combine(localAppData, "Microsoft", "WindowsApps");
        string? actualParent = Path.GetDirectoryName(filePath);
        return string.Equals(expectedParent, actualParent, StringComparison.OrdinalIgnoreCase);
    }

    private sealed class ManagedProcess : IManagedProcess
    {
        private const int MaxPendingOutputLines = 256;

        private readonly System.Diagnostics.Process _process;
        private readonly Task _standardOutputTask;
        private readonly Task _standardErrorTask;
        private readonly object _outputLock = new();
        private readonly Queue<ProcessOutput> _pendingOutput = new();
        private bool _wasForceStopped;
        private bool _disposed;
        private Action<ProcessOutput>? _outputReceived;

        public ManagedProcess(System.Diagnostics.Process process)
        {
            _process = process;
            _standardOutputTask = PumpAsync(_process.StandardOutput, ProcessOutputKind.StandardOutput);
            _standardErrorTask = PumpAsync(_process.StandardError, ProcessOutputKind.StandardError);
        }

        public int Pid => _process.Id;

        public bool HasExited => _process.HasExited;

        public int? ExitCode => HasExited ? _process.ExitCode : null;

        public event Action<ProcessOutput>? OutputReceived
        {
            add
            {
                ArgumentNullException.ThrowIfNull(value);
                lock (_outputLock)
                {
                    _outputReceived += value;
                    while (_pendingOutput.TryDequeue(out var output))
                    {
                        value(output);
                    }
                }
            }
            remove
            {
                lock (_outputLock)
                {
                    _outputReceived -= value;
                }
            }
        }

        public async Task WriteLineAsync(string line, CancellationToken cancellationToken = default)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            ArgumentNullException.ThrowIfNull(line);
            cancellationToken.ThrowIfCancellationRequested();
            await _process.StandardInput.WriteLineAsync(line).WaitAsync(cancellationToken).ConfigureAwait(false);
            await _process.StandardInput.FlushAsync(cancellationToken).ConfigureAwait(false);
        }

        public async Task<ProcessExitResult> WaitForExitAsync(CancellationToken cancellationToken = default)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            await _process.WaitForExitAsync(cancellationToken).ConfigureAwait(false);
            await Task.WhenAll(_standardOutputTask, _standardErrorTask).ConfigureAwait(false);
            Logger.Information("子程序 (PID: {Pid}) 結束，結束代碼: {ExitCode}, 強制終止: {WasForceStopped}", _process.Id, _process.ExitCode, _wasForceStopped);
            return new(_process.ExitCode, _wasForceStopped);
        }

        public async Task<ProcessExitResult> StopAsync(
            TimeSpan gracefulTimeout,
            CancellationToken cancellationToken = default)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            ArgumentOutOfRangeException.ThrowIfLessThan(gracefulTimeout, TimeSpan.Zero);
            if (!HasExited)
            {
                Logger.Information("正在請求子程序 (PID: {Pid}) 關閉主視窗，等候逾時: {Timeout}", _process.Id, gracefulTimeout);
                _process.CloseMainWindow();
                using var timeout = new CancellationTokenSource(gracefulTimeout);
                using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, timeout.Token);
                try
                {
                    return await WaitForExitAsync(linked.Token).ConfigureAwait(false);
                }
                catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
                {
                    _wasForceStopped = true;
                    Logger.Warning("子程序 (PID: {Pid}) 未在預期時間內結束，執行強制中斷程序樹", _process.Id);
                    _process.Kill(entireProcessTree: true);
                }
            }

            return await WaitForExitAsync(cancellationToken).ConfigureAwait(false);
        }

        public async ValueTask DisposeAsync()
        {
            if (_disposed)
            {
                return;
            }

            _disposed = true;
            if (!_process.HasExited)
            {
                _wasForceStopped = true;
                _process.Kill(entireProcessTree: true);
            }

            await _process.WaitForExitAsync().ConfigureAwait(false);
            await Task.WhenAll(_standardOutputTask, _standardErrorTask).ConfigureAwait(false);
            _process.Dispose();
        }

        private async Task PumpAsync(StreamReader reader, ProcessOutputKind kind)
        {
            while (await reader.ReadLineAsync().ConfigureAwait(false) is { } line)
            {
                var output = new ProcessOutput(kind, line);
                Action<ProcessOutput>? handler;
                lock (_outputLock)
                {
                    handler = _outputReceived;
                    if (handler is null)
                    {
                        _pendingOutput.Enqueue(output);
                        while (_pendingOutput.Count > MaxPendingOutputLines)
                        {
                            _pendingOutput.Dequeue();
                        }
                    }
                }

                handler?.Invoke(output);
            }
        }
    }
}
