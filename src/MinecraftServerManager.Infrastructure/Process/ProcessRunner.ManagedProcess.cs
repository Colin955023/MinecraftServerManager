using System.Buffers;
using System.ComponentModel;
using System.Text;
using System.Threading.Channels;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;

namespace MinecraftServerManager.Infrastructure.Process;

public sealed partial class ProcessRunner
{
    private sealed class ManagedProcess : IManagedProcess
    {
        private const int MaxPendingOutputLines = 256;
        private const int ReadBufferSize = 4096;
        private static readonly TimeSpan OutputDrainTimeout = TimeSpan.FromSeconds(5);

        private readonly System.Diagnostics.Process _process;
        private readonly int _pid;

        /// <summary>派送佇列；<see cref="DispatchItem.Output"/> 為 null 代表「有新訂閱者，請重播積壓輸出」的喚醒訊號</summary>
        private readonly Channel<DispatchItem> _outputChannel;
        private long _droppedOutputLines;
        private readonly Task _standardOutputTask;
        private readonly Task _standardErrorTask;
        private readonly Task _outputDispatchTask;
        private readonly Lock _outputLock = new();
        private readonly Queue<ProcessOutput> _pendingOutput = new();
        private readonly SemaphoreSlim _inputGate = new(1, 1);
        private bool _replayRequested;
        private bool _dispatchCompleted;
        private int _exitLogged;
        private volatile bool _wasForceStopped;
        private volatile bool _disposed;
        private int _disposeStarted;
        private Action<ProcessOutput>? _outputReceived;
        public event Action<ProcessOutput>? OutputLineObserved;
        private readonly Lock _exitLock = new();
        private Task<ProcessExitResult>? _exitTask;
        private ProcessExitResult? _exitResult;

        public ManagedProcess(System.Diagnostics.Process process, Action<ProcessOutput>? outputLineObserved)
        {
            _process = process;
            _pid = process.Id;
            OutputLineObserved = outputLineObserved;
            _outputChannel = Channel.CreateBounded<DispatchItem>(
                new BoundedChannelOptions(MaxPendingOutputLines)
                {
                    FullMode = BoundedChannelFullMode.DropOldest,
                    SingleReader = true,
                    SingleWriter = false,
                },
                item =>
                {
                    // 喚醒訊號被擠掉無妨：派送端每次取項前都會檢查重播旗標
                    if (item.Output is not null)
                    {
                        Interlocked.Increment(ref _droppedOutputLines);
                    }
                });
            _outputDispatchTask = DispatchOutputAsync();
            _standardOutputTask = process.StartInfo.RedirectStandardOutput
                ? PumpAsync(_process.StandardOutput, ProcessOutputKind.StandardOutput)
                : Task.CompletedTask;
            _standardErrorTask = process.StartInfo.RedirectStandardError
                ? PumpAsync(_process.StandardError, ProcessOutputKind.StandardError)
                : Task.CompletedTask;
        }

        public int Pid => _pid;

        // 處置後 Process 物件已釋放，不可再讀取其屬性；改用結束時留存的結果
        public bool HasExited
        {
            get
            {
                if (_exitResult is not null || _disposed)
                {
                    return true;
                }

                try
                {
                    return _process.HasExited;
                }
                catch (ObjectDisposedException)
                {
                    return true;
                }
            }
        }

        public int? ExitCode
        {
            get
            {
                if (_exitResult is { } result)
                {
                    return result.ExitCode;
                }

                try
                {
                    return !_disposed && _process.HasExited ? _process.ExitCode : null;
                }
                catch (ObjectDisposedException)
                {
                    return _exitResult?.ExitCode;
                }
            }
        }

        public long DroppedOutputLines => Interlocked.Read(ref _droppedOutputLines);

