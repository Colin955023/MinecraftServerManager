using System.Buffers;
using System.Collections.Frozen;
using System.Text;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.Core.Utilities;

/// <summary>集中產生 Minecraft 伺服器 JVM 啟動參數建議</summary>
public static class JvmOptionPolicy
{
    // 可執行外部命令、載入原生程式庫／代理或間接讀入其他選項檔的選項
    private static readonly string[] CommandExecutionOptionPrefixes =
    [
        "-XX:OnError",
        "-XX:OnOutOfMemoryError",
        "-XX:Flags",
        "-XX:OptionsFile",
        "-XX:VMOptionsFile",
        "-agentpath",
        "-agentlib",
        "-javaagent:",
        "-Xrun",
        "-Xbootclasspath",
    ];

    private static readonly FrozenSet<string> KnownGcOptions = FrozenSet.Create(
        StringComparer.OrdinalIgnoreCase,
        "-XX:+UseG1GC",
        "-XX:+UseZGC",
        "-XX:+UseShenandoahGC",
        "-XX:+UseParallelGC",
        "-XX:+UseParallelOldGC",
        "-XX:+UseSerialGC",
        "-XX:+UseConcMarkSweepGC",
        "-XX:+UseEpsilonGC");

    private static readonly SearchValues<char> ScriptUnsafeChars = SearchValues.Create("\r\n\0&|<>^%\"");

    /// <summary>參數是否為可執行任意外部命令、載入原生程式庫或引用參數檔的 JVM 選項；引號未閉合亦視為無效輸入</summary>
    public static bool IsCommandExecutionOption(ReadOnlySpan<char> argument)
    {
        ReadOnlySpan<char> trimmed = argument.Trim();
        if (!trimmed.ContainsAny('"', '\''))
        {
            // @argfile 會由 java 啟動器展開為任意參數
            return trimmed.StartsWith('@') || StartsWithBlockedPrefix(trimmed);
        }

        if (HasUnbalancedQuotes(trimmed))
        {
            return true;
        }

        string unquoted = StripQuotes(trimmed);
        return unquoted.StartsWith('@') || StartsWithBlockedPrefix(unquoted);
    }

    /// <summary>參數是否含換行、NUL 或批次特殊字元（寫入啟動腳本時會被 cmd 解析或展開）</summary>
    public static bool ContainsScriptUnsafeChars(ReadOnlySpan<char> argument) => argument.ContainsAny(ScriptUnsafeChars);

    /// <summary>參數是否不得寫入啟動腳本或引數檔（可執行外部命令或含批次特殊字元）</summary>
    public static bool IsRejectedCustomArgument(ReadOnlySpan<char> argument) =>
        ContainsScriptUnsafeChars(argument) || IsCommandExecutionOption(argument);

    /// <summary>命令列文字中是否含有可執行任意外部命令的 JVM 選項（供啟動腳本逐行檢查）</summary>
    public static bool ContainsCommandExecutionOption(ReadOnlySpan<char> commandLine) =>
        ContainsBlockedPrefix(commandLine.ContainsAny('"', '\'') ? StripQuotes(commandLine) : commandLine);

    /// <summary>將自訂 JVM 參數依引號規則切為清單（含空白的引號路徑視為單一參數）；引號未閉合之剩餘內容保留原文為單一參數，由 <see cref="IsCommandExecutionOption"/> 拒絕</summary>
    public static IReadOnlyList<string> NormalizeJvmArgs(string? rawArgs)
    {
        if (string.IsNullOrWhiteSpace(rawArgs))
        {
            return [];
        }

        var tokens = new List<string>();
        var current = new StringBuilder();
        char quote = '\0';
        int quoteStart = -1;
        bool hasToken = false;

        for (int i = 0; i < rawArgs.Length; i++)
        {
            char c = rawArgs[i];
            if (quote != '\0')
            {
                if (c == quote)
                {
                    quote = '\0';
                }
                else
                {
                    current.Append(c);
                }

                continue;
            }

            if (c is '\'' or '"')
            {
                quote = c;
                quoteStart = i;
                hasToken = true;
                continue;
            }

            if (char.IsWhiteSpace(c))
            {
                if (hasToken && current.Length > 0)
                {
                    tokens.Add(current.ToString());
                }

                current.Clear();
                hasToken = false;
                continue;
            }

            current.Append(c);
            hasToken = true;
        }

        if (quote != '\0')
        {
            // 未閉合：以原文保留引號，確保後續檢查一律拒絕
            int tokenStart = quoteStart;
            while (tokenStart > 0 && !char.IsWhiteSpace(rawArgs[tokenStart - 1]))
            {
                tokenStart--;
            }

            tokens.Add(rawArgs[tokenStart..].TrimEnd());
        }
        else if (hasToken && current.Length > 0)
        {
            tokens.Add(current.ToString());
        }

        return tokens;
    }

