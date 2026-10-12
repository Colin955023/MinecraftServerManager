using System.Buffers;
using System.Collections.Frozen;
using System.Text;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>
/// 伺服器啟動腳本與指令安全性檢驗器
/// </summary>
public static class SafeScriptValidator
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("SafeScriptValidator");

    /// <summary>
    /// 批次命令中嚴格禁止出現的危險字元（防範命令串接、管道、重新導向與逸出逃逸）
    /// </summary>
    private static readonly SearchValues<char> StrictForbiddenBatchChars = SearchValues.Create("&|<>^\0");

    /// <summary>
    /// 合法 Java 執行檔名稱集合
    /// </summary>
    private static readonly FrozenSet<string> ValidJavaExecutables = new[]
    {
        "java",
        "java.exe",
        "javaw",
        "javaw.exe"
    }.ToFrozenSet(StringComparer.OrdinalIgnoreCase);

    /// <summary>
    /// 檢查 Java 執行檔路徑是否安全合規。
    /// </summary>
    public static bool IsSafeJavaExecutable(string javaPath)
    {
        if (string.IsNullOrWhiteSpace(javaPath))
        {
            return false;
        }

        try
        {
            string fullPath = Path.GetFullPath(javaPath);
            if (!File.Exists(fullPath))
            {
                Logger.Warning("Java 執行檔不存在：{Path}", fullPath);
                return false;
            }

            if (SafeFileSystem.IsReparsePoint(fullPath))
            {
                Logger.Warning("拒絕使用符號連結或 Reparse Point 之 Java 執行檔：{Path}", fullPath);
                return false;
            }

            string fileName = Path.GetFileName(fullPath);
            return ValidJavaExecutables.Contains(fileName);
        }
        catch (Exception ex)
        {
            Logger.Warning("檢驗 Java 執行檔時發生例外：{Message}", ex.Message);
            return false;
        }
    }

    /// <summary>
    /// 驗證啟動參數所引用的 JAR 與引數檔（如 @args.txt）是否完全位於伺服器目錄內且非 Reparse Point。
    /// </summary>
    public static bool ValidateCommandInputs(string serverDirectory, IReadOnlyList<string> arguments)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);
        ArgumentNullException.ThrowIfNull(arguments);

        string stableServerDir = SafeFileSystem.ResolveStableDirectory(serverDirectory);

        for (int i = 0; i < arguments.Count; i++)
        {
            string arg = arguments[i];
            string? targetRelativePath = null;

            if (arg.StartsWith('@') && arg.Length > 1)
            {
                targetRelativePath = arg[1..].Trim('"');
            }
            else if (string.Equals(arg, "-jar", StringComparison.OrdinalIgnoreCase) && i + 1 < arguments.Count)
            {
                targetRelativePath = arguments[i + 1].Trim('"');
            }

            if (string.IsNullOrWhiteSpace(targetRelativePath))
            {
                continue;
            }

            // 若為絕對路徑或包含相對路徑，確認其位於伺服器目錄內
            string targetFullPath = Path.IsPathRooted(targetRelativePath)
                ? Path.GetFullPath(targetRelativePath)
                : Path.GetFullPath(Path.Combine(stableServerDir, targetRelativePath));

            if (!SafeFileSystem.IsPathWithin(stableServerDir, targetFullPath, strict: false))
            {
                Logger.Warning("啟動參數引用之檔案路徑越界：{Target} (伺服器目錄: {ServerDir})", targetFullPath, stableServerDir);
                return false;
            }

            if (SafeFileSystem.IsReparsePoint(targetFullPath))
            {
                Logger.Warning("啟動參數引用之檔案為 Reparse Point：{Target}", targetFullPath);
                return false;
            }

            if (!File.Exists(targetFullPath))
            {
                Logger.Warning("啟動參數引用之檔案不存在：{Target}", targetFullPath);
                return false;
            }
        }

        return true;
    }

    /// <summary>
    /// 檢查批次腳本內容是否安全合規（防範批次注入、路徑越界、任意命令執行）。
    /// </summary>
    public static bool ValidateScriptContent(string scriptPath, string serverDirectory)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(scriptPath);
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);

        string stableServerDir = SafeFileSystem.ResolveStableDirectory(serverDirectory);
        string fullScriptPath = Path.GetFullPath(scriptPath);

        if (!SafeFileSystem.IsPathWithin(stableServerDir, fullScriptPath, strict: false))
        {
            Logger.Warning("啟動腳本不在伺服器目錄內：{ScriptPath}", fullScriptPath);
            return false;
        }

        if (SafeFileSystem.IsReparsePoint(fullScriptPath) || !File.Exists(fullScriptPath))
        {
            Logger.Warning("啟動腳本不存在或為 Reparse Point：{ScriptPath}", fullScriptPath);
            return false;
        }

        try
        {
            string[] lines = File.ReadAllLines(fullScriptPath, Encoding.UTF8);
            foreach (string rawLine in lines)
            {
                string line = rawLine.Trim();
                if (string.IsNullOrEmpty(line))
                {
                    continue;
                }

                // 1. 無條件禁止命令串接、管道、重新導向與轉義符號（任何指令與註解均不得含有）
                if (line.AsSpan().ContainsAny(StrictForbiddenBatchChars))
                {
                    Logger.Warning("啟動腳本包含不安全之命令串接或重新導向字元：{Line}", line);
                    return false;
                }

                // 2. 禁止延遲變數展開字元 !
                if (line.Contains('!'))
                {
                    Logger.Warning("啟動腳本包含延遲變數展開字元 !：{Line}", line);
                    return false;
                }

                // 3. 檢查變數展開 %，僅允許相容之合法位置參數（例如 %*、%~dp0、%1 等）
                if (HasUnsafePercentUsage(line.AsSpan()))
                {
                    Logger.Warning("啟動腳本包含未受信任之環境變數展開語法：{Line}", line);
                    return false;
                }

                // 4. 防範路徑穿越
                if (line.Contains(".."))
                {
                    Logger.Warning("啟動腳本包含相對路徑穿越序列 ..：{Line}", line);
                    return false;
                }

                // 5. 結構化指令格式白名單檢驗
                if (!IsAllowedScriptCommand(line))
                {
                    Logger.Warning("啟動腳本包含未受信任之指令：{Line}", line);
                    return false;
                }
            }

            return true;
        }
        catch (Exception ex)
        {
            Logger.Warning("讀取啟動腳本失敗：{Message}", ex.Message);
            return false;
        }
    }

    private static bool IsAllowedScriptCommand(string line)
    {
        // 註解行
        if (line.StartsWith("::", StringComparison.Ordinal) ||
            (line.StartsWith("rem", StringComparison.OrdinalIgnoreCase) && (line.Length == 3 || char.IsWhiteSpace(line[3]))))
        {
            return true;
        }

        // 回顯設定與訊息
        if (line.StartsWith("@echo", StringComparison.OrdinalIgnoreCase) && (line.Length == 5 || char.IsWhiteSpace(line[5])))
        {
            return true;
        }

        if (line.StartsWith("echo", StringComparison.OrdinalIgnoreCase) && (line.Length == 4 || char.IsWhiteSpace(line[4])))
        {
            return true;
        }

        // 標題與暫停
        if (line.StartsWith("title", StringComparison.OrdinalIgnoreCase) && (line.Length == 5 || char.IsWhiteSpace(line[5])))
        {
            return true;
        }

        if (line.Equals("pause", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        // 字碼頁切換 (例如 chcp 65001)
        if (line.StartsWith("chcp", StringComparison.OrdinalIgnoreCase) && (line.Length == 4 || char.IsWhiteSpace(line[4])))
        {
            return true;
        }

        // 工作目錄切換 (僅允許切換至目前目錄或腳本所在目錄 %~dp0)
        if (line.StartsWith("cd", StringComparison.OrdinalIgnoreCase) && (line.Length == 2 || char.IsWhiteSpace(line[2])))
        {
            string cdArg = line[2..].Trim();
            if (cdArg.StartsWith("/d", StringComparison.OrdinalIgnoreCase))
            {
                cdArg = cdArg[2..].Trim();
            }

            cdArg = cdArg.Trim('"').Trim();
            return string.IsNullOrEmpty(cdArg) ||
                   cdArg.Equals(".", StringComparison.Ordinal) ||
                   cdArg.Equals("%~dp0", StringComparison.OrdinalIgnoreCase);
        }

        // Java 啟動指令
        if (line.StartsWith("java", StringComparison.OrdinalIgnoreCase) && (line.Length == 4 || char.IsWhiteSpace(line[4])))
        {
            return true;
        }

        if (line.StartsWith("\"java\"", StringComparison.OrdinalIgnoreCase) ||
            line.StartsWith("java.exe", StringComparison.OrdinalIgnoreCase) ||
            line.StartsWith("\"java.exe\"", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        return false;
    }

    private static bool HasUnsafePercentUsage(ReadOnlySpan<char> span)
    {
        int searchStart = 0;
        while (searchStart < span.Length)
        {
            int relativeIndex = span[searchStart..].IndexOf('%');
            if (relativeIndex < 0)
            {
                break;
            }

            int pos = searchStart + relativeIndex;
            int remaining = span.Length - (pos + 1);
            if (remaining <= 0)
            {
                // 單獨一個末端 % 視為異常
                return true;
            }

            char next = span[pos + 1];
            if (next == '*')
            {
                // %* 合法
                searchStart = pos + 2;
                continue;
            }

            if (char.IsAsciiDigit(next))
            {
                // %0 ~ %9 合法
                searchStart = pos + 2;
                continue;
            }

            if (next == '~')
            {
                // 檢查修飾符如 %~dp0、%~f0 等
                int modifierEnd = pos + 2;
                while (modifierEnd < span.Length && (span[modifierEnd] == 'd' || span[modifierEnd] == 'D' ||
                                                     span[modifierEnd] == 'p' || span[modifierEnd] == 'P' ||
                                                     span[modifierEnd] == 'f' || span[modifierEnd] == 'F' ||
                                                     span[modifierEnd] == 's' || span[modifierEnd] == 'S' ||
                                                     span[modifierEnd] == 'n' || span[modifierEnd] == 'N' ||
                                                     span[modifierEnd] == 'x' || span[modifierEnd] == 'X'))
                {
                    modifierEnd++;
                }

                if (modifierEnd < span.Length && (char.IsAsciiDigit(span[modifierEnd]) || span[modifierEnd] == '*'))
                {
                    searchStart = modifierEnd + 1;
                    continue;
                }
            }

            // 其餘任何形式（如 %TEMP%、%COMSPEC% 等）皆不允許
            return true;
        }

        return false;
    }
}
