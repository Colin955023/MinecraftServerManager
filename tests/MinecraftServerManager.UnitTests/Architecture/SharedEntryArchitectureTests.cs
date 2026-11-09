using System.Text.RegularExpressions;
using System.Xml.Linq;
using Xunit;

namespace MinecraftServerManager.UnitTests.Architecture;
/// <summary>
/// 原生架構測試（A1～A30 規則）：
/// 規定「共用工具入口」與架構分層界線；規則編號與 docs/TECHNICAL_OVERVIEW.md 第 11 節對照表一一對應。
/// 零額外第三方相依、純原生靜態原始碼掃描與專案結構檢查。
/// </summary>
public sealed partial class SharedEntryArchitectureTests
{
    #region 輔助方法

    private static void AssertNoViolations(List<SourceViolation> violations, string ruleId)
    {
        if (violations.Count == 0)
        {
            return;
        }

        string details = string.Join(
            Environment.NewLine,
            violations.Select(v => $"  - [{v.RuleId}] {v.FilePath}:{v.LineNumber} -> {v.LineContent}"));

        Assert.Fail($"架構規則 [{ruleId}] 檢查失敗，共發現 {violations.Count} 處違規呼叫：{Environment.NewLine}{details}");
    }

    private static List<string> GetProjectReferences(string csprojPath)
    {
        if (!File.Exists(csprojPath))
        {
            throw new FileNotFoundException($"找不到專案檔：{csprojPath}");
        }

        var doc = XDocument.Load(csprojPath);
        return [.. doc.Descendants("ProjectReference")
            .Select(x => (string?)x.Attribute("Include") ?? string.Empty)
            .Where(x => !string.IsNullOrWhiteSpace(x))];
    }

    #endregion

    #region 架構規則測試（A1～A30）

    /// <summary>
    /// A1：檔案與目錄存在性、走訪、建立、刪除與串流 I/O 一律經由 SafeFileSystem / AtomicFileWriter
    /// 禁止直接呼叫 File.、Directory.、FileInfo、DirectoryInfo、FileStream、DriveInfo
    /// 規範：專案規範「共用工具入口」（檔案與目錄）、「檔案系統與安全邊界」；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A1。
    /// </summary>
    [Fact]
    public void A1_FileSystemDirectAccess_ShouldOnlyBeUsedInWhitelistedPaths()
    {
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A1Regex(),
            "A1",
            "檔案系統 I/O 必須統一透過 SafeFileSystem 或 AtomicFileWriter",
            path =>
                path.StartsWith("src/MinecraftServerManager.Infrastructure/FileSystem/", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.Infrastructure/Utilities/AtomicFileWriter.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.Infrastructure/Logging/RotatingFileLoggerProvider.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.Infrastructure/Http/HttpDownloadClient.cs", StringComparison.OrdinalIgnoreCase));

        AssertNoViolations(violations, "A1");
    }

    /// <summary>
    /// A2：ZIP / JAR 讀寫、解壓與單一 ZipArchiveEntry 串流讀取一律經由 SafeZipArchive
    /// 禁止直接呼叫 ZipFile.、建構 new ZipArchive 或直接對 ZipArchiveEntry 呼叫 .Open()
    /// 規範：專案規範「共用工具入口」（ZIP／JAR）、「檔案系統與安全邊界」；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A2。
    /// </summary>
    [Fact]
    public void A2_ZipDirectAccess_ShouldOnlyBeUsedInWhitelistedPaths()
    {
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A2Regex(),
            "A2",
            "壓縮檔操作與單一項目讀取必須透過 SafeZipArchive（OpenXmlSpreadsheetBuilder 僅限記憶體建構例外）",
            path =>
                string.Equals(path, "src/MinecraftServerManager.Infrastructure/FileSystem/SafeZipArchive.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.Infrastructure/Utilities/OpenXmlSpreadsheetBuilder.cs", StringComparison.OrdinalIgnoreCase));

        AssertNoViolations(violations, "A2");
    }

    /// <summary>
    /// A3：外部行程生命週期與 Shell 呼叫一律經由 ProcessRunner
    /// 禁止直接呼叫 Process.Start、new Process、ProcessStartInfo
    /// 規範：專案規範「共用工具入口」（外部行程）；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A3。
    /// </summary>
    [Fact]
    public void A3_ProcessDirectAccess_ShouldOnlyBeUsedInWhitelistedPaths()
    {
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A3Regex(),
            "A3",
            "外部行程管理必須統一由 ProcessRunner 負責",
            path =>
                string.Equals(path, "src/MinecraftServerManager.Infrastructure/Process/ProcessRunner.cs", StringComparison.OrdinalIgnoreCase));