        public event Action<ProcessOutput>? OutputReceived
        {
            add
            {
                ArgumentNullException.ThrowIfNull(value);

                // 處理常式只由派送端在鎖外呼叫；訂閱時僅登記並請派送端先重播積壓輸出，確保順序且不並行
                bool replayNow;
                lock (_outputLock)
                {
                    _outputReceived += value;
                    replayNow = _dispatchCompleted;
                    if (!replayNow)
                    {
                        _replayRequested = true;
                    }
                }

                if (replayNow)
                {
                    // 派送已結束，不會再有並行呼叫，直接在呼叫端重播剩餘積壓
                    ReplayBacklog();
                }
                else
                {
                    _outputChannel.Writer.TryWrite(default);
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

            try
            {
                // 序列化寫入，避免多個命令的內容在標準輸入交錯
                await _inputGate.WaitAsync(cancellationToken).ConfigureAwait(false);
            }
            catch (ObjectDisposedException)
            {
                throw new ObjectDisposedException(nameof(ManagedProcess));
            }

            try
            {
                ObjectDisposedException.ThrowIf(_disposed, this);
                await _process.StandardInput.WriteLineAsync(line.AsMemory(), cancellationToken).ConfigureAwait(false);
                await _process.StandardInput.FlushAsync(cancellationToken).ConfigureAwait(false);
            }
            finally
            {
                try
                {
                    _inputGate.Release();
                }
                catch (ObjectDisposedException)
                {
                    Logger.Information("子行程 (PID: {Pid}) 已處置，略過釋放輸入閘門", _pid);
                }
            }
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
            catch (Exception ex) when (ex is InvalidOperationException or Win32Exception or ObjectDisposedException)
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
                Logger.Information("子行程 (PID: {Pid}) 結束，結束代碼: {ExitCode}, 強制終止: {WasForceStopped}", _pid, result.ExitCode, _wasForceStopped);
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
            if (!HasExited && gracefulTimeout == TimeSpan.Zero)
            {
                // 不給寬限時間即直接強制終止，不送出關閉視窗請求
                ForceKill();
            }
            else if (!HasExited)
            {
                Logger.Information("正在請求子行程 (PID: {Pid}) 關閉主視窗，等候逾時: {Timeout}", _pid, gracefulTimeout);
                _process.CloseMainWindow();
                using var linked = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
                linked.CancelAfter(gracefulTimeout);
                try
                {
                    return await WaitForExitAsync(linked.Token).ConfigureAwait(false);
                }
                catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
                {
                    Logger.Warning("子行程 (PID: {Pid}) 未在預期時間內結束，執行強制中斷行程樹", _pid);
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
            try
            {
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
                    Logger.Warning("子行程 (PID: {Pid}) 未在 {Timeout} 內結束，不再等待", _pid, OutputDrainTimeout);
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
                        Logger.Warning(ex, "子行程 (PID: {Pid}) 處置時未能取得結束結果", _pid);
                    }
                }
            }
            finally
            {
                _process.Dispose();
                _inputGate.Dispose();
            }
        }

        /// <summary>等待輸出管線讀完；孫行程可能佔用管線，故設逾時</summary>
        private async Task DrainOutputAsync()
        {
            try
            {
                await Task.WhenAll(_standardOutputTask, _standardErrorTask).WaitAsync(OutputDrainTimeout).ConfigureAwait(false);
            }
            catch (TimeoutException)
            {
                Logger.Warning("子行程 (PID: {Pid}) 輸出管線未在 {Timeout} 內關閉（可能有孫行程持有管線），不再等待", _pid, OutputDrainTimeout);
            }
            finally
            {
                _outputChannel.Writer.TryComplete();
            }

            try
            {
                // 處理常式卡住時不無限等待派送端
                await _outputDispatchTask.WaitAsync(OutputDrainTimeout).ConfigureAwait(false);
            }
            catch (TimeoutException)
            {
                Logger.Warning("子行程 (PID: {Pid}) 輸出處理常式未在 {Timeout} 內完成，不再等待", _pid, OutputDrainTimeout);
            }

            long dropped = DroppedOutputLines;
            if (dropped > 0)
            {
                Logger.Warning("子行程 (PID: {Pid}) 輸出速度超過處理能力，已捨棄 {Dropped} 行", _pid, dropped);
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
                Logger.Warning(ex, "強制終止子行程 (PID: {Pid}) 時行程已結束或權限不足", _pid);
            }
        }

        /// <summary>以固定緩衝區讀取並切行；單行超過上限時只保留前段，不讓整行留在記憶體</summary>
        private async Task PumpAsync(StreamReader reader, ProcessOutputKind kind)
        {
            char[] buffer = ArrayPool<char>.Shared.Rent(ReadBufferSize);
            var line = new StringBuilder();
            bool truncating = false;
            bool skipLineFeed = false;
            try
            {
                int read;
                while ((read = await reader.ReadAsync(buffer.AsMemory(0, ReadBufferSize)).ConfigureAwait(false)) > 0)
                {
                    int start = 0;
                    if (skipLineFeed)
                    {
                        skipLineFeed = false;
                        if (buffer[0] == '\n')
                        {
                            start = 1;
                        }
                    }

                    while (start < read)
                    {
                        ReadOnlySpan<char> remaining = buffer.AsSpan(start, read - start);
                        int newline = remaining.IndexOfAny('\r', '\n');
                        ReadOnlySpan<char> segment = newline < 0 ? remaining : remaining[..newline];
                        if (!truncating)
                        {
                            int room = MaxOutputLineLength - line.Length;
                            line.Append(segment.Length <= room ? segment : segment[..room]);
                            truncating = segment.Length > room;
                        }

                        if (newline < 0)
                        {
                            break;
                        }

                        EmitLine(kind, line);
                        truncating = false;
                        start += newline + 1;
                        if (remaining[newline] == '\r')
                        {
                            if (start < read)
                            {
                                if (buffer[start] == '\n')
                                {
                                    start++;
                                }
                            }
                            else
                            {
                                skipLineFeed = true;
                            }
                        }
                    }
                }

                if (line.Length > 0 || truncating)
                {
                    EmitLine(kind, line);
                }
            }
            catch (Exception ex) when (ex is IOException or ObjectDisposedException)
            {
                Logger.Warning(ex, "讀取子行程 (PID: {Pid}) 輸出管線中斷", _pid);
            }
            finally
            {
                ArrayPool<char>.Shared.Return(buffer);
            }
        }

        private void EmitLine(ProcessOutputKind kind, StringBuilder line)
        {
            var output = new ProcessOutput(kind, SanitizeOutputLine(line.ToString()));
            NotifyOutputLineObserved(output);
            _outputChannel.Writer.TryWrite(new DispatchItem(output));
            line.Clear();
        }

        private void NotifyOutputLineObserved(ProcessOutput output)
        {
            try
            {
                OutputLineObserved?.Invoke(output);
            }
            catch (Exception ex)
            {
                Logger.Warning(ex, "處理子行程即時輸出事件時發生例外");
            }
        }

        private async Task DispatchOutputAsync()
        {
            await foreach (DispatchItem item in _outputChannel.Reader.ReadAllAsync().ConfigureAwait(false))
            {
                ReplayBacklogIfRequested();
                if (item.Output is not { } output)
                {
                    continue;
                }

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
                            Interlocked.Increment(ref _droppedOutputLines);
                        }
                    }
                }

                if (handler is not null)
                {
                    NotifyOutputReceived(handler, output);
                }
            }

