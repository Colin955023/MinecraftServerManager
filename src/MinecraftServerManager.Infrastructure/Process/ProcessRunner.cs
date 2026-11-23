using System.Buffers;
using System.ComponentModel;
using System.Diagnostics;
using System.Text;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Utilities;

namespace MinecraftServerManager.Infrastructure.Process;

public sealed partial class ProcessRunner : IProcessRunner, IProcessInspector
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ProcessRunner));

    public DateTimeOffset? GetStartTimeUtc(int pid) => QueryStartTimeUtc(pid);

    /// <summary>查詢存活行程的啟動時間（UTC）；行程不存在、已結束或無權限時回傳 null</summary>
    internal static DateTimeOffset? QueryStartTimeUtc(int pid)
    {
        try
        {
            using var process = System.Diagnostics.Process.GetProcessById(pid);
            return process.HasExited ? null : new DateTimeOffset(process.StartTime.ToUniversalTime(), TimeSpan.Zero);
        }
        catch (Exception ex) when (ex is ArgumentException or InvalidOperationException or Win32Exception)
        {
            return null;
        }
    }

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

    public Task<IManagedProcess> StartAsync(
        ProcessStartSpec specification,
        Action<ProcessOutput>? outputLineObserved = null,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(specification);
        cancellationToken.ThrowIfCancellationRequested();
        string resolvedFileName = ResolveAndValidateExecutable(specification);

        Logger.Information("準備啟動子行程: {FileName} (工作目錄: {WorkingDirectory})", resolvedFileName, specification.WorkingDirectory);

        bool redirect = !specification.UseShellExecute;
        var startInfo = new ProcessStartInfo
        {
            WorkingDirectory = specification.WorkingDirectory ?? Environment.CurrentDirectory,
            UseShellExecute = specification.UseShellExecute,
            CreateNoWindow = specification.CreateNoWindow,
            RedirectStandardInput = redirect,
            RedirectStandardOutput = redirect,
            RedirectStandardError = redirect,
            StandardInputEncoding = redirect ? Utf8NoBom : null,
            StandardOutputEncoding = redirect ? Utf8NoBom : null,
            StandardErrorEncoding = redirect ? Utf8NoBom : null,
        };

        if (redirect)
        {
            ApplyCommand(startInfo, resolvedFileName, specification);
        }
        else
        {
            startInfo.FileName = resolvedFileName;
            AddArguments(startInfo, specification.Arguments);
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
            return Task.FromResult<IManagedProcess>(new ManagedProcess(process, outputLineObserved));
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "啟動子行程失敗: {FileName}", resolvedFileName);
            process.Dispose();
            throw;
        }
    }

    /// <summary>設定執行檔與參數；批次檔改經固定路徑的 cmd.exe 執行並拒絕 cmd 中繼字元</summary>
    private static void ApplyCommand(ProcessStartInfo startInfo, string executable, ProcessStartSpec specification)
    {
        ReadOnlySpan<char> extension = Path.GetExtension(executable.AsSpan());
        bool isBatchScript = extension.Equals(".bat", StringComparison.OrdinalIgnoreCase) ||
                             extension.Equals(".cmd", StringComparison.OrdinalIgnoreCase);
        if (!isBatchScript)
        {
            startInfo.FileName = executable;
            AddArguments(startInfo, specification.Arguments);
            return;
        }

        // 不信任 ComSpec 環境變數，固定使用系統目錄的 cmd.exe
        if (!SafeFileSystem.FileExists(CmdPath))
        {
            throw new FileNotFoundException("找不到系統命令解譯器 (cmd.exe)", CmdPath);
        }

        // cmd.exe 在引號內仍會解譯部分中繼字元；結尾反斜線會吃掉收尾引號
        if (IsUnsafeCmdToken(executable) || specification.Arguments.Any(IsUnsafeCmdToken))
        {
            throw new ArgumentException("批次檔路徑或參數含 cmd 中繼字元，已拒絕執行", nameof(specification));
        }

        startInfo.FileName = CmdPath;
        startInfo.ArgumentList.Add("/d");
        startInfo.ArgumentList.Add("/c");
        startInfo.ArgumentList.Add(executable);
        AddArguments(startInfo, specification.Arguments);
    }

    private static bool IsUnsafeCmdToken(string token) =>
        token.AsSpan().ContainsAny(CmdMetaChars) || token.EndsWith('\\');

    private static void AddArguments(ProcessStartInfo startInfo, IEnumerable<string> arguments)
    {
        foreach (string argument in arguments)
        {
            startInfo.ArgumentList.Add(argument);
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
            WorkingDirectory = specification.WorkingDirectory ?? Environment.CurrentDirectory,
            UseShellExecute = false,
            CreateNoWindow = specification.CreateNoWindow,
        };
        ApplyCommand(startInfo, executable, specification);
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

        // 純檔名不在工作目錄內解析，交由 PATH 搜尋
        if (Path.IsPathFullyQualified(fileName) ||
            fileName.Contains(Path.DirectorySeparatorChar) ||
            fileName.Contains(Path.AltDirectorySeparatorChar))
        {
            // winget 別名本身是 reparse point，須先判斷
            if (IsTrustedWindowsAppAliasFile(candidatePath))
            {
                return candidatePath;
            }

            // FileExists 對 reparse point 回傳 false，不可信任者在此被拒絕
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

    /// <summary>是否為 WindowsApps 下的 winget.exe 別名</summary>
    private static bool IsTrustedWindowsAppAliasFile(string filePath) =>
        IsTrustedWindowsAppAlias(filePath) &&
        SafeFileSystem.DirectoryExists(Path.GetDirectoryName(filePath)!) &&
        // 讀取失敗不得視為可信別名，故不使用失敗即視為 reparse 的 IsReparsePoint
        SafeFileSystem.IsConfirmedReparsePoint(filePath);

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

    private static readonly SearchValues<char> CmdMetaChars = SearchValues.Create("&|<>^%!()\"\r\n\0");
    private static readonly UTF8Encoding Utf8NoBom = new(encoderShouldEmitUTF8Identifier: false);
    private static readonly string CmdPath = Path.Combine(RuntimePaths.GetSystemDir(), "cmd.exe");
}
