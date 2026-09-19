using System.Collections.ObjectModel;
using System.Windows;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 建立伺服器頁面 ViewModel
/// </summary>
public sealed partial class CreateServerViewModel : PageViewModel
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("CreateServer");
    private static readonly string[] LoaderPrefixes = ["Fabric ", "Forge ", "Quilt ", "NeoForge ", "Vanilla "];

    private readonly IJavaRuntimeDetector? _javaDetector;
    private readonly IMinecraftJavaRequirementService? _javaRequirementService;
    private readonly IServerManager? _serverManager;
    private readonly ILoaderCatalogService? _loaderCatalog;
    private readonly Action<string, bool>? _notificationSink;
    private readonly IExternalLauncher? _launcher;
    private readonly Action<string, string?>? _navigateCallback;
    private readonly long _systemMemoryMb;
    private List<string>? _customJvmArgs;

    [ObservableProperty]
    private string _serverName = "我的伺服器";

    [ObservableProperty]
    private string _javaPath = string.Empty;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsNotDetectingJava))]
    private bool _isDetectingJava;

    public bool IsNotDetectingJava => !IsDetectingJava;

    [ObservableProperty]
    private string _selectedLoader = "Vanilla";

    [ObservableProperty]
    private string _selectedLoaderVersion = "無";

    [ObservableProperty]
    private bool _isLoaderVersionEnabled;

    [ObservableProperty]
    private string _selectedMinecraftVersion = "1.21.4";

    [ObservableProperty]
    private string _minMemoryMb = "1024";

    [ObservableProperty]
    private string _maxMemoryMb = "2048";

    [ObservableProperty]
    private string _memoryWarningText = string.Empty;

    [ObservableProperty]
    private bool _isMemoryWarning;

    [ObservableProperty]
    private bool _isMemoryError;

    [ObservableProperty]
    private string _jvmArgsSummary = "使用系統建議 JVM 參數 (G1GC)";

    public CreateServerViewModel(
        IJavaRuntimeDetector? javaDetector = null,
        IServerManager? serverManager = null,
        ILoaderCatalogService? loaderCatalog = null,
        Action<string, bool>? notificationSink = null,
        long? systemMemoryMb = null,
        IExternalLauncher? launcher = null,
        Action<string, string?>? navigateCallback = null,
        IMinecraftJavaRequirementService? javaRequirementService = null)
        : base("create", "建立新伺服器", "配置名稱、版本、模組載入器與記憶體參數建立伺服器")
    {
        _javaDetector = javaDetector;
        _javaRequirementService = javaRequirementService;
        _serverManager = serverManager;
        _loaderCatalog = loaderCatalog;
        _notificationSink = notificationSink;
        _launcher = launcher;
        _navigateCallback = navigateCallback;
        _systemMemoryMb = systemMemoryMb ?? GetTotalSystemMemoryMb();

        AvailableLoaders = ["Vanilla", "Fabric", "Forge", "Quilt", "NeoForge"];
        AvailableMinecraftVersions =
        [
            "1.21.4",
            "1.21.3",
            "1.21.1",
            "1.20.6",
            "1.20.4",
            "1.20.1",
            "1.19.4",
            "1.18.2",
            "1.16.5",
            "1.12.2"
        ];
        LoaderVersions = ["無"];

        int? cachedMajor = _javaRequirementService?.GetCachedJavaMajor(SelectedMinecraftVersion);
        _jvmArgsSummary = (cachedMajor is null or >= 21) ? "使用系統建議 JVM 參數 (ZGC)" : "使用系統建議 JVM 參數 (G1GC)";

        UpdateLoaderStateSync();
        UpdateMemoryWarning();

        if (_loaderCatalog is not null)
        {
            _ = InitializeVersionsAsync();
        }
    }

    public ObservableCollection<string> AvailableLoaders { get; }

    public ObservableCollection<string> AvailableMinecraftVersions { get; }

    public ObservableCollection<string> LoaderVersions { get; }

    public static string EulaNoticeText =>
        "請務必閱讀並同意 Minecraft EULA 條款 (點我閱讀)\n點擊建立即表示你同意 Minecraft 條款，任何違法行為本軟體不負責任";

    public static string EulaUrl => "https://aka.ms/MinecraftEULA";

    partial void OnSelectedLoaderChanged(string value)
    {
        UpdateSynchronizedServerName();
        _ = RefreshLoaderVersionsAsync();
    }

    partial void OnSelectedMinecraftVersionChanged(string value)
    {
        UpdateSynchronizedServerName();
        if (_customJvmArgs == null)
        {
            if (_javaRequirementService is not null)
            {
                _ = UpdateJvmArgsSummaryAsync(value);
            }
        }
        _ = RefreshLoaderVersionsAsync();
    }

    private async Task UpdateJvmArgsSummaryAsync(string version)
    {
        try
        {
            int major = await _javaRequirementService!.GetRequiredJavaMajorAsync(version).ConfigureAwait(true);
            if (_customJvmArgs == null && string.Equals(SelectedMinecraftVersion, version, StringComparison.OrdinalIgnoreCase))
            {
                JvmArgsSummary = major >= 21 ? "使用系統建議 JVM 參數 (ZGC)" : "使用系統建議 JVM 參數 (G1GC)";
            }
        }
        catch
        {
            // 無法從官方取得時保持預設，嚴禁版本號硬推算猜測
        }
    }

    partial void OnMinMemoryMbChanged(string value) => UpdateMemoryWarning();

    partial void OnMaxMemoryMbChanged(string value) => UpdateMemoryWarning();

    private void UpdateSynchronizedServerName()
    {
        string current = ServerName.Trim();
        if (string.Equals(current, "我的伺服器", StringComparison.OrdinalIgnoreCase))
        {
            ServerName = ComposeServerName(SelectedLoader, SelectedMinecraftVersion);
            return;
        }

        string? suffix = ExtractServerNameSuffix(current, AvailableMinecraftVersions);
        if (suffix != null)
        {
            ServerName = ComposeServerName(SelectedLoader, SelectedMinecraftVersion, suffix);
        }
    }

    private static string ComposeServerName(string loaderType, string mcVersion, string suffix = "")
    {
        string baseName = $"{mcVersion}{suffix}";
        return loaderType is "Fabric" or "Forge" or "Quilt" or "NeoForge"
            ? $"{loaderType} {baseName}"
            : $"Vanilla {baseName}";
    }

    private static string? ExtractServerNameSuffix(string name, IEnumerable<string> versionCandidates)
    {
        ReadOnlySpan<char> span = name.AsSpan().Trim();
        if (span.IsEmpty)
        {
            return null;
        }

        foreach (string prefix in LoaderPrefixes)
        {
            if (span.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            {
                span = span[prefix.Length..];
                break;
            }
        }

        foreach (string version in versionCandidates)
        {
            if (!string.IsNullOrEmpty(version) && span.StartsWith(version, StringComparison.OrdinalIgnoreCase))
            {
                return span[version.Length..].ToString();
            }
        }

        return null;
    }

    private async Task InitializeVersionsAsync()
    {
        if (_loaderCatalog is null)
        {
            return;
        }

        try
        {
            var versions = await _loaderCatalog.GetMinecraftVersionsAsync().ConfigureAwait(true);
            if (versions.Count > 0)
            {
                AvailableMinecraftVersions.Clear();
                foreach (var v in versions)
                {
                    AvailableMinecraftVersions.Add(v.Version);
                }

                if (!AvailableMinecraftVersions.Contains(SelectedMinecraftVersion))
                {
                    SelectedMinecraftVersion = AvailableMinecraftVersions[0];
                }
            }
        }
        catch
        {
            // 忽略預載入失敗，維持既有預設版本清單
        }

        await RefreshLoaderVersionsAsync().ConfigureAwait(true);
        if (_javaRequirementService is not null)
        {
            _ = Task.Run(() => _javaRequirementService.PreloadAllJavaRequirementsAsync());
        }
    }

    private async Task RefreshLoaderVersionsAsync()
    {
        if (SelectedLoader == "Vanilla")
        {
            UpdateLoaderStateSync();
            return;
        }

        if (_loaderCatalog is null || !Enum.TryParse<LoaderKind>(SelectedLoader, ignoreCase: true, out var loaderKind))
        {
            UpdateLoaderStateSync();
            return;
        }

        try
        {
            var versions = await _loaderCatalog.GetLoaderVersionsAsync(loaderKind, SelectedMinecraftVersion).ConfigureAwait(true);
            LoaderVersions.Clear();
            if (versions.Count > 0)
            {
                foreach (var v in versions)
                {
                    LoaderVersions.Add(v.Version);
                }
                SelectedLoaderVersion = LoaderVersions[0];
                IsLoaderVersionEnabled = true;
            }
            else
            {
                LoaderVersions.Add("無可用版本");
                SelectedLoaderVersion = "無可用版本";
                IsLoaderVersionEnabled = false;
            }
        }
        catch
        {
            UpdateLoaderStateSync();
        }
    }

    private void UpdateLoaderStateSync()
    {
        LoaderVersions.Clear();
        if (SelectedLoader == "Vanilla")
        {
            LoaderVersions.Add("無");
            SelectedLoaderVersion = "無";
            IsLoaderVersionEnabled = false;
        }
        else
        {
            LoaderVersions.Add($"最新穩定版 ({SelectedLoader})");
            SelectedLoaderVersion = LoaderVersions[0];
            IsLoaderVersionEnabled = true;
        }
    }

    [RelayCommand]
    public void OpenEula() => _launcher?.OpenUrl(EulaUrl);

    [RelayCommand]
    public void BrowseJava()
    {
        var dialog = new Microsoft.Win32.OpenFileDialog
        {
            Title = "選取 Java 執行檔",
            Filter = "Java 執行檔 (javaw.exe;java.exe)|javaw.exe;java.exe|所有檔案 (*.*)|*.*",
            CheckFileExists = true
        };

        if (dialog.ShowDialog() == true)
        {
            JavaPath = dialog.FileName;
        }
    }

    [RelayCommand]
    public async Task AutoDetectJavaAsync()
    {
        if (_javaDetector is null)
        {
            _notificationSink?.Invoke("未設定 Java 偵測器", true);
            return;
        }

        IsDetectingJava = true;
        try
        {
            int? targetMajor = null;
            if (_javaRequirementService is not null)
            {
                try
                {
                    targetMajor = await _javaRequirementService.GetRequiredJavaMajorAsync(SelectedMinecraftVersion).ConfigureAwait(true);
                }
                catch (Exception ex)
                {
                    Logger.Warning("向官方取得 Minecraft {Version} 之 Java major 失敗: {Error}", SelectedMinecraftVersion, ex.Message);
                }
            }

            JavaRuntimeInfo? matched = targetMajor.HasValue
                ? await _javaDetector.FindBestMatchAsync(targetMajor.Value).ConfigureAwait(true)
                : null;

            if (matched is not null)
            {
                JavaPath = matched.ExecutablePath;
                Logger.Information("依據 Minecraft {McVersion} (官方指定需求 Java {TargetMajor}) 配對到最佳 Java {FoundMajor}：{Path}",
                    SelectedMinecraftVersion, targetMajor, matched.MajorVersion, JavaPath);
            }
            else
            {
                var detected = await _javaDetector.DetectAsync().ConfigureAwait(true);
                if (detected.Count > 0)
                {
                    JavaPath = detected[0].ExecutablePath;
                    Logger.Information("選取本機偵測到之 Java {FoundMajor}：{Path}",
                        detected[0].MajorVersion, JavaPath);
                }
                else
                {
                    _notificationSink?.Invoke("未偵測到相容的 Java 執行檔，請手動指定路徑", true);
                }
            }
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "自動偵測 Java 失敗: {Message}", ex.Message);
            _notificationSink?.Invoke($"自動偵測 Java 失敗：{ex.Message}", true);
        }
        finally
        {
            IsDetectingJava = false;
        }
    }

    [RelayCommand]
    public async Task ReloadMinecraftVersions()
    {
        if (_loaderCatalog is not null)
        {
            try
            {
                var versions = await _loaderCatalog.GetMinecraftVersionsAsync().ConfigureAwait(true);
                if (versions.Count > 0)
                {
                    AvailableMinecraftVersions.Clear();
                    foreach (var v in versions)
                    {
                        AvailableMinecraftVersions.Add(v.Version);
                    }
                    if (!AvailableMinecraftVersions.Contains(SelectedMinecraftVersion))
                    {
                        SelectedMinecraftVersion = AvailableMinecraftVersions[0];
                    }
                    Logger.Information("已重新整理 Minecraft 版本清單，共 {Count} 個版本", versions.Count);
                    await RefreshLoaderVersionsAsync().ConfigureAwait(true);
                    return;
                }
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "重新整理版本清單失敗: {Message}", ex.Message);
                return;
            }
        }
    }

    [RelayCommand]
    public async Task ReloadLoaderVersions()
    {
        if (_loaderCatalog is not null)
        {
            await _loaderCatalog.ForceReloadAllLoadersAsync().ConfigureAwait(true);
        }
        await RefreshLoaderVersionsAsync().ConfigureAwait(true);
        Logger.Information("已強制向網路重新載入所有載入器版本清單");
    }

    [RelayCommand]
    public void ConfigureJvmArgs()
    {
        int maxMem = int.TryParse(MaxMemoryMb.Trim(), out int m) ? m : 2048;
        int? javaMajor = _javaRequirementService?.GetCachedJavaMajor(SelectedMinecraftVersion);
        var vm = new JvmArgsViewModel(javaMajor, maxMem, SelectedLoader, _customJvmArgs);
        var dialog = new Views.JvmArgsDialog(vm);
        if (Application.Current?.MainWindow is not null)
        {
            dialog.Owner = Application.Current.MainWindow;
        }

        if (dialog.ShowDialog() == true)
        {
            var finalArgs = vm.GetFinalJvmArgs();
            _customJvmArgs = [.. finalArgs];
            JvmArgsSummary = finalArgs.Count > 0
                ? $"已套用 {finalArgs.Count} 個 JVM 參數"
                : "無使用自訂 JVM 參數";
            Logger.Information("JVM 參數已配置，共 {Count} 個參數", finalArgs.Count);
        }
    }

    [RelayCommand]
    public void ResetForm()
    {
        SelectedLoader = "Vanilla";
        SelectedMinecraftVersion = AvailableMinecraftVersions.Count > 0 ? AvailableMinecraftVersions[0] : "1.21.4";
        SelectedLoaderVersion = SelectedMinecraftVersion;
        ServerName = $"Vanilla {SelectedMinecraftVersion}";
        MinMemoryMb = "1024";
        MaxMemoryMb = "2048";
        JavaPath = string.Empty;
        _customJvmArgs = null;
        int? javaMajor = _javaRequirementService?.GetCachedJavaMajor(SelectedMinecraftVersion);
        JvmArgsSummary = (javaMajor is null or >= 21)
            ? "使用系統建議 JVM 參數 (ZGC)"
            : "使用系統建議 JVM 參數 (G1GC)";
        UpdateLoaderStateSync();
        UpdateMemoryWarning();
        Logger.Information("建立伺服器表單已重設為預設值 (Vanilla {Version})", SelectedMinecraftVersion);
    }

    [RelayCommand]
    public async Task CreateServer()
    {
        if (string.IsNullOrWhiteSpace(ServerName))
        {
            _notificationSink?.Invoke("伺服器名稱不能為空", true);
            return;
        }

        if (IsMemoryError)
        {
            _notificationSink?.Invoke($"記憶體設定無效：{MemoryWarningText}", true);
            return;
        }

        if (_serverManager is not null)
        {
            try
            {
                int minMem = int.TryParse(MinMemoryMb.Trim(), out int min) ? min : 1024;
                int maxMem = int.TryParse(MaxMemoryMb.Trim(), out int max) ? max : 2048;
                Enum.TryParse<LoaderKind>(SelectedLoader, ignoreCase: true, out var loaderKind);

                string loaderVer = SelectedLoaderVersion;
                if (loaderVer is "無" or "無可用版本")
                {
                    loaderVer = string.Empty;
                }

                var plan = ServerCreationPlan.Create(
                    name: Domain.ValueObjects.ServerName.Parse(ServerName.Trim()),
                    minecraftVersion: Domain.ValueObjects.MinecraftVersion.Parse(SelectedMinecraftVersion),
                    loaderType: loaderKind,
                    loaderVersion: loaderVer,
                    memoryMaxMb: maxMem,
                    memoryMinMb: minMem,
                    jvmArgs: _customJvmArgs,
                    userJavaPath: string.IsNullOrWhiteSpace(JavaPath) ? null : JavaPath);

                Logger.Information("開始建立伺服器: {Name}, 版本: {Version}, 載入器: {Loader}, 記憶體: {Min}M-{Max}M",
                    plan.Name.Value, plan.MinecraftVersion.Value, plan.LoaderType, plan.MemoryMinMb, plan.MemoryMaxMb);

                var created = await _serverManager.CreateServerAsync(plan);
                if (created.Completed && created.Config is not null)
                {
                    Logger.Information("伺服器建立成功: {Name}，路徑: {Path}", created.Config.Name.Value, created.Config.Path);
                    _notificationSink?.Invoke($"伺服器「{created.Config.Name.Value}」已成功建立！", false);
                    _navigateCallback?.Invoke("manage", created.Config.Name.Value);
                }
                else
                {
                    Logger.Warning("伺服器建立失敗: {Message}", created.Message);
                    _notificationSink?.Invoke($"建立伺服器失敗：{created.Message}", true);
                }
                return;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "建立伺服器時發生例外: {Message}", ex.Message);
                _notificationSink?.Invoke($"建立伺服器失敗：{ex.Message}", true);
                return;
            }
        }

        _notificationSink?.Invoke($"準備建立伺服器「{ServerName}」({SelectedMinecraftVersion} / {SelectedLoader})", false);
    }

    private void UpdateMemoryWarning()
    {
        bool hasMin = int.TryParse(MinMemoryMb.Trim(), out int minMem);
        bool hasMax = int.TryParse(MaxMemoryMb.Trim(), out int maxMem);

        if (!hasMax)
        {
            MemoryWarningText = "⚠️ 警告：最大記憶體必須為有效的正整數";
            IsMemoryError = true;
            IsMemoryWarning = false;
            return;
        }

        if (hasMin && minMem > maxMem)
        {
            MemoryWarningText = "⚠️ 警告：最小記憶體必須小於最大記憶體";
            IsMemoryError = true;
            IsMemoryWarning = false;
            return;
        }

        if (_systemMemoryMb > 0)
        {
            if (maxMem > _systemMemoryMb || (hasMin && minMem > _systemMemoryMb))
            {
                MemoryWarningText = $"⚠️ 警告：設定記憶體超過系統總記憶體 ({_systemMemoryMb}MB)";
                IsMemoryError = true;
                IsMemoryWarning = false;
                return;
            }

            long halfSystem = _systemMemoryMb / 2;
            if (maxMem > halfSystem || (hasMin && minMem > halfSystem))
            {
                MemoryWarningText = $"⚠️ 警告：設定記憶體超過系統記憶體的一半 ({halfSystem}MB)";
                IsMemoryError = false;
                IsMemoryWarning = true;
                return;
            }
        }

        MemoryWarningText = string.Empty;
        IsMemoryError = false;
        IsMemoryWarning = false;
    }

    private static long GetTotalSystemMemoryMb()
    {
        try
        {
            var memoryStatus = GC.GetGCMemoryInfo();
            long totalBytes = memoryStatus.TotalAvailableMemoryBytes;
            return totalBytes > 0 ? totalBytes / (1024 * 1024) : 16384;
        }
        catch
        {
            return 16384;
        }
    }
}
