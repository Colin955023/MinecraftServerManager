using System.Buffers;
using System.Collections.Frozen;
using System.Text;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>伺服器啟動腳本與指令安全性檢驗器</summary>
public static class SafeScriptValidator
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(SafeScriptValidator));

    private static readonly SearchValues<char> StrictForbiddenBatchChars = SearchValues.Create("&|<>^\0");

    // cmd.exe 解析命令名稱時的分隔符；未加引號的執行檔路徑出現非空白分隔符時解析結果與本檢驗不一致
    private static readonly SearchValues<char> CmdSeparators = SearchValues.Create(" \t,;=");

    private const string ScriptDirectoryToken = "%~dp0";
    private const long MaxArgumentFileBytes = 1024 * 1024;

    private static readonly FrozenSet<string> ValidJavaExecutables = FrozenSet.Create(
        StringComparer.OrdinalIgnoreCase,
        ServerDefaults.DefaultJavaCommand,
        "java.exe",
        "javaw",
        "javaw.exe");

    /// <summary>純檔名是否為允許的 Java 執行檔名稱（java／javaw，含 .exe）</summary>
    internal static bool IsJavaExecutableName(string fileName) => ValidJavaExecutables.Contains(fileName);

    /// <summary>Java 路徑須為實體 java 執行檔；純檔名只接受 java 系列名稱，不符合時拋出 <see cref="InvalidOperationException"/></summary>
    internal static void ValidateJavaPath(string javaPath)
    {
        string trimmedJava = javaPath.Trim();
        bool isBareName = Path.GetFileName(trimmedJava) == trimmedJava;
        if (isBareName ? !IsJavaExecutableName(trimmedJava) : !IsSafeJavaExecutable(trimmedJava))
        {
            throw new InvalidOperationException($"指定的 Java 執行檔未通過安全性檢驗：{javaPath}");
        }
    }

    internal static bool IsSafeJavaExecutable(string javaPath)
    {
        if (string.IsNullOrWhiteSpace(javaPath))
        {
            return false;
        }

        try
        {
            string fullPath = Path.GetFullPath(javaPath);
            if (!SafeFileSystem.FileExists(fullPath))
            {
                Logger.Warning("Java 執行檔不存在: {Path}", fullPath);
                return false;
            }

            if (HasReparsePointAlongPath(fullPath))
            {
                Logger.Warning("拒絕使用符號連結或 Reparse Point 之 Java 執行檔: {Path}", fullPath);
                return false;
            }

            return IsJavaExecutableName(Path.GetFileName(fullPath));
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "檢驗 Java 執行檔時發生例外");
            return false;
        }
    }

    /// <summary>驗證啟動參數引用的 JAR 與引數檔位於伺服器目錄內</summary>
    public static bool ValidateCommandInputs(string serverDirectory, IReadOnlyList<string> arguments)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);
        ArgumentNullException.ThrowIfNull(arguments);

        string stableServerDir = SafeFileSystem.ResolveStableDirectory(serverDirectory);
        return ValidateLaunchReferences(stableServerDir, arguments, requireExists: true);
    }

    /// <summary>檢查 <c>-jar</c> 與 <c>@argfile</c> 引用位於伺服器目錄內，並掃描引數檔內容；<paramref name="requireExists"/> 為 false 時允許引用檔尚不存在</summary>
    private static bool ValidateLaunchReferences(string stableServerDir, IReadOnlyList<string> arguments, bool requireExists)
    {
        for (int i = 0; i < arguments.Count; i++)
        {
            string arg = arguments[i];
            string? targetRelativePath = null;
            bool isArgumentFile = false;

            if (arg.StartsWith('@') && arg.Length > 1)
            {
                targetRelativePath = arg[1..].Trim('"');
                isArgumentFile = true;
            }
            else if (string.Equals(arg, "-jar", StringComparison.OrdinalIgnoreCase) && i + 1 < arguments.Count)
            {
                targetRelativePath = arguments[++i].Trim('"');
            }

            if (string.IsNullOrWhiteSpace(targetRelativePath))
            {
                continue;
            }

            // %~dp0 展開為腳本所在目錄（含結尾反斜線），即伺服器目錄
            if (targetRelativePath.StartsWith(ScriptDirectoryToken, StringComparison.OrdinalIgnoreCase))
            {
                targetRelativePath = targetRelativePath[ScriptDirectoryToken.Length..];
            }

            string targetFullPath;
            try
            {
                targetFullPath = Path.GetFullPath(targetRelativePath, stableServerDir);
            }
            catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException)
            {
                Logger.Warning(ex, "啟動參數引用之檔案路徑無效: {Target}", targetRelativePath);
                return false;
            }

            if (!SafeFileSystem.IsPathWithin(stableServerDir, targetFullPath, strict: false))
            {
                Logger.Warning("啟動參數引用之檔案路徑超出邊界: {Target} (伺服器目錄: {ServerDir})", targetFullPath, stableServerDir);
                return false;
            }

            if (SafeFileSystem.IsReparsePoint(targetFullPath))
            {
                Logger.Warning("啟動參數引用之檔案為 Reparse Point: {Target}", targetFullPath);
                return false;
            }

            if (!SafeFileSystem.FileExists(targetFullPath))
            {
                if (requireExists)
                {
                    Logger.Warning("啟動參數引用之檔案不存在: {Target}", targetFullPath);
                    return false;
                }

                continue;
            }

            if (isArgumentFile && !IsArgumentFileSafe(targetFullPath))
            {
                return false;
            }
        }

        return true;
    }

    /// <summary>java 會展開引數檔內容為參數，須同樣排除可執行外部命令的選項</summary>
    private static bool IsArgumentFileSafe(string argumentFilePath)
    {
        try
        {
            foreach (string rawLine in SafeFileSystem.ReadAllLines(argumentFilePath, Encoding.UTF8, MaxArgumentFileBytes))
            {
                ReadOnlySpan<char> line = rawLine.AsSpan().Trim();
                if (line.IsEmpty || line[0] == '#')
                {
                    continue;
                }

                foreach (string token in JvmOptionPolicy.NormalizeJvmArgs(line.ToString()))
                {
                    if (JvmOptionPolicy.IsCommandExecutionOption(token))
                    {
                        Logger.Warning("引數檔包含不允許的 JVM 選項: {Path}: {Option}", argumentFilePath, token);
                        return false;
                    }
                }
            }

            return true;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or InvalidDataException or ArgumentException or NotSupportedException)
        {
            Logger.Warning(ex, "讀取引數檔失敗: {Path}", argumentFilePath);
            return false;
        }
    }

    /// <summary>批次腳本內容是否安全合規（防範批次注入、路徑超出邊界、任意命令執行）</summary>
    public static bool ValidateScriptContent(string scriptPath, string serverDirectory)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(scriptPath);
        ArgumentException.ThrowIfNullOrWhiteSpace(serverDirectory);

        string stableServerDir = SafeFileSystem.ResolveStableDirectory(serverDirectory);
        string fullScriptPath;
        try
        {
            fullScriptPath = Path.GetFullPath(scriptPath, stableServerDir);
        }
        catch (Exception ex) when (ex is ArgumentException or NotSupportedException or PathTooLongException)
        {
            Logger.Warning(ex, "啟動腳本路徑無效: {ScriptPath}", scriptPath);
            return false;
        }

        if (!SafeFileSystem.IsPathWithin(stableServerDir, fullScriptPath, strict: false))
        {
            Logger.Warning("啟動腳本不在伺服器目錄內: {ScriptPath}", fullScriptPath);
            return false;
        }

        if (SafeFileSystem.IsReparsePoint(fullScriptPath) || !SafeFileSystem.FileExists(fullScriptPath))
        {
            Logger.Warning("啟動腳本不存在或為 Reparse Point: {ScriptPath}", fullScriptPath);
            return false;
        }

        try
        {
            string[] lines = SafeFileSystem.ReadAllLines(fullScriptPath, Encoding.UTF8, maxBytes: MaxArgumentFileBytes);
            foreach (string rawLine in lines)
            {
                string line = rawLine.Trim();
                if (string.IsNullOrEmpty(line))
                {
                    continue;
                }

                string lineToCheck = line;
                if (TryStripSafeChcpNulRedirection(line, out string safeStripped))
                {
                    lineToCheck = safeStripped;
                }

                // 1. 禁止命令串接、管線、重新導向與逸出符號
                if (lineToCheck.AsSpan().ContainsAny(StrictForbiddenBatchChars))
                {
                    Logger.Warning("啟動腳本包含不安全之命令串接或重新導向字元: {Line}", line);
                    return false;
                }

                // 2. 禁止延遲變數展開字元 !
                if (lineToCheck.Contains('!'))
                {
                    Logger.Warning("啟動腳本包含延遲變數展開字元 !: {Line}", line);
                    return false;
                }

                // 3. 變數展開只允許位置參數（%*、%~dp0、%1 等）
                if (HasUnsafePercentUsage(lineToCheck))
                {
                    Logger.Warning("啟動腳本包含未受信任之環境變數展開語法: {Line}", line);
                    return false;
                }

                // 4. 防範路徑穿越
                if (lineToCheck.Contains(".."))
                {
                    Logger.Warning("啟動腳本包含相對路徑穿越序列 ..: {Line}", line);
                    return false;
                }

                // 5. 結構化指令格式白名單檢驗
                if (!IsAllowedScriptCommand(lineToCheck, stableServerDir))
                {
                    Logger.Warning("啟動腳本包含未受信任之指令: {Line}", line);
                    return false;
                }
            }

            return true;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or InvalidDataException or ArgumentException or NotSupportedException)
        {
            Logger.Warning(ex, "讀取啟動腳本失敗: {ScriptPath}", fullScriptPath);
            return false;
        }
    }

    private static bool IsCommandWord(string line, string word) =>
        line.StartsWith(word, StringComparison.OrdinalIgnoreCase) && (line.Length == word.Length || char.IsWhiteSpace(line[word.Length]));

    private static bool IsAllowedScriptCommand(string line, string stableServerDir)
    {
        // 註解行
        if (line.StartsWith("::", StringComparison.Ordinal) ||
            IsCommandWord(line, "rem"))
        {
            return true;
        }

        // 回顯設定與訊息
        if (IsCommandWord(line, "@echo"))
        {
            return true;
        }

        if (IsCommandWord(line, "echo"))
        {
            return true;
        }

        // 標題與暫停
        if (IsCommandWord(line, "title"))
        {
            return true;
        }

        if (line.Equals("pause", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        // 字碼頁切換 (例如 chcp 65001)
        if (IsCommandWord(line, "chcp"))
        {
            return true;
        }

        // 工作目錄切換 (僅允許切換至目前目錄或腳本所在目錄 %~dp0)
        if (IsCommandWord(line, "cd"))
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

        // Java 啟動指令只接受絕對路徑
        if (TryExtractLaunchExecutable(line, out string exePath, out string arguments)
            && Path.IsPathFullyQualified(exePath))
        {
            try
            {
                // FileExists 會拒絕 reparse point，故直接檢查屬性；不存在的路徑回傳 false
                if (HasReparsePointAlongPath(exePath) || !ValidJavaExecutables.Contains(Path.GetFileName(exePath)))
                {
                    return false;
                }
            }
            catch (ArgumentException)
            {
                return false;
            }

            // 排除可執行外部命令的 JVM 選項（剝除引號後比對），並驗證 -jar／@argfile 位於伺服器目錄內
            return !JvmOptionPolicy.ContainsCommandExecutionOption(arguments)
                && ValidateLaunchReferences(stableServerDir, JvmOptionPolicy.NormalizeJvmArgs(arguments), requireExists: false);
        }

        return false;
    }

    private static bool HasReparsePointAlongPath(string path)
    {
        if (SafeFileSystem.IsReparsePoint(path))
        {
            return true;
        }

        for (string? parent = Path.GetDirectoryName(path); !string.IsNullOrEmpty(parent); parent = Path.GetDirectoryName(parent))
        {
            if (SafeFileSystem.IsReparsePoint(parent))
            {
                return true;
            }
        }

        return false;
    }

    private static bool TryExtractLaunchExecutable(string line, out string exePath, out string arguments)
    {
        exePath = string.Empty;
        arguments = string.Empty;
        ReadOnlySpan<char> span = line.AsSpan().Trim();
        if (span.IsEmpty)
        {
            return false;
        }

        if (span.StartsWith('@'))
        {
            span = span[1..].TrimStart();
        }

        if (span.IsEmpty)
        {
            return false;
        }

        if (span[0] == '"')
        {
            int closingQuote = span[1..].IndexOf('"');
            if (closingQuote < 0)
            {
                return false;
            }

            int endQuotePos = closingQuote + 1;
            if (endQuotePos + 1 < span.Length && !char.IsWhiteSpace(span[endQuotePos + 1]))
            {
                return false;
            }

            exePath = span[1..endQuotePos].Trim().ToString();
            arguments = span[(endQuotePos + 1)..].Trim().ToString();
            return !string.IsNullOrWhiteSpace(exePath);
        }

        int separatorIndex = span.IndexOfAny(CmdSeparators);
        if (separatorIndex >= 0 && span[separatorIndex] is not (' ' or '\t'))
        {
            // 未加引號之 , ; = 會被 cmd.exe 視為命令名稱結尾
            return false;
        }

        ReadOnlySpan<char> rawTarget = separatorIndex >= 0 ? span[..separatorIndex] : span;
        exePath = rawTarget.Trim().ToString();
        arguments = separatorIndex >= 0 ? span[separatorIndex..].Trim().ToString() : string.Empty;
        return !string.IsNullOrWhiteSpace(exePath);
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

    private static bool TryStripSafeChcpNulRedirection(string line, out string strippedLine)
    {
        strippedLine = line;
        ReadOnlySpan<char> span = line.AsSpan().Trim();
        if (span.StartsWith('@'))
        {
            span = span[1..].TrimStart();
        }

        if (!span.StartsWith("chcp", StringComparison.OrdinalIgnoreCase) ||
            (span.Length > 4 && !char.IsWhiteSpace(span[4])))
        {
            return false;
        }

        int gtIndex = span.IndexOf('>');
        if (gtIndex < 0)
        {
            return false;
        }

        // 僅允許恰好一個 '>' 且絕不允許其他禁止字元出現在重導向之前或之後
        if (span[(gtIndex + 1)..].Contains('>'))
        {
            return false;
        }

        ReadOnlySpan<char> target = span[(gtIndex + 1)..].Trim();
        if (!target.Equals("nul", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        ReadOnlySpan<char> commandPart = span[..gtIndex].Trim();
        ReadOnlySpan<char> afterChcp = commandPart[4..].Trim();
        foreach (char c in afterChcp)
        {
            if (!char.IsAsciiDigit(c))
            {
                return false;
            }
        }

        strippedLine = commandPart.ToString();
        return true;
    }
}