    /// <summary>參數中是否已包含 GC 選項</summary>
    public static bool HasGcOption(IEnumerable<string> args)
    {
        ArgumentNullException.ThrowIfNull(args);
        FrozenSet<string>.AlternateLookup<ReadOnlySpan<char>> lookup = KnownGcOptions.GetAlternateLookup<ReadOnlySpan<char>>();
        foreach (string? arg in args)
        {
            if (arg is null)
            {
                continue;
            }

            ReadOnlySpan<char> trimmed = arg.AsSpan().Trim();
            bool matched = !trimmed.ContainsAny('"', '\'')
                ? lookup.Contains(trimmed)
                : KnownGcOptions.Contains(StripQuotes(trimmed));
            if (matched)
            {
                return true;
            }
        }

        return false;
    }

    /// <summary>取得建議的 JVM 參數與其對應的繁體中文說明</summary>
    public static IReadOnlyList<(string Option, string Description)> GetRecommendedJvmArgsDetails(
        int? javaMajor,
        int memoryMaxMb,
        LoaderKind loaderType = LoaderKind.Unknown)
    {
        var args = new List<(string Option, string Description)>();

        if (javaMajor.HasValue && javaMajor.Value >= 21)
        {
            // ZGC (Java 21+)
            args.Add(("-XX:+UseZGC", "啟用 ZGC 低延遲垃圾回收器"));
            if (javaMajor.Value < 23)
            {
                // Java 23 起分代 ZGC 為預設，該旗標已棄用
                args.Add(("-XX:+ZGenerational", "啟用分代 ZGC 大幅降低 CPU 使用率並減少記憶體停頓"));
            }
            args.Add(("-XX:+AlwaysPreTouch", "啟動時預先配置實體記憶體分頁以避免執行時延遲"));
            args.Add(("-XX:+DisableExplicitGC", "禁止模組手動觸發 GC 避免非預期停頓"));
        }
        else
        {
            // G1GC (Aikar's Flags)
            args.Add(("-XX:+UseG1GC", "啟用 G1GC 垃圾回收器平衡吞吐量與延遲"));
            args.Add(("-XX:+ParallelRefProcEnabled", "啟用多執行緒處理弱參考減少暫停時間"));
            args.Add(("-XX:MaxGCPauseMillis=200", "設定最大 GC 暫停時間目標為 200 毫秒"));
            args.Add(("-XX:+UnlockExperimentalVMOptions", "解鎖實驗性 JVM 參數以允許進階效能調校"));
            args.Add(("-XX:+DisableExplicitGC", "禁止手動觸發 System.gc"));
            args.Add(("-XX:+AlwaysPreTouch", "啟動時預先配置實體記憶體分頁"));
            args.Add(("-XX:G1NewSizePercent=30", "設定年輕代初始大小佔總堆積的 30%"));
            args.Add(("-XX:G1MaxNewSizePercent=40", "設定年輕代最大佔總堆積的 40%"));

            if (memoryMaxMb >= 12288)
            {
                args.Add(("-XX:G1HeapRegionSize=16M", "設定 G1GC 區域大小為 16M（大記憶體最佳化）"));
            }
            else
            {
                args.Add(("-XX:G1HeapRegionSize=8M", "設定 G1GC 區域大小為 8M"));
            }

            args.Add(("-XX:G1ReservePercent=20", "保留 20% 記憶體作為 GC 緩衝防止晉升失敗"));
            args.Add(("-XX:G1HeapWastePercent=5", "允許浪費 5% 記憶體以縮短回收時間"));
            args.Add(("-XX:G1MixedGCCountTarget=4", "設定混合 GC 目標次數分攤回收壓力"));
            args.Add(("-XX:InitiatingHeapOccupancyPercent=15", "提早至 15% 佔用率即開始並行標記適合 Minecraft"));
            args.Add(("-XX:G1MixedGCLiveThresholdPercent=90", "提高舊生代回收門檻值增加回收效率"));
            args.Add(("-XX:G1RSetUpdatingPauseTimePercent=5", "限制更新記憶集時間比例為 5% 縮短暫停時間"));
            args.Add(("-XX:SurvivorRatio=32", "增大 Survivor 區比例減少物件過早晉升"));
            args.Add(("-XX:+PerfDisableSharedMem", "停用效能監控資料共享記憶體防止磁碟延遲"));
            args.Add(("-XX:MaxTenuringThreshold=1", "設定物件最大晉升年齡為 1 加速回收短命物件"));
            args.Add(("-Dusing.aikars.flags=https://mcflags.emc.gs", "Aikar 參數識別標記屬性"));
            args.Add(("-Daikars.new.flags=true", "標記使用新版 Aikar 參數"));
        }

        if (javaMajor.HasValue && javaMajor.Value >= 22)
        {
            args.Add(("--enable-native-access=ALL-UNNAMED", "允許未命名模組呼叫原生方法消除 Java 22+ 警告"));
        }

        if (loaderType is LoaderKind.Forge or LoaderKind.NeoForge)
        {
            args.Add(("-Dfml.readTimeout=120", "增加 FML 讀取逾時至 120 秒避免大型模組包斷線"));
            args.Add(("-Dfml.queryResult=confirm", "自動確認 FML 模組變更警告避免啟動卡住"));
        }

        return args;
    }

