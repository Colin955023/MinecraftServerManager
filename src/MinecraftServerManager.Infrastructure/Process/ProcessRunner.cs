using System.Buffers;
using System.Collections.Frozen;
using System.ComponentModel;
using System.Diagnostics;
using System.Text;
using System.Threading.Channels;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;

using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Process;

public sealed partial class ProcessRunner : IProcessRunner, IExternalLauncher, IProcessInspector
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ProcessRunner));

    private static readonly FrozenSet<string> AllowedOpenFileExtensions =
        new[] { ".txt", ".log", ".json", ".toml", ".properties", ".yml", ".yaml", ".ini", ".cfg", ".md", ".csv", ".html", ".htm", ".xlsx", ".xml" }
            .ToFrozenSet(StringComparer.OrdinalIgnoreCase);

    public bool OpenFolder(string folderPath)
    {
        if (string.IsNullOrWhiteSpace(folderPath) || !SafeFileSystem.DirectoryExists(folderPath))
        {
            Logger.Warning("開啟資料夾失敗，路徑不存在或為空: {Path}", folderPath);
            return false;
        }

        if (TryShellExecute(() => new ProcessStartInfo { FileName = folderPath, UseShellExecute = true }) is { } error)
        {
            Logger.Error(error, "開啟資料夾失敗: {Path}", folderPath);
            return false;
        }

        Logger.Information("已開啟資料夾: {Path}", folderPath);
        return true;
    }

    public bool ShowInFolder(string filePath)
    {
        if (string.IsNullOrWhiteSpace(filePath) || !SafeFileSystem.FileExists(filePath))
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
            Logger.Error(error, "在資料夾中顯示檔案失敗: {Path}", filePath);
            return false;
        }

        Logger.Information("已在資料夾中顯示檔案: {Path}", filePath);
        return true;
    }

    public bool OpenFile(string filePath, bool isTrusted = false)
    {
        if (string.IsNullOrWhiteSpace(filePath) || !SafeFileSystem.FileExists(filePath))
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
            Logger.Error(error, "開啟檔案失敗: {Path}", filePath);
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

        // 若為程式內建或受信任的連結，不需協定拒絕判斷
        if (!isTrusted && uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps)
        {
            Logger.Warning("開啟網址被拒絕，非 HTTP/HTTPS 協定: {Url}", url);
            return false;
        }

        if (TryShellExecute(() => new ProcessStartInfo { FileName = url, UseShellExecute = true }) is { } error)
        {
            Logger.Error(error, "開啟網址失敗: {Url}", url);
            return false;
        }

        Logger.Information("已開啟網址: {Url}", url);
        return true;
    }

    /// <summary>取得指定 PID 行程的啟動時間（UTC），查詢失敗回傳 null</summary>
    public DateTime? GetStartTimeUtc(int pid)
    {
        try
        {
            using var process = System.Diagnostics.Process.GetProcessById(pid);
            return process.HasExited ? null : process.StartTime.ToUniversalTime();
        }
        catch (Exception ex) when (ex is ArgumentException or InvalidOperationException or Win32Exception)
        {
            return null;
        }
    }

    /// <summary>強制終止指定 PID 的行程及其子行程，行程已不存在視為成功</summary>
    public bool KillProcessTree(int pid)
    {
        try
        {
            using var process = System.Diagnostics.Process.GetProcessById(pid);
            process.Kill(entireProcessTree: true);
            Logger.Information("已強制終止行程樹 (PID: {Pid})", pid);
            return true;
        }
        catch (ArgumentException)
        {
            return true;
        }
        catch (Exception ex) when (ex is InvalidOperationException or Win32Exception)
        {
            Logger.Warning(ex, "強制終止行程樹失敗 (PID: {Pid})", pid);
            return false;
        }
    }

    /// <summary>以殼層方式啟動目標；成功回傳 null，失敗回傳例外供呼叫端記錄</summary>
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
                             Path.Combine(RuntimePaths.GetSystemDir(), "cmd.exe");
            if (!SafeFileSystem.FileExists(comSpec))
            {
                throw new FileNotFoundException("找不到系統命令解譯器 (cmd.exe)", comSpec);
            }

            // cmd.exe 會在引號內仍解譯部分中繼字元，路徑或參數含中繼字元一律拒絕以防指令串接
            if (resolvedFileName.AsSpan().ContainsAny(CmdMetaChars) ||
                specification.Arguments.Any(static a => a.AsSpan().ContainsAny(CmdMetaChars)))
            {
                throw new ArgumentException("批次檔路徑或參數含 cmd 中繼字元，已拒絕執行", nameof(specification));
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

        ApplyEnvironment(startInfo, specification);

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

    private static void ApplyEnvironment(ProcessStartInfo startInfo, ProcessStartSpec specification)
    {
        if (specification.Environment is null)
        {
            return;
        }

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

    public void StartDetached(ProcessStartSpec specification)
    {
        ArgumentNullException.ThrowIfNull(specification);
        if (specification.UseShellExecute)
        {
            throw new ArgumentException("脫離管理啟動不支援殼層執行", nameof(specification));
        }

        string executable = ResolveAndValidateExecutable(specification);
        var startInfo = new ProcessStartInfo
        {
            FileName = executable,
            WorkingDirectory = specification.WorkingDirectory ?? Environment.CurrentDirectory,
            UseShellExecute = false,
            CreateNoWindow = specification.CreateNoWindow,
        };
        foreach (string argument in specification.Arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        ApplyEnvironment(startInfo, specification);

        using var process = System.Diagnostics.Process.Start(startInfo)
            ?? throw new InvalidOperationException($"無法啟動脫離管理的行程：{executable}");

        Logger.Information("已啟動脫離管理的子行程，PID: {Pid} ({FileName})", process.Id, executable);
    }

    private static string ResolveAndValidateExecutable(ProcessStartSpec specification)
    {
        if (string.IsNullOrWhiteSpace(specification.FileName))
        {
            throw new ArgumentException("執行檔名稱不得為空", nameof(specification));
        }

        string fileName = specification.FileName;

        if (specification.WorkingDirectory is not null && !SafeFileSystem.DirectoryExists(specification.WorkingDirectory))
        {
            throw new DirectoryNotFoundException($"找不到工作目錄：{specification.WorkingDirectory}");
        }

        string basePath = specification.WorkingDirectory ?? Environment.CurrentDirectory;
        string candidatePath = Path.GetFullPath(fileName, basePath);

        // 純檔名不在工作目錄內解析（避免伺服器資料夾內被植入同名執行檔），交由 PATH／系統目錄搜尋
        if (Path.IsPathFullyQualified(fileName) ||
            fileName.Contains(Path.DirectorySeparatorChar) ||
            fileName.Contains(Path.AltDirectorySeparatorChar))
        {
            // winget 的 App Execution Alias 本身即為 reparse point，須先判斷，否則會被 FileExists 視為不存在
            if (IsTrustedWindowsAppAliasFile(candidatePath))
            {
                return candidatePath;
            }

            // FileExists 對 reparse point 一律回傳 false，因此不可信任的 reparse point 亦會在此被拒絕
            if (!SafeFileSystem.FileExists(candidatePath))
            {
                throw new FileNotFoundException("找不到指定的執行檔", fileName);
            }

            return candidatePath;
        }

        // 純檔名搜尋，若為 winget 則額外檢查 WindowsApps 目錄
        if (string.Equals(fileName, "winget", StringComparison.OrdinalIgnoreCase) ||
            string.Equals(fileName, "winget.exe", StringComparison.OrdinalIgnoreCase))
        {
            string localAppData = RuntimePaths.GetLocalAppDataDir();
            if (!string.IsNullOrEmpty(localAppData))
            {
                string wingetDefault = Path.Combine(localAppData, "Microsoft", "WindowsApps", "winget.exe");
                if (IsTrustedWindowsAppAliasFile(wingetDefault))
                {
                    return wingetDefault;
                }
            }
        }

        return fileName;
    }

    /// <summary>判斷是否為 %LOCALAPPDATA%\Microsoft\WindowsApps 下實際存在的 winget.exe 別名（不擲出例外）</summary>
    private static bool IsTrustedWindowsAppAliasFile(string filePath) =>
        IsTrustedWindowsAppAlias(filePath) &&
        SafeFileSystem.DirectoryExists(Path.GetDirectoryName(filePath)!) &&
        SafeFileSystem.IsReparsePoint(filePath);

    private static bool IsTrustedWindowsAppAlias(string filePath)
    {
        string name = Path.GetFileName(filePath);
        if (!string.Equals(name, "winget.exe", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        string localAppData = RuntimePaths.GetLocalAppDataDir();
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
        private static readonly TimeSpan OutputDrainTimeout = TimeSpan.FromSeconds(5);

        private readonly Channel<ProcessOutput> _outputChannel;
        private long _droppedOutputLines;
        private readonly Task _standardOutputTask;
        private readonly Task _standardErrorTask;
        private readonly Task _outputDispatchTask;
        private readonly Lock _outputLock = new();
        private readonly Queue<ProcessOutput> _pendingOutput = new();
        private int _exitLogged;
        private bool _wasForceStopped;
        private bool _disposed;
        private int _disposeStarted;
        private Action<ProcessOutput>? _outputReceived;
        private readonly Lock _exitLock = new();
        private Task<ProcessExitResult>? _exitTask;
        private ProcessExitResult? _exitResult;

        public ManagedProcess(System.Diagnostics.Process process)
        {
            _process = process;
            _outputChannel = Channel.CreateBounded<ProcessOutput>(
                new BoundedChannelOptions(MaxPendingOutputLines)
                {
                    FullMode = BoundedChannelFullMode.DropOldest,
                    SingleReader = true,
                    SingleWriter = false,
                },
                _ => Interlocked.Increment(ref _droppedOutputLines));
            _outputDispatchTask = DispatchOutputAsync();
            _standardOutputTask = process.StartInfo.RedirectStandardOutput
                ? PumpAsync(_process.StandardOutput, ProcessOutputKind.StandardOutput)
                : Task.CompletedTask;
            _standardErrorTask = process.StartInfo.RedirectStandardError
                ? PumpAsync(_process.StandardError, ProcessOutputKind.StandardError)
                : Task.CompletedTask;
        }

        public int Pid => _process.Id;

        // 處置後 Process 物件已釋放，不可再讀取其屬性；改用結束時留存的結果
        public bool HasExited => _exitResult is not null || _disposed || _process.HasExited;

        public int? ExitCode => _exitResult?.ExitCode ?? (!_disposed && _process.HasExited ? _process.ExitCode : null);

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

        public long? GetWorkingSet64()
        {
            try
            {
                if (_disposed || _process.HasExited)
                {
                    return null;
                }

                _process.Refresh();
                return _process.WorkingSet64;
            }
            catch (Exception ex) when (ex is InvalidOperationException or Win32Exception)
            {
                return null;
            }
        }

        /// <summary>所有等待者共用同一個結束工作，結束代碼只讀取一次，處置後仍可取得已留存的結果</summary>
        public Task<ProcessExitResult> WaitForExitAsync(CancellationToken cancellationToken = default)
        {
            Task<ProcessExitResult> exitTask;
            lock (_exitLock)
            {
                if (_exitTask is null)
                {
                    ObjectDisposedException.ThrowIf(_disposed, this);
                    _exitTask = WaitForExitCoreAsync();
                }

                exitTask = _exitTask;
            }

            return exitTask.WaitAsync(cancellationToken);
        }

        private async Task<ProcessExitResult> WaitForExitCoreAsync()
        {
            await _process.WaitForExitAsync().ConfigureAwait(false);
            await DrainOutputAsync().ConfigureAwait(false);
            var result = new ProcessExitResult(_process.ExitCode, _wasForceStopped);
            _exitResult = result;
            if (Interlocked.Exchange(ref _exitLogged, 1) == 0)
            {
                Logger.Information("子行程 (PID: {Pid}) 結束，結束代碼: {ExitCode}, 強制終止: {WasForceStopped}", _process.Id, result.ExitCode, _wasForceStopped);
            }
            return result;
        }

        public async Task<ProcessExitResult> StopAsync(
            TimeSpan gracefulTimeout,
            CancellationToken cancellationToken = default)
        {
            ArgumentOutOfRangeException.ThrowIfLessThan(gracefulTimeout, TimeSpan.Zero);
            if (_exitResult is { } exited)
            {
                return exited;
            }

            ObjectDisposedException.ThrowIf(_disposed, this);
            if (!HasExited)
            {
                Logger.Information("正在請求子行程 (PID: {Pid}) 關閉主視窗，等候逾時: {Timeout}", _process.Id, gracefulTimeout);
                _process.CloseMainWindow();
                using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
                linked.CancelAfter(gracefulTimeout);
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
            if (Interlocked.Exchange(ref _disposeStarted, 1) != 0)
            {
                return;
            }

            _disposed = true;
            if (!_process.HasExited)
            {
                ForceKill();
            }

            try
            {
                // 強制終止失敗（權限不足等）時行程可能不會結束，設逾時避免處置流程無限等待
                await _process.WaitForExitAsync().WaitAsync(OutputDrainTimeout).ConfigureAwait(false);
            }
            catch (TimeoutException)
            {
                Logger.Warning("子行程 (PID: {Pid}) 未在 {Timeout} 內結束，不再等待", _process.Id, OutputDrainTimeout);
            }

            await DrainOutputAsync().ConfigureAwait(false);

            Task<ProcessExitResult>? exitTask;
            lock (_exitLock)
            {
                exitTask = _exitTask;
            }

            if (exitTask is not null)
            {
                try
                {
                    // 先讓共用的結束工作讀完結束代碼，再釋放 Process
                    await exitTask.WaitAsync(OutputDrainTimeout).ConfigureAwait(false);
                }
                catch (Exception ex) when (ex is TimeoutException or InvalidOperationException)
                {
                    Logger.Warning(ex, "子行程 (PID: {Pid}) 處置時未能取得結束結果", _process.Id);
                }
            }

            _process.Dispose();
        }

        /// <summary>等待標準輸出／錯誤管線讀完並結束分派；孫行程可能繼承管線而使其永不關閉，故設逾時</summary>
        private async Task DrainOutputAsync()
        {
            try
            {
                await Task.WhenAll(_standardOutputTask, _standardErrorTask).WaitAsync(OutputDrainTimeout).ConfigureAwait(false);
            }
            catch (TimeoutException)
            {
                Logger.Warning("子行程 (PID: {Pid}) 輸出管線未在 {Timeout} 內關閉（可能有孫行程持有管線），不再等待", _process.Id, OutputDrainTimeout);
            }

            _outputChannel.Writer.TryComplete();
            await _outputDispatchTask.ConfigureAwait(false);

            long dropped = Interlocked.Exchange(ref _droppedOutputLines, 0);
            if (dropped > 0)
            {
                Logger.Warning("子行程 (PID: {Pid}) 輸出速度超過處理能力，已捨棄 {Dropped} 行", _process.Id, dropped);
            }
        }

        private void ForceKill()
        {
            _wasForceStopped = true;
            try
            {
                _process.Kill(entireProcessTree: true);
            }
            catch (Exception ex) when (ex is InvalidOperationException or Win32Exception)
            {
                Logger.Warning(ex, "強制終止子行程時行程已結束或權限不足");
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
                Logger.Warning(ex, "處理子行程輸出事件時發生例外");
            }
        }
    }

    private const int MaxOutputLineLength = 8192;
    private static readonly SearchValues<char> CmdMetaChars = SearchValues.Create("&|<>^%!()\"");

    private static readonly SearchValues<char> InvalidControlOrEscapeChars = SearchValues.Create(
        "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x0A\x0B\x0C\x0D\x0E\x0F" +
        "\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1A\x1B\x1C\x1D\x1E\x1F\x7F");

    /// <summary>清洗行程輸出單行文字，過濾 ANSI 逸出序列與非列印控制字元並限制單行上限</summary>
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

        string withoutAnsi = line.Contains('\x1B') ? ModHelpers.StripColorAndFormattingCodes(line) : line;

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
}