            bool replay;
            lock (_outputLock)
            {
                _dispatchCompleted = true;
                replay = _replayRequested;
                _replayRequested = false;
            }

            if (replay)
            {
                ReplayBacklog();
            }
        }

        private void ReplayBacklogIfRequested()
        {
            lock (_outputLock)
            {
                if (!_replayRequested)
                {
                    return;
                }

                _replayRequested = false;
            }

            ReplayBacklog();
        }

        /// <summary>於鎖內取出積壓輸出，在鎖外依序交給目前的處理常式</summary>
        private void ReplayBacklog()
        {
            Action<ProcessOutput>? handler;
            ProcessOutput[] backlog;
            lock (_outputLock)
            {
                handler = _outputReceived;
                if (handler is null || _pendingOutput.Count == 0)
                {
                    return;
                }

                backlog = [.. _pendingOutput];
                _pendingOutput.Clear();
            }

            foreach (ProcessOutput output in backlog)
            {
                NotifyOutputReceived(handler, output);
            }
        }

        private readonly record struct DispatchItem(ProcessOutput? Output);

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

    private static readonly SearchValues<char> InvalidControlOrEscapeChars = SearchValues.Create(
        "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x0A\x0B\x0C\x0D\x0E\x0F" +
        "\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1A\x1B\x1C\x1D\x1E\x1F\x7F");

    /// <summary>清洗行程輸出單行文字，過濾 ANSI 逸出序列與非列印控制字元並限制單行上限</summary>
    internal static string SanitizeOutputLine(string line)
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