    /// <summary>依記憶體與 Java 版本產生 JVM 建議參數</summary>
    public static IReadOnlyList<string> RecommendGcArgs(
        int memoryMaxMb,
        int? javaMajor = null,
        LoaderKind loaderType = LoaderKind.Unknown,
        IEnumerable<string>? existingArgs = null)
    {
        if (existingArgs is not null && HasGcOption(existingArgs))
        {
            return [];
        }

        var details = GetRecommendedJvmArgsDetails(javaMajor, memoryMaxMb, loaderType);
        string[] result = new string[details.Count];
        for (int i = 0; i < details.Count; i++)
        {
            result[i] = details[i].Option;
        }

        return result;
    }

    private static bool StartsWithBlockedPrefix(ReadOnlySpan<char> argument)
    {
        foreach (string prefix in CommandExecutionOptionPrefixes)
        {
            if (argument.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }

        return false;
    }

    private static bool ContainsBlockedPrefix(ReadOnlySpan<char> text)
    {
        foreach (string prefix in CommandExecutionOptionPrefixes)
        {
            if (text.Contains(prefix, StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
        }

        return false;
    }

    private static bool HasUnbalancedQuotes(ReadOnlySpan<char> text)
    {
        char quote = '\0';
        for (int i = 0; i < text.Length; i++)
        {
            char c = text[i];
            if (quote != '\0')
            {
                if (c == quote)
                {
                    quote = '\0';
                }

                continue;
            }

            if (c == '"' || (c == '\'' && (i == 0 || text[i - 1] is '=' or ':')))
            {
                quote = c;
            }
        }

        return quote != '\0';
    }

    /// <summary>移除全部單雙引號，避免以引號拆分選項名稱規避檢查</summary>
    private static string StripQuotes(ReadOnlySpan<char> text)
    {
        if (!text.ContainsAny('"', '\''))
        {
            return text.ToString();
        }

        var sb = new StringBuilder(text.Length);
        foreach (char c in text)
        {
            if (c is not ('"' or '\''))
            {
                sb.Append(c);
            }
        }

        return sb.ToString();
    }
}
