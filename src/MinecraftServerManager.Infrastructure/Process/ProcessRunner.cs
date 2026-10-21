using System.Buffers;
using System.Collections.Frozen;
using System.Diagnostics;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Channels;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Process;

public sealed partial class ProcessRunner : IProcessRunner, IExternalLauncher
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("ProcessRunner");

    private static readonly FrozenSet<string> AllowedOpenFileExtensions =
        new[] { ".txt", ".log", ".json", ".toml", ".properties", ".yml", ".yaml", ".ini", ".cfg", ".md", ".csv", ".html", ".htm", ".xlsx", ".xml" }
            .ToFrozenSet(StringComparer.OrdinalIgnoreCase);

    public bool OpenFolder(string folderPath, bool isTrusted = false)
    {
        if (string.IsNullOrWhiteSpace(folderPath) || !Directory.Exists(folderPath))
        {
            Logger.Warning("開啟資料夾失敗，路徑不存在或為空: {Path}", folderPath);
            return false;
        }

        if (TryShellExecute(() => new ProcessStartInfo { FileName = folderPath, UseShellExecute = true }) is { } error)
        {
            Logger.Error(error, "開啟資料夾異常: {Path}", folderPath);
            return false;
        }

        Logger.Information("已開啟資料夾: {Path}", folderPath);
        return true;
    }

    public bool ShowInFolder(string filePath, bool isTrusted = false)
    {
        if (string.IsNullOrWhiteSpace(filePath) || !File.Exists(filePath))
        {
            Logger.Warning("在資料夾中顯示失敗，檔案不存在或為空: {Path}", filePath);
            return false;
        }

        string sanitized = Path.GetFullPath(filePath)
            .Replace("\"", string.Empty)
            .Replace("\r", string.Empty)
            .Replace("\n", string.Empty);

        if (TryShellExecute(() => new ProcessStartInfo
        {
            FileName = "explorer.exe",
            Arguments = $"/select,\"{sanitized}\"",
            UseShellExecute = true,
        }) is { } error)
        {
            Logger.Error(error, "在資料夾中顯示檔案異常: {Path}", filePath);
            return false;
        }

        Logger.Information("已在資料夾中顯示檔案: {Path}", filePath);
        return true;
    }

    public bool OpenFile(string filePath, bool isTrusted = false)
    {
        if (string.IsNullOrWhiteSpace(filePath) || !File.Exists(filePath))
        {
            Logger.Warning("開啟檔案失敗，檔案不存在或為空: {Path}", filePath);
            return false;
        }

        // 若為程式內建或受信任的產出內容，不需判斷是否拒絕開啟
        if (!isTrusted)
        {
            string ext = Path.GetExtension(filePath);
            if (!AllowedOpenFileExtensions.Contains(ext))
            {
                Logger.Warning("拒絕開啟不具備允許副檔名白名單之檔案: {Path}", filePath);
                return false;
            }
        }

        if (TryShellExecute(() => new ProcessStartInfo { FileName = filePath, UseShellExecute = true }) is { } error)
        {
            Logger.Error(error, "開啟檔案異常: {Path}", filePath);
            return false;
        }

        Logger.Information("已開啟檔案: {Path}", filePath);
        return true;
    }

    public bool OpenUrl(string url, bool isTrusted = false)
    {
        if (string.IsNullOrWhiteSpace(url) || !Uri.TryCreate(url, UriKind.Absolute, out var uri))
        {
            Logger.Warning("開啟網址失敗，無效的 URL: {Url}", url);
            return false;
        }

        // 若為程式內建或受信任的連結，不需進行協定拒絕判斷
        if (!isTrusted && uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps)
        {
            Logger.Warning("開啟網址被拒絕，非 HTTP/HTTPS 協定: {Url}", url);
            return false;
        }

        if (TryShellExecute(() => new ProcessStartInfo { FileName = url, UseShellExecute = true }) is { } error)
        {
            Logger.Error(error, "開啟網址異常: {Url}", url);
            return false;
        }

        Logger.Information("已開啟網址: {Url}", url);
        return true;
    }

    /// <summary>
    /// 以殼層方式啟動目標；成功回傳 null，失敗回傳例外供呼叫端記錄
    /// </summary>
    private static Exception? TryShellExecute(Func<ProcessStartInfo> createStartInfo)
    {
        try
        {
            System.Diagnostics.Process.Start(createStartInfo())?.Dispose();
            return null;
        }
        catch (Exception ex)
        {
            return ex;
        }
    }

    public Task<IManagedProcess> StartAsync(
        ProcessStartSpec specification,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(specification);
        cancellationToken.ThrowIfCancellationRequested();
        string resolvedFileName = ResolveAndValidateExecutable(specification);

        Logger.Information("準備啟動子行程: {FileName} (工作目錄: {WorkingDirectory})", resolvedFileName, specification.WorkingDirectory);

        string ext = Path.GetExtension(resolvedFileName);
        bool isBatchScript = ext.Equals(".bat", StringComparison.OrdinalIgnoreCase) ||
                             ext.Equals(".cmd", StringComparison.OrdinalIgnoreCase);

        var startInfo = new ProcessStartInfo
        {
            WorkingDirectory = specification.WorkingDirectory ?? Environment.CurrentDirectory,
            UseShellExecute = specification.UseShellExecute,
            CreateNoWindow = specification.CreateNoWindow,
            RedirectStandardInput = !specification.UseShellExecute,
            RedirectStandardOutput = !specification.UseShellExecute,
            RedirectStandardError = !specification.UseShellExecute,
            StandardOutputEncoding = specification.UseShellExecute ? null : Encoding.UTF8,
            StandardErrorEncoding = specification.UseShellExecute ? null : Encoding.UTF8,
        };

        if (isBatchScript && !specification.UseShellExecute)
        {
            string comSpec = Environment.GetEnvironmentVariable("ComSpec") ??
                             Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "cmd.exe");
            if (!File.Exists(comSpec))
            {
                throw new FileNotFoundException("找不到系統命令解譯器 (cmd.exe)", comSpec);
            }

            startInfo.FileName = comSpec;
            startInfo.ArgumentList.Add("/d");
            startInfo.ArgumentList.Add("/c");
            startInfo.ArgumentList.Add(resolvedFileName);
            foreach (string argument in specification.Arguments)
            {
                startInfo.ArgumentList.Add(argument);
            }
        }
        else
        {
            startInfo.FileName = resolvedFileName;
            foreach (string argument in specification.Arguments)
            {
                startInfo.ArgumentList.Add(argument);
            }
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
                Logger.Error("無法啟動子行程: {FileName}", resolvedFileName);
                throw new InvalidOperationException("無法啟動子行程");
            }

            Logger.Information("子行程啟動成功，PID: {Pid} ({FileName})", process.Id, resolvedFileName);
            return Task.FromResult<IManagedProcess>(new ManagedProcess(process));
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "啟動子行程失敗: {FileName}", resolvedFileName);
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

        string basePath = specification.WorkingDirectory ?? Environment.CurrentDirectory;
        string candidatePath = Path.GetFullPath(fileName, basePath);

        if (Path.IsPathRooted(fileName) ||
            fileName.Contains(Path.DirectorySeparatorChar) ||
            fileName.Contains(Path.AltDirectorySeparatorChar) ||
            File.Exists(candidatePath))
        {
            if (!File.Exists(candidatePath))
            {
                throw new FileNotFoundException("找不到指定的執行檔", fileName);
            }

            if (SafeFileSystem.IsReparsePoint(candidatePath) && !IsTrustedWindowsAppAlias(candidatePath))
            {
                throw new SafeFileSystemException($"執行檔路徑不可為不可信任的 reparse point：{fileName}");
            }

            return candidatePath;
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
        private readonly Channel<ProcessOutput> _outputChannel = Channel.CreateBounded<ProcessOutput>(new BoundedChannelOptions(MaxPendingOutputLines)
        {
            FullMode = BoundedChannelFullMode.DropOldest,
            SingleReader = true,
            SingleWriter = false,
        });
        private readonly Task _standardOutputTask;
        private readonly Task _standardErrorTask;
        private readonly Task _outputDispatchTask;
        private readonly Lock _outputLock = new();
        private readonly Queue<ProcessOutput> _pendingOutput = new();
        private int _exitLogged;
        private bool _wasForceStopped;
        private bool _disposed;
        private Action<ProcessOutput>? _outputReceived;

        public ManagedProcess(System.Diagnostics.Process process)
        {
            _process = process;
            _outputDispatchTask = DispatchOutputAsync();
            _standardOutputTask = process.StartInfo.RedirectStandardOutput
                ? PumpAsync(_process.StandardOutput, ProcessOutputKind.StandardOutput)
                : Task.CompletedTask;
            _standardErrorTask = process.StartInfo.RedirectStandardError
                ? PumpAsync(_process.StandardError, ProcessOutputKind.StandardError)
                : Task.CompletedTask;
        }

        public int Pid => _process.Id;

        public bool HasExited => _process.HasExited;

        public int? ExitCode => HasExited ? _process.ExitCode : null;

        public event Action<ProcessOutput>? OutputReceived
        {
            add
            {
                ArgumentNullException.ThrowIfNull(value);
                List<ProcessOutput>? backlog = null;
                lock (_outputLock)
                {
                    _outputReceived += value;
                    if (_pendingOutput.Count > 0)
                    {
                        backlog = new List<ProcessOutput>(_pendingOutput.Count);
                        while (_pendingOutput.TryDequeue(out var output))
                        {
                            backlog.Add(output);
                        }
                    }
                }

                if (backlog is not null)
                {
                    foreach (var output in backlog)
                    {
                        NotifyOutputReceived(value, output);
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
            if (!_process.StartInfo.RedirectStandardInput)
            {
                return;
            }
            await _process.StandardInput.WriteLineAsync(line.AsMemory(), cancellationToken).ConfigureAwait(false);
            await _process.StandardInput.FlushAsync(cancellationToken).ConfigureAwait(false);
        }

        public async Task<ProcessExitResult> WaitForExitAsync(CancellationToken cancellationToken = default)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            await _process.WaitForExitAsync(cancellationToken).ConfigureAwait(false);
            await Task.WhenAll(_standardOutputTask, _standardErrorTask).ConfigureAwait(false);
            _outputChannel.Writer.TryComplete();
            await _outputDispatchTask.ConfigureAwait(false);
            if (Interlocked.Exchange(ref _exitLogged, 1) == 0)
            {
                Logger.Information("子行程 (PID: {Pid}) 結束，結束代碼: {ExitCode}, 強制終止: {WasForceStopped}", _process.Id, _process.ExitCode, _wasForceStopped);
            }
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
                Logger.Information("正在請求子行程 (PID: {Pid}) 關閉主視窗，等候逾時: {Timeout}", _process.Id, gracefulTimeout);
                _process.CloseMainWindow();
                using var timeout = new CancellationTokenSource(gracefulTimeout);
                using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, timeout.Token);
                try
                {
                    return await WaitForExitAsync(linked.Token).ConfigureAwait(false);
                }
                catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
                {
                    Logger.Warning("子行程 (PID: {Pid}) 未在預期時間內結束，執行強制中斷行程樹", _process.Id);
                    ForceKill();
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
                ForceKill();
            }

            await _process.WaitForExitAsync().ConfigureAwait(false);
            await Task.WhenAll(_standardOutputTask, _standardErrorTask).ConfigureAwait(false);
            _outputChannel.Writer.TryComplete();
            await _outputDispatchTask.ConfigureAwait(false);
            _process.Dispose();
        }

        private void ForceKill()
        {
            _wasForceStopped = true;
            try
            {
                _process.Kill(entireProcessTree: true);
            }
            catch (Exception ex) when (ex is InvalidOperationException or System.ComponentModel.Win32Exception)
            {
                Logger.Warning("強制終止子行程時行程已結束或權限不足: {Message}", ex.Message);
            }
        }

        private async Task PumpAsync(StreamReader reader, ProcessOutputKind kind)
        {
            while (await reader.ReadLineAsync().ConfigureAwait(false) is { } line)
            {
                _outputChannel.Writer.TryWrite(new ProcessOutput(kind, SanitizeOutputLine(line)));
            }
        }

        private async Task DispatchOutputAsync()
        {
            await foreach (ProcessOutput output in _outputChannel.Reader.ReadAllAsync().ConfigureAwait(false))
            {
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

                if (handler is not null)
                {
                    NotifyOutputReceived(handler, output);
                }
            }
        }

        private static void NotifyOutputReceived(Action<ProcessOutput> handler, ProcessOutput output)
        {
            try
            {
                handler(output);
            }
            catch (Exception ex)
            {
                Logger.Warning("處理子行程輸出事件時發生例外: {Message}", ex.Message);
            }
        }
    }

    private const int MaxOutputLineLength = 8192;
    private static readonly SearchValues<char> InvalidControlOrEscapeChars = SearchValues.Create(
        "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x0A\x0B\x0C\x0D\x0E\x0F" +
        "\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1A\x1B\x1C\x1D\x1E\x1F\x7F");

    /// <summary>
    /// 清洗行程輸出單行文字，過濾 ANSI 轉義序列與非列印控制字元並限制單行上限
    /// </summary>
    public static string SanitizeOutputLine(string line)
    {
        if (string.IsNullOrEmpty(line))
        {
            return string.Empty;
        }

        if (line.Length > MaxOutputLineLength)
        {
            line = line[..MaxOutputLineLength];
        }

        if (!line.AsSpan().ContainsAny(InvalidControlOrEscapeChars))
        {
            return line;
        }

        string withoutAnsi = line.Contains('\x1B') ? AnsiEscapeRegex().Replace(line, string.Empty) : line;

        if (!withoutAnsi.AsSpan().ContainsAny(InvalidControlOrEscapeChars))
        {
            return withoutAnsi;
        }

        Span<char> buffer = withoutAnsi.Length <= 512
            ? stackalloc char[withoutAnsi.Length]
            : new char[withoutAnsi.Length];
        int written = 0;
        foreach (char ch in withoutAnsi)
        {
            if (ch is '\t' or (>= (char)0x20 and not (char)0x7F))
            {
                buffer[written++] = ch;
            }
        }

        return new string(buffer[..written]);
    }

    [GeneratedRegex(@"\x1B\[[0-?]*[ -/]*[@-~]")]
    private static partial Regex AnsiEscapeRegex();
}