        AssertNoViolations(violations, "A3");
    }

    /// <summary>
    /// A4：共用 HttpClient 與 Handler 僅得由組合根建立，外部通訊經由 IHttpPort
    /// 禁止 new HttpClient、SocketsHttpHandler、HttpClientHandler
    /// 規範：專案規範「共用工具入口」（HTTP／下載）；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A4。
    /// </summary>
    [Fact]
    public void A4_HttpClientDirectInstantiation_ShouldOnlyBeUsedInAppCompositionRoot()
    {
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A4Regex(),
            "A4",
            "HttpClient 與處理常式僅得於 AppCompositionRoot 集中建立",
            path =>
                string.Equals(path, "src/MinecraftServerManager.App/AppCompositionRoot.cs", StringComparison.OrdinalIgnoreCase));

        AssertNoViolations(violations, "A4");
    }

    /// <summary>
    /// A5：JSON 序列化與解析一律透過 JsonCodec，Core 連接埠僅得保留最小回退
    /// 禁止 JsonSerializer.、JsonDocument.、new JsonSerializerOptions
    /// 規範：專案規範「共用工具入口」（JSON）、「資料序列化」；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A5。
    /// </summary>
    [Fact]
    public void A5_JsonDirectAccess_ShouldOnlyBeUsedInWhitelistedPaths()
    {
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A5Regex(),
            "A5",
            "JSON 解析與序列化必須透過 JsonCodec（IHttpPort 僅保留最小回退）",
            path =>
                string.Equals(path, "src/MinecraftServerManager.Infrastructure/Utilities/JsonCodec.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.Core/Ports/IHttpPort.cs", StringComparison.OrdinalIgnoreCase));

        AssertNoViolations(violations, "A5");
    }

    /// <summary>
    /// A6：正規表示式一律採用 [GeneratedRegex] Source Generator 編譯期產生
    /// 禁止 new Regex( 或 Regex.IsMatch / Match / Replace / Split 靜態呼叫
    /// 規範：專案規範「.NET 10 高階原生 API 與現代化慣用語」（正規表示式）；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A6。
    /// </summary>
    [Fact]
    public void A6_RegexDirectInstantiationOrStaticCall_ShouldBeZero_MustUseGeneratedRegex()
    {
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A6Regex(),
            "A6",
            "正規表示式一律使用 [GeneratedRegex]，禁止執行期動態建構或靜態方法呼叫",
            _ => false);

        AssertNoViolations(violations, "A6");
    }

    /// <summary>
    /// A7：訊息框、檔案與目錄選取器、對話方塊、UI 執行緒派送與計時器一律透過 IUiService
    /// 禁止直接呼叫 MessageBoxW、FileOpenPicker、FileSavePicker、FolderPicker、DispatcherTimer、DispatcherQueueTimer、new ContentDialog
    /// 規範：專案規範「UI 與 MVVM 規範」、專案規範「共用工具入口」（UI、對話框與計時器）；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A7。
    /// </summary>
    [Fact]
    public void A7_UiDirectAccess_ShouldOnlyBeUsedInWhitelistedPaths()
    {
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A7Regex(),
            "A7",
            "UI 派送、檔案選取器、對話方塊、訊息框與計時器必須由 IUiService (WinUiService) 統一管理",
            path =>
                string.Equals(path, "src/MinecraftServerManager.App/Services/WinUiService.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.App/App.xaml.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.App/MainWindow.xaml.cs", StringComparison.OrdinalIgnoreCase) ||
                path.StartsWith("src/MinecraftServerManager.App/Views/", StringComparison.OrdinalIgnoreCase));

        AssertNoViolations(violations, "A7");
    }

    /// <summary>
    /// A8：專案全境嚴格禁止出現 unsafe 區塊或關鍵字
    /// 規範：專案規範「語言與框架標準」（unsafe 規範）；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A8。
    /// </summary>
    [Fact]
    public void A8_UnsafeCode_ShouldBeZeroAcrossSolution()
    {
        var files = SourceScanner.GetSourceFiles("src")
            .Concat(SourceScanner.GetSourceFiles("tests"));

        var violations = SourceScanner.ScanViolations(
            files,
            A8Regex(),
            "A8",
            "專案全境嚴格禁止 unsafe 程式碼",
            _ => false);

        AssertNoViolations(violations, "A8");
    }

    /// <summary>
    /// A9：專案相依性與命名空間界線
    /// 1. 檢查專案參照（Project References）
    /// 2. 檢查 Domain 與 Core 之 using 命名空間界線
    /// 規範：專案規範「架構與專案結構」（相依方向）；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A9。
    /// </summary>
    [Fact]
    public void A9_LayerDependencies_ShouldRespectArchitectureBoundaries()
    {
        string domainCsproj = Path.Combine(SourceScanner.SolutionRoot, "src", "MinecraftServerManager.Domain", "MinecraftServerManager.Domain.csproj");
        string coreCsproj = Path.Combine(SourceScanner.SolutionRoot, "src", "MinecraftServerManager.Core", "MinecraftServerManager.Core.csproj");
        string infraCsproj = Path.Combine(SourceScanner.SolutionRoot, "src", "MinecraftServerManager.Infrastructure", "MinecraftServerManager.Infrastructure.csproj");

        var domainRefs = GetProjectReferences(domainCsproj);
        Assert.True(domainRefs.Count == 0, $"Domain 專案不得參照任何外部專案，目前參照：{string.Join(", ", domainRefs)}");

        var coreRefs = GetProjectReferences(coreCsproj);
        Assert.True(
            coreRefs.All(r => r.Contains("MinecraftServerManager.Domain", StringComparison.OrdinalIgnoreCase)),
            $"Core 專案僅得參照 Domain 專案，目前參照：{string.Join(", ", coreRefs)}");

        var infraRefs = GetProjectReferences(infraCsproj);
        Assert.False(
            infraRefs.Any(r => r.Contains("MinecraftServerManager.App", StringComparison.OrdinalIgnoreCase)),
            $"Infrastructure 專案不得逆向參照 App 專案，目前參照：{string.Join(", ", infraRefs)}");

        var domainFiles = SourceScanner.GetSourceFiles("src/MinecraftServerManager.Domain");
        var domainViolations = SourceScanner.ScanViolations(
            domainFiles,
            A9DomainUsingRegex(),
            "A9",
            "Domain 核心領域層不得 using System.IO、System.Net 或 System.Diagnostics",
            _ => false);
        AssertNoViolations(domainViolations, "A9-Domain");

        var coreFiles = SourceScanner.GetSourceFiles("src/MinecraftServerManager.Core");
        var coreViolations = SourceScanner.ScanViolations(
            coreFiles,
            A9CoreUsingRegex(),
            "A9",
            "Core 業務核心層不得 using System.IO、System.Net.Http 或 System.Diagnostics",
            _ => false);
        AssertNoViolations(coreViolations, "A9-Core");
    }

    /// <summary>
    /// A10：App/ViewModels 不得持有原生 Process 實體、不得直接呼叫 File./Directory.、不得 new HttpClient
    /// 規範：專案規範「UI 與 MVVM 規範」、專案規範「共用工具入口」（外部行程、HTTP、檔案與目錄）；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A10。
    /// </summary>
    [Fact]
    public void A10_ViewModelBoundaries_ShouldNotHoldProcessOrDirectIoOrHttpClient()
    {
        var viewModelFiles = SourceScanner.GetSourceFiles("src/MinecraftServerManager.App/ViewModels");
        var violations = SourceScanner.ScanViolations(
            viewModelFiles,
            A10Regex(),
            "A10",
            "ViewModel 嚴禁持有原生 Process 實體、直接實體檔案 I/O 或建構 HttpClient",
            _ => false);

        AssertNoViolations(violations, "A10");
    }

    /// <summary>
    /// A11：檔案與資料雜湊一律集中於 HashCalculator，僅 HTTP 續傳下載可在串流中同步計算雜湊
    /// 禁止直接呼叫或建構 SHA256、SHA1、MD5、SHA512、IncrementalHash
    /// 規範：專案規範「共用工具入口」（雜湊）；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A11。
    /// </summary>
    [Fact]
    public void A11_HashDirectAccess_ShouldOnlyBeUsedInWhitelistedPaths()
    {
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A11Regex(),
            "A11",
            "檔案與資料雜湊計算必須統一經由 HashCalculator（HttpDownloadClient 僅限續傳下載串流例外）",
            path =>
                string.Equals(path, "src/MinecraftServerManager.Infrastructure/Utilities/HashCalculator.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.Infrastructure/Http/HttpDownloadClient.cs", StringComparison.OrdinalIgnoreCase));

        AssertNoViolations(violations, "A11");
    }

    /// <summary>
    /// A12：記錄管線一律由 AppLogging 與 ComponentLogger 集中管理，禁止直呼 Console/Trace/Debug 輸出
    /// 規範：專案規範「共用工具入口」（記錄）；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A12。
    /// </summary>
    [Fact]
    public void A12_ConsoleOrDiagnosticsLoggingDirectAccess_ShouldBeZeroAcrossSrc()
    {
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A12Regex(),
            "A12",
            "記錄輸出必須統一由 AppLogging 與 ComponentLogger 管理，禁止直呼 Console、Trace 或 Debug 輸出",
            _ => false);

        AssertNoViolations(violations, "A12");
    }

    /// <summary>
    /// A13：App/ViewModels 內禁止出現裸 _ = XxxAsync( 或 _ = Task.Run( 發射後不管呼叫，必須統一呼叫 ViewModelBase.RunSafeAsync
    /// 規範：專案規範「例外處理與 Catch 規範」（禁止無聲失敗）；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A13。
    /// </summary>
    [Fact]
    public void A13_ViewModels_MustNotContainDiscardedAsyncCalls()
    {
        var files = SourceScanner.GetSourceFiles("src/MinecraftServerManager.App/ViewModels");
        var violations = SourceScanner.ScanViolations(
            files,
            A13Regex(),
            "A13",
            "ViewModel 內禁止出現裸 _ = XxxAsync(，必須經由 ViewModelBase.RunSafeAsync 統一處理例外與記錄",
            _ => false);

        AssertNoViolations(violations, "A13");
    }

    /// <summary>
    /// A14：系統提示音效一律經由 AudioFeedback 工具
    /// 禁止直接呼叫 SystemSounds 或 new SoundPlayer
    /// 規範：專案規範「共用工具入口」（系統提示音效）；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A14。
    /// </summary>
    [Fact]
    public void A14_SoundDirectAccess_ShouldOnlyBeUsedInAudioFeedback()
    {
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A14Regex(),
            "A14",
            "系統提示音效必須統一由 AudioFeedback 提供",
            path =>
                string.Equals(path, "src/MinecraftServerManager.App/Services/AudioFeedback.cs", StringComparison.OrdinalIgnoreCase));

        AssertNoViolations(violations, "A14");
    }

    /// <summary>
    /// A15：全專案嚴格禁止使用 Debug 或 Trace 等級輸出日誌
    /// 禁止 Logger.Debug(、Logger.Trace(、LogDebug(、LogTrace(
    /// 規範：專案規範「日誌等級與正式發布規範」；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A15。
    /// </summary>
    [Fact]
    public void A15_LogLevel_MustNotContainDebugOrTrace()
    {
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A15Regex(),
            "A15",
            "全專案嚴格禁止使用 Debug 或 Trace 等級輸出日誌（常規使用 Information，非致命異常使用 Warning，嚴重錯誤使用 Error）",
            _ => false);

        AssertNoViolations(violations, "A15");
    }

    /// <summary>
    /// A16：視窗標題列主題、系統強調色探測、模態父子視窗綁定與視窗圖示載入一律集中於專屬統一工具
    /// 規範：專案規範「共用工具入口」（視窗外觀與系統強調色）；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A16。
    /// </summary>
    [Fact]
    public void A16_WindowAndThemeNativeHelpers_ShouldOnlyBeUsedInDesignatedServices()
    {
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A16Regex(),
            "A16",
            "視窗標題列、系統強調色、模態視窗綁定與圖示資源載入必須統一由專屬服務管理",
            path =>
                string.Equals(path, "src/MinecraftServerManager.App/Services/TitleBarThemeHelper.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.App/Services/AccentColorService.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.App/Services/ModalWindowHost.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.App/Services/WindowIconHelper.cs", StringComparison.OrdinalIgnoreCase));

        AssertNoViolations(violations, "A16");
    }

    /// <summary>
    /// A17：模組 JAR 副檔名剝除（.jar.disabled）與 Windows 保留裝置名稱檢查（CLOCK$ / LPT / COM）
    /// 一律集中於 ModHelpers 與 ServerName，禁止於其他檔案重複實作
    /// 規範：專案規範「共用工具入口」（檔案與目錄：保留裝置名稱；模組檔名）；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A17。
    /// </summary>
    [Fact]
    public void A17_ModFilenameAndDeviceNameHelpers_ShouldOnlyBeImplementedInDesignatedSharedTools()
    {
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A17Regex(),
            "A17",
            "Windows 保留裝置名稱檢查必須統一使用 ServerName.IsWindowsDeviceName，模組檔名與雜湊挑選必須統一使用 ModHelpers",
            path =>
                string.Equals(path, "src/MinecraftServerManager.Domain/ValueObjects/ServerName.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.Core/Mods/ModHelpers.cs", StringComparison.OrdinalIgnoreCase),
            preserveStrings: true);

        AssertNoViolations(violations, "A17");
    }

    /// <summary>
    /// A18：禁止無型別 catch（catch { }），必須明確捕獲 Exception 並記錄或以 when 過濾，避免吞沒取消訊號
    /// 規範：專案規範「例外處理與 Catch 規範」；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A18。
    /// </summary>
    [Fact]
    public void A18_UntypedCatch_ShouldBeZeroAcrossSrc()
    {
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A18Regex(),
            "A18",
            "例外捕獲必須指定型別（如 catch (Exception ex) when (ex is not OperationCanceledException)）並記錄日誌或通知使用者",
            _ => false);

        AssertNoViolations(violations, "A18");
    }

    /// <summary>
    /// A19：模組檔案 .jar／.jar.disabled 副檔名判斷與組合一律使用 ModHelpers（IsJarFileName／IsModFileName／ToDisabledModFileName）
    /// 規範：專案規範「共用工具入口」（模組檔名）；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A19。
    /// </summary>
    [Fact]
    public void A19_ModFileExtensionChecks_ShouldOnlyBeImplementedInModHelpers()
    {
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A19Regex(),
            "A19",
            "模組檔案副檔名判斷必須統一使用 ModHelpers（Domain 層 OnlineModVersion 因相依方向例外）",
            path =>
                string.Equals(path, "src/MinecraftServerManager.Core/Mods/ModHelpers.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.Domain/Mods/OnlineModVersion.cs", StringComparison.OrdinalIgnoreCase),
            preserveStrings: true);

        AssertNoViolations(violations, "A19");
    }

    /// <summary>
    /// A20：Minecraft 官方與 PaperMC 版本中繼資料端點、版本快取檔名一律由 MojangVersionCatalog 持有
    /// 規範：專案規範「共用工具入口」（Minecraft／PaperMC 版本中繼資料）、「Java Major 需求判定原則」；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A20。
    /// </summary>
    [Fact]
    public void A20_MojangAndPaperVersionMetadata_ShouldOnlyBeDefinedInMojangVersionCatalog()
    {
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A20Regex(),
            "A20",
            "版本快取檔名、Mojang Manifest 與 PaperMC API 端點必須統一由 MojangVersionCatalog 提供",
            path =>
                string.Equals(path, "src/MinecraftServerManager.Infrastructure/Loaders/MojangVersionCatalog.cs", StringComparison.OrdinalIgnoreCase),
            preserveStrings: true);

        AssertNoViolations(violations, "A20");
    }

    /// <summary>
    /// A21：P/Invoke（LibraryImport／DllImport）只允許宣告於指定之原生互通輔助類別
    /// 規範：專案規範「共用工具入口」（P/Invoke）；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A21。
    /// </summary>
    [Fact]
    public void A21_NativeInterop_ShouldOnlyBeDeclaredInDesignatedHelpers()
    {
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A21Regex(),
            "A21",
            "原生 Win32 互通宣告必須集中於 App.xaml.cs、AudioFeedback、TitleBarThemeHelper、ModalWindowHost、WindowIconHelper、WindowLayoutHelper",
            path =>
                string.Equals(path, "src/MinecraftServerManager.App/App.xaml.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.App/Services/AudioFeedback.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.App/Services/TitleBarThemeHelper.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.App/Services/ModalWindowHost.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.App/Services/WindowIconHelper.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.App/Services/WindowLayoutHelper.cs", StringComparison.OrdinalIgnoreCase));

        AssertNoViolations(violations, "A21");
    }

    /// <summary>
    /// A22：系統資料夾（使用者設定檔、LocalAppData、Program Files、System32、暫存目錄）查詢一律經由 RuntimePaths
    /// 規範：專案規範「共用工具入口」（系統資料夾路徑）；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A22。
    /// </summary>
    [Fact]
    public void A22_SpecialFolderLookups_ShouldOnlyBeUsedInRuntimePaths()
    {
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A22Regex(),
            "A22",
            "系統資料夾路徑查詢必須統一使用 RuntimePaths",
            path =>
                string.Equals(path, "src/MinecraftServerManager.Infrastructure/Utilities/RuntimePaths.cs", StringComparison.OrdinalIgnoreCase));

        AssertNoViolations(violations, "A22");
    }

    /// <summary>
    /// A23：判斷絕對路徑一律使用 Path.IsPathFullyQualified（IsPathRooted 對 \foo 與 C:foo 亦回傳 true）；
    /// 移除結尾分隔字元一律使用 Path.TrimEndingDirectorySeparator（TrimEnd 會將 C:\ 變為磁碟相對路徑 C:）
    /// 規範：專案規範「共用工具入口」（路徑 API）；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A23。
    /// </summary>
    [Fact]
    public void A23_PathApis_ShouldUseFullyQualifiedAndRootSafeVariants()
    {
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A23Regex(),
            "A23",
            "必須使用 Path.IsPathFullyQualified 與 Path.TrimEndingDirectorySeparator（SafeZipArchive 拒絕任何具根路徑之壓縮項目為例外）",
            path =>
                string.Equals(path, "src/MinecraftServerManager.Infrastructure/FileSystem/SafeZipArchive.cs", StringComparison.OrdinalIgnoreCase));

        AssertNoViolations(violations, "A23");
    }

    /// <summary>
    /// A24：Core／Infrastructure 進度轉接一律使用 SynchronousProgress&lt;T&gt;，
    /// 禁止 new Progress&lt;T&gt;（會擷取 SynchronizationContext，巢狀轉接時造成重複派送與回報亂序）
    /// 規範：專案規範「共用工具入口」（進度轉接）；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A24。
    /// </summary>
    [Fact]
    public void A24_CoreAndInfrastructure_MustNotCreateContextCapturingProgress()
    {
        var files = SourceScanner.GetSourceFiles("src/MinecraftServerManager.Core")
            .Concat(SourceScanner.GetSourceFiles("src/MinecraftServerManager.Infrastructure"));
        var violations = SourceScanner.ScanViolations(
            files,
            A24Regex(),
            "A24",
            "Core／Infrastructure 進度轉接必須使用 SynchronousProgress<T>",
            _ => false);

        AssertNoViolations(violations, "A24");
    }

    /// <summary>
    /// A25：表格欄位排序一律使用 TableSortExtensions.SortBy，禁止於各 View 自行建立比較器並重排集合
    /// 規範：專案規範「共用工具入口」（表格排序）、「表格與長列表規範」；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A25。
    /// </summary>
    [Fact]
    public void A25_TableSorting_ShouldOnlyUseTableSortExtensions()
    {
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A25Regex(),
            "A25",
            "表格排序必須統一使用 TableSortExtensions.SortBy",
            path =>
                string.Equals(path, "src/MinecraftServerManager.App/Controls/NaturalSortHelper.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.App/Controls/TableSortExtensions.cs", StringComparison.OrdinalIgnoreCase));

        AssertNoViolations(violations, "A25");
    }

    /// <summary>
    /// A26：原子替換用暫存檔命名一律使用 AtomicFileWriter.CreateTempSiblingPath／TempFileExtension
    /// 規範：專案規範「共用工具入口」（檔案與目錄：暫存檔命名）；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A26。
    /// </summary>
    [Fact]
    public void A26_TemporaryFileNaming_ShouldOnlyUseAtomicFileWriter()
    {
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A26Regex(),
            "A26",
            "暫存檔命名必須統一使用 AtomicFileWriter.CreateTempSiblingPath",
            path =>
                string.Equals(path, "src/MinecraftServerManager.Infrastructure/Utilities/AtomicFileWriter.cs", StringComparison.OrdinalIgnoreCase),
            preserveStrings: true);

        AssertNoViolations(violations, "A26");
    }

    /// <summary>
    /// A27：ANSI 跳脫序列清洗與 -Xmx／-Xms 參數正規式只能定義於 ModHelpers 與 MemoryUtils
    /// 規範：專案規範「共用工具入口」（ANSI 清洗、記憶體參數）；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A27。
    /// </summary>
    [Fact]
    public void A27_AnsiAndJvmMemoryPatterns_ShouldOnlyBeDefinedInSharedTools()
    {
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A27Regex(),
            "A27",
            "ANSI 清洗必須使用 ModHelpers.StripColorAndFormattingCodes，記憶體參數必須使用 MemoryUtils",
            path =>
                string.Equals(path, "src/MinecraftServerManager.Core/Mods/ModHelpers.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.Core/Utilities/MemoryUtils.cs", StringComparison.OrdinalIgnoreCase),
            preserveStrings: true);

        AssertNoViolations(violations, "A27");
    }

    /// <summary>
    /// A28：LoaderKind 字串解析一律使用 LoaderKinds.TryParse／ParseOrDefault（拒絕純數字字串與未定義值）
    /// 規範：專案規範「共用工具入口」（載入器種類解析）；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A28。
    /// </summary>
    [Fact]
    public void A28_LoaderKindParsing_ShouldOnlyUseLoaderKinds()
    {
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A28Regex(),
            "A28",
            "LoaderKind 解析必須統一使用 LoaderKinds",
            path =>
                string.Equals(path, "src/MinecraftServerManager.Domain/Servers/LoaderKinds.cs", StringComparison.OrdinalIgnoreCase));

        AssertNoViolations(violations, "A28");
    }

    /// <summary>
    /// A29：呈現層（ViewModels 與 Views）的檔案 I/O 一律經由 Core 連接埠（ILocalFileSystem、IServerLogReader、IModFileService、IServersRootService、IServerBackupService），
    /// 禁止直接呼叫 SafeFileSystem、ModFileInstaller、ServersRootRelocator、PropertiesDocumentCodec 靜態成員
    /// 規範：專案規範「相依方向」、「UI 與 MVVM 規範」；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A29。
    /// </summary>
    [Fact]
    public void A29_PresentationLayerFileIo_ShouldOnlyUseCorePorts()
    {
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A29Regex(),
            "A29",
            "ViewModel 與 View 的檔案 I/O 必須經由 Core 連接埠注入，不得直接呼叫 Infrastructure 靜態工具",
            path =>
                !path.StartsWith("src/MinecraftServerManager.App/ViewModels/", StringComparison.OrdinalIgnoreCase) &&
                !path.StartsWith("src/MinecraftServerManager.App/Views/", StringComparison.OrdinalIgnoreCase));

        AssertNoViolations(violations, "A29");
    }

    /// <summary>
    /// A30：視窗尺寸調整一律經由 WindowLayoutHelper.ResizeToDip（邏輯像素依 DPI 換算），禁止直接呼叫 AppWindow.Resize
    /// 規範：專案規範「UI 與 MVVM 規範」（Per-Monitor V2 高 DPI）；對照表：docs/TECHNICAL_OVERVIEW.md 第 11 節 A30。
    /// </summary>
    [Fact]
    public void A30_WindowResize_ShouldOnlyUseWindowLayoutHelper()
    {
        var files = SourceScanner.GetSourceFiles("src");
        var violations = SourceScanner.ScanViolations(
            files,
            A30Regex(),
            "A30",
            "視窗尺寸調整必須統一使用 WindowLayoutHelper.ResizeToDip，避免實體像素與邏輯像素混用",
            path =>
                string.Equals(path, "src/MinecraftServerManager.App/Services/WindowLayoutHelper.cs", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(path, "src/MinecraftServerManager.App/MainWindow.xaml.cs", StringComparison.OrdinalIgnoreCase));

        AssertNoViolations(violations, "A30");
    }

    #endregion

    #region 規則比對正規式（A1～A30）

    [GeneratedRegex(@"(?<![\w\.])((System\.IO\.)?(File\.|Directory\.|FileInfo\b|DirectoryInfo\b|FileStream\b|DriveInfo\b))")]
    private static partial Regex A1Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.IO\.Compression\.)?(ZipFile\.|ZipFile\b)|new\s+(System\.IO\.Compression\.)?ZipArchive\b|\b\w*Entry\w*\.Open\(\))")]
    private static partial Regex A2Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.Diagnostics\.)?(Process\.Start\b|ProcessStartInfo\b)|new\s+(System\.Diagnostics\.)?Process\()")]
    private static partial Regex A3Regex();

    [GeneratedRegex(@"(?<![\w\.])(new\s+(System\.Net\.Http\.)?HttpClient\b|SocketsHttpHandler\b|HttpClientHandler\b)")]
    private static partial Regex A4Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.Text\.Json\.)?(JsonSerializer\.|JsonDocument\.)|new\s+(System\.Text\.Json\.)?JsonSerializerOptions\b)")]
    private static partial Regex A5Regex();

    [GeneratedRegex(@"(?<![\w\.])(new\s+(System\.Text\.RegularExpressions\.)?Regex\(|(System\.Text\.RegularExpressions\.)?Regex\.(IsMatch|Match|Matches|Replace|Split)\()")]
    private static partial Regex A6Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.Windows\.)?MessageBox\.Show\b|MessageBoxW\b|Dispatcher\.Invoke|Dispatcher\.BeginInvoke|DispatcherTimer\b|DispatcherQueueTimer\b|FileOpenPicker\b|FileSavePicker\b|FolderPicker\b|new\s+ContentDialog\b)|\.CreateTimer\(")]
    private static partial Regex A7Regex();

    [GeneratedRegex(@"(?<![\w\.])unsafe\b")]
    private static partial Regex A8Regex();

    [GeneratedRegex(@"^\s*using\s+System\.(IO|Net|Diagnostics)\b")]
    private static partial Regex A9DomainUsingRegex();

    [GeneratedRegex(@"^\s*using\s+System\.(IO|Net\.Http|Diagnostics)\b")]
    private static partial Regex A9CoreUsingRegex();

    [GeneratedRegex(@"(?<![\w\.])(System\.Diagnostics\.Process\b|\bProcess\s+[A-Za-z_]|new\s+(System\.Net\.Http\.)?HttpClient\b|(System\.IO\.)?File\.|(System\.IO\.)?Directory\.)")]
    private static partial Regex A10Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.Security\.Cryptography\.)?(SHA256\.|SHA1\.|MD5\.|SHA512\.|IncrementalHash\b|HashAlgorithm\.|HashAlgorithmName\.|CryptographicOperations\.HashData\b)|System\.Security\.Cryptography\.HashAlgorithm\b)")]
    private static partial Regex A11Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.)?Console\.(WriteLine|Write)|(System\.Diagnostics\.)?(Trace|Debug)\.(WriteLine|Write|TraceInformation|TraceWarning|TraceError))\(")]
    private static partial Regex A12Regex();

    [GeneratedRegex(@"(?<![\w\.])_\s*=\s*(?!(?:ViewModelBase\.)?RunSafeAsync\b)(?:([a-zA-Z_]\w*\.)*([a-zA-Z_]\w*Async)|Task\.Run)\(")]
    private static partial Regex A13Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.Media\.)?(SystemSounds\b|SoundPlayer\b)|MessageBeep\b)")]
    private static partial Regex A14Regex();

    [GeneratedRegex(@"(?<![\w\.])(?:\bLogger|\blogger|\bLog)\.(Debug|Trace|LogDebug|LogTrace)\(")]
    private static partial Regex A15Regex();

    [GeneratedRegex(@"(?<![\w\.])(AppWindowTitleBar\b|UISettings\b|SetWindowLongPtrW\b|LoadIconW\b)")]
    private static partial Regex A16Regex();

    [GeneratedRegex(@"(""CLOCK\$""|""PRN""|\bStripJarExtension\b|\bExtractHash\s*\(\s*ModFile|\bResolveHash\s*\(\s*ModFile)")]
    private static partial Regex A17Regex();

    [GeneratedRegex(@"(?<![\w\.])catch\s*(\{|$)")]
    private static partial Regex A18Regex();

    [GeneratedRegex(@"EndsWith\(\s*""\.jar|\.jar\.disabled""")]
    private static partial Regex A19Regex();

    [GeneratedRegex(@"mc_versions_cache\.json|piston-meta\.mojang\.com|fill\.papermc\.io")]
    private static partial Regex A20Regex();

    [GeneratedRegex(@"\[\s*(LibraryImport|DllImport)\b")]
    private static partial Regex A21Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.)?Environment\.GetFolderPath|(System\.IO\.)?Path\.GetTempPath)\b")]
    private static partial Regex A22Regex();

    [GeneratedRegex(@"(?<![\w\.])((System\.IO\.)?Path\.IsPathRooted\(|\.TrimEnd\(\s*(System\.IO\.)?Path\.(Alt)?DirectorySeparatorChar)")]
    private static partial Regex A23Regex();

    [GeneratedRegex(@"(?<![\w\.])new\s+(System\.)?Progress<")]
    private static partial Regex A24Regex();

    [GeneratedRegex(@"(?<![\w\.])new\s+SortKeyComparer\b|\bSortKeyComparer\.Instance\b")]
    private static partial Regex A25Regex();

    [GeneratedRegex(@"\.tmp""")]
    private static partial Regex A26Regex();

    [GeneratedRegex(@"GeneratedRegex\(.*(\\x1B|\\u001[bB]|-Xm[xs]|Xmx\|Xms)")]
    private static partial Regex A27Regex();

    [GeneratedRegex(@"Enum\.(TryParse|Parse)\s*<\s*LoaderKind\s*>")]
    private static partial Regex A28Regex();

    [GeneratedRegex(@"(?<![\w\.])(SafeFileSystem|ModFileInstaller|ServersRootRelocator|PropertiesDocumentCodec)\.")]
    private static partial Regex A29Regex();

    [GeneratedRegex(@"\bAppWindow\.Resize\(")]
    private static partial Regex A30Regex();

    #endregion
}
