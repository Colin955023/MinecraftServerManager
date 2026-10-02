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
    /// 批次命令中禁止出現的危險字元（防範命令鏈接與變數展開注入）
    /// </summary>
    private static readonly SearchValues<char> UnsafeBatchChars = SearchValues.Create("&|<>^%!();\0");

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
    /// 檢查批次腳本內容是否安全合規（防範批次注入、路徑越界）。
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

                // 註解行或已知安全的開頭略過
                if (line.StartsWith("::", StringComparison.Ordinal) ||
                    line.StartsWith("rem ", StringComparison.OrdinalIgnoreCase) ||
                    line.StartsWith("echo ", StringComparison.OrdinalIgnoreCase) ||
                    line.StartsWith("@echo ", StringComparison.OrdinalIgnoreCase) ||
                    line.StartsWith("title ", StringComparison.OrdinalIgnoreCase) ||
                    line.StartsWith("pause", StringComparison.OrdinalIgnoreCase) ||
                    line.StartsWith("chcp ", StringComparison.OrdinalIgnoreCase) ||
                    line.StartsWith("cd ", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                // 檢查是否含有命令串接或危險變數展開字元
                if (line.AsSpan().ContainsAny(UnsafeBatchChars))
                {
                    Logger.Warning("啟動腳本包含不安全之批次指令字元：{Line}", line);
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
}
