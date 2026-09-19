namespace MinecraftServerManager.Core.Utilities;

/// <summary>
/// 集中產生 Minecraft 伺服器 JVM 啟動參數建議
/// </summary>
public static class JvmOptionPolicy
{
    private const string GcOptionPrefix = "-XX:+Use";

    /// <summary>
    /// 將使用者自訂 JVM 參數正規化為清單
    /// </summary>
    public static IReadOnlyList<string> NormalizeJvmArgs(string? rawArgs)
    {
        if (string.IsNullOrWhiteSpace(rawArgs))
        {
            return [];
        }

        var result = new List<string>();
        string[] parts = rawArgs.Split([' ', '\t', '\r', '\n'], StringSplitOptions.RemoveEmptyEntries);
        foreach (string part in parts)
        {
            string trimmed = part.Trim();
            if (!string.IsNullOrEmpty(trimmed))
            {
                result.Add(trimmed);
            }
        }

        return result;
    }

    /// <summary>
    /// 檢查參數中是否已包含 GC 選項
    /// </summary>
    public static bool HasGcOption(IEnumerable<string> args) => args.Any(arg => arg.StartsWith(GcOptionPrefix, StringComparison.OrdinalIgnoreCase) && arg.EndsWith("GC", StringComparison.OrdinalIgnoreCase));

    /// <summary>
    /// 取得建議的 JVM 參數與其對應的繁體中文說明
    /// </summary>
    public static IReadOnlyList<(string Option, string Description)> GetRecommendedJvmArgsDetails(
        int? javaMajor,
        int memoryMaxMb,
        string loaderType = "")
    {
        var args = new List<(string Option, string Description)>();

        if (javaMajor.HasValue && javaMajor.Value >= 21)
        {
            // ZGC (Java 21+)
            args.Add(("-XX:+UseZGC", "啟用 ZGC 低延遲垃圾回收器"));
            if (javaMajor.Value < 24)
            {
                args.Add(("-XX:+ZGenerational", "啟用分代 ZGC 大幅降低 CPU 使用率並減少記憶體停頓"));
            }
            args.Add(("-XX:+AlwaysPreTouch", "啟動時預先配置實體記憶體分頁以避免執行時延遲"));
            args.Add(("-XX:+DisableExplicitGC", "禁止模組手動觸發 GC 避免非預期卡頓"));
        }
        else
        {
            // G1GC (Aikar's Flags)
            args.Add(("-XX:+UseG1GC", "啟用 G1GC 垃圾回收器平衡吞吐量與延遲"));
            args.Add(("-XX:+ParallelRefProcEnabled", "啟用多執行緒處理弱引用減少暫停時間"));
            args.Add(("-XX:MaxGCPauseMillis=200", "設定最大 GC 暫停時間目標為 200 毫秒"));
            args.Add(("-XX:+UnlockExperimentalVMOptions", "解鎖實驗性 JVM 參數以允許進階效能調校"));
            args.Add(("-XX:+DisableExplicitGC", "禁止手動觸發 System.gc"));
            args.Add(("-XX:+AlwaysPreTouch", "啟動時預先配置實體記憶體分頁"));
            args.Add(("-XX:G1NewSizePercent=30", "設定年輕代初始大小佔總堆疊的 30%"));
            args.Add(("-XX:G1MaxNewSizePercent=40", "設定年輕代最大佔總堆疊的 40%"));

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
            args.Add(("-XX:G1MixedGCLiveThresholdPercent=90", "提高舊生代回收閾值增加回收效率"));
            args.Add(("-XX:G1RSetUpdatingPauseTimePercent=5", "限制更新記憶集時間比例為 5% 縮短暫停時間"));
            args.Add(("-XX:SurvivorRatio=32", "增大 Survivor 區比例減少物件過早晉升"));
            args.Add(("-XX:+PerfDisableSharedMem", "停用效能監控資料共享記憶體防止磁碟延遲"));
            args.Add(("-XX:MaxTenuringThreshold=1", "設定物件最大晉升年齡為 1 加速回收短命物件"));
            args.Add(("-Dusing.aikars.flags=https://mcflags.emc.gs", "Aikar 參數標識屬性"));
            args.Add(("-Daikars.new.flags=true", "標記使用新版 Aikar 參數"));
        }

        if (javaMajor.HasValue && javaMajor.Value >= 22)
        {
            args.Add(("--enable-native-access=ALL-UNNAMED", "允許未命名模組呼叫原生方法消除 Java 22+ 警告"));
        }

        string normalizedLoader = loaderType.Trim().ToLowerInvariant();
        if (normalizedLoader is "forge" or "neoforge")
        {
            args.Add(("-Dfml.readTimeout=120", "增加 FML 讀取逾時至 120 秒避免大型模組包斷線"));
            args.Add(("-Dfml.queryResult=confirm", "自動確認 FML 模組變更警告避免啟動卡住"));
        }

        return args;
    }

    /// <summary>
    /// 依記憶體與 Java 版本產生 JVM 建議參數
    /// </summary>
    public static IReadOnlyList<string> RecommendGcArgs(
        int memoryMaxMb,
        int? javaMajor = null,
        string loaderType = "",
        IEnumerable<string>? existingArgs = null)
    {
        string[] existing = existingArgs?.ToArray() ?? [];
        if (HasGcOption(existing))
        {
            return [];
        }

        var details = GetRecommendedJvmArgsDetails(javaMajor, memoryMaxMb, loaderType);
        return details.Select(d => d.Option).ToArray();
    }
}
