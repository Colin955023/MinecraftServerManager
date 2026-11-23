using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Servers;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>建立伺服器頁面 ViewModel</summary>
public sealed partial class CreateServerViewModel : PageViewModel, IDisposable
{
    private const string NoAvailableVersion = "無可用版本";
    private const string DefaultLoader = "Paper";
    private const string EulaUrl = "https://aka.ms/MinecraftEULA";
    private const string VersionOperationCancelled = "版本與參數設定操作已取消";

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(CreateServerViewModel));
    private static readonly string[] NoAvailableVersions = [NoAvailableVersion];
    private static readonly string DefaultMinMemoryText = ServerDefaults.DefaultMemoryMinMb.ToString(System.Globalization.CultureInfo.InvariantCulture);
    private static readonly string DefaultMaxMemoryText = ServerDefaults.DefaultMemoryMaxMb.ToString(System.Globalization.CultureInfo.InvariantCulture);

    private readonly IUiService _ui;
    private readonly IJavaRuntimeDetector _javaDetector;
    private readonly IMinecraftJavaRequirementService _javaRequirementService;
    private readonly IJavaInstaller _javaInstaller;
    private readonly IServerRuntimeHost _runtimeHost;
    private readonly Func<IServerRuntime, ServerInitializationWorkflow> _createInitializationWorkflow;
    private readonly ILocalFileSystem _fileSystem;
    private readonly IServerManager _serverManager;
    private readonly ILoaderCatalogService _loaderCatalog;
    private readonly IExternalLauncher _launcher;
    private readonly Action<string, string?> _navigateCallback;
    private readonly long _systemMemoryMb;
    private readonly SerialCancellation _versionFetch = new();
    private readonly SerialCancellation _selectionFetch = new();
    private readonly CancellationTokenSource _lifetime = new();
    private readonly CancellationToken _lifetimeToken;
    private List<string>? _customJvmArgs;
    private int _loadingCount;
    private bool _isServerNameManuallyEdited;
    private bool _isProgrammaticServerNameUpdate;
    private bool _isUserManuallySelectedVersion;
    private bool _isProgrammaticVersionUpdate;
    private bool _disposed;

    public CreateServerViewModel(
        ILocalFileSystem fileSystem,
        IUiService uiService,
        IJavaRuntimeDetector javaDetector,
        IServerManager serverManager,
        ILoaderCatalogService loaderCatalog,
        long systemMemoryMb,
        IExternalLauncher launcher,
        Action<string, string?> navigateCallback,
        IMinecraftJavaRequirementService javaRequirementService,
        IJavaInstaller javaInstaller,
        IServerRuntimeHost runtimeHost,
        Func<IServerRuntime, ServerInitializationWorkflow> createInitializationWorkflow)
        : base("建立新伺服器")
    {
        ArgumentNullException.ThrowIfNull(fileSystem);
        ArgumentNullException.ThrowIfNull(uiService);
        ArgumentNullException.ThrowIfNull(javaDetector);
        ArgumentNullException.ThrowIfNull(serverManager);
        ArgumentNullException.ThrowIfNull(loaderCatalog);
        ArgumentNullException.ThrowIfNull(launcher);
        ArgumentNullException.ThrowIfNull(navigateCallback);
        ArgumentNullException.ThrowIfNull(javaRequirementService);
        ArgumentNullException.ThrowIfNull(javaInstaller);
        ArgumentNullException.ThrowIfNull(runtimeHost);
        ArgumentNullException.ThrowIfNull(createInitializationWorkflow);

        _ui = uiService;
        _javaDetector = javaDetector;
        _javaRequirementService = javaRequirementService;
        _javaInstaller = javaInstaller;
        _runtimeHost = runtimeHost;
        _createInitializationWorkflow = createInitializationWorkflow;
        _fileSystem = fileSystem;
        _serverManager = serverManager;
        _loaderCatalog = loaderCatalog;
        _launcher = launcher;
        _navigateCallback = navigateCallback;
        _systemMemoryMb = systemMemoryMb;
        _lifetimeToken = _lifetime.Token;

        AvailableLoaders = [DefaultLoader, "Fabric", "Quilt", "Forge", "NeoForge"];
        AvailableMinecraftVersions = [];
        SetServerNameProgrammatically(DefaultServerName);
        LoaderVersions = [SelectedLoaderVersion];

        ApplyCachedJvmSummary();
        IsMinecraftVersionReloadEnabled = !IsPaperSelected;

        UpdateLoaderStateSync();
        UpdateMemoryWarning();

        _ = RunSafeAsync(InitializeVersionsAsync, "初始化 Minecraft 版本清單", Logger);
    }

    [ObservableProperty]
    public partial string ServerName { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string JavaPath { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string SelectedLoader { get; set; } = DefaultLoader;

    [ObservableProperty]
    public partial string SelectedLoaderVersion { get; set; } = LatestStableVersionText(DefaultLoader);

    [ObservableProperty]
    public partial bool IsLoaderVersionEnabled { get; set; } = true;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ReloadMinecraftVersionsCommand), nameof(ReloadLoaderVersionsCommand))]
    public partial bool IsLoadingVersions { get; private set; }

    [ObservableProperty]
    public partial string LoadingStatusText { get; set; } = string.Empty;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(ReloadMinecraftVersionsCommand))]
    public partial bool IsMinecraftVersionReloadEnabled { get; private set; }

    [ObservableProperty]
    public partial string SelectedMinecraftVersion { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string MinMemoryMb { get; set; } = DefaultMinMemoryText;

    [ObservableProperty]
    public partial string MaxMemoryMb { get; set; } = DefaultMaxMemoryText;

    [ObservableProperty]
    public partial string MemoryWarningText { get; set; } = string.Empty;

    [ObservableProperty]
    public partial bool IsMemoryError { get; set; }

    [ObservableProperty]
    public partial string JvmArgsSummary { get; set; } = string.Empty;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(CreateServerCommand), nameof(ResetFormCommand))]
    public partial bool IsCreating { get; set; }

    public ObservableCollection<string> AvailableLoaders { get; }

    public BulkObservableCollection<string> AvailableMinecraftVersions { get; }

    public BulkObservableCollection<string> LoaderVersions { get; }

    private bool CanCreateServer => !IsCreating;
    private bool CanResetForm => !IsCreating;
    private bool CanReloadMinecraftVersions => IsMinecraftVersionReloadEnabled && !IsLoadingVersions;
    private bool CanReloadLoaderVersions => !IsLoadingVersions;

    private LoaderKind CurrentLoaderKind => LoaderKinds.ParseOrDefault(SelectedLoader);

    private bool IsPaperSelected => CurrentLoaderKind == LoaderKind.Paper;

    private string DefaultServerName => string.IsNullOrWhiteSpace(SelectedMinecraftVersion) ? SelectedLoader : $"{SelectedLoader} {SelectedMinecraftVersion}";

    private int ParsedMinMemoryMb => int.TryParse(MinMemoryMb.AsSpan().Trim(), out int min) ? min : ServerDefaults.DefaultMemoryMinMb;

    private int ParsedMaxMemoryMb => int.TryParse(MaxMemoryMb.AsSpan().Trim(), out int max) ? max : ServerDefaults.DefaultMemoryMaxMb;

    partial void OnServerNameChanged(string value)
    {
        if (_isProgrammaticServerNameUpdate)
        {
            return;
        }

        _isServerNameManuallyEdited = !string.Equals(value.Trim(), DefaultServerName, StringComparison.OrdinalIgnoreCase);
    }

    partial void OnSelectedLoaderChanged(string value)
    {
        IsMinecraftVersionReloadEnabled = !IsPaperSelected;
        UpdateSynchronizedServerName();
        _ = RunSafeAsync(() => HandleLoaderChangedAsync(value), "切換模組載入器", Logger);
    }

    partial void OnSelectedMinecraftVersionChanged(string value)
    {
        if (!_isProgrammaticVersionUpdate)
        {
            _isUserManuallySelectedVersion = true;
        }

        UpdateSynchronizedServerName();
        _ = RunSafeAsync(RefreshSelectionDependentsAsync, "重新整理載入器版本與 JVM 參數摘要", Logger);
    }

    partial void OnMinMemoryMbChanged(string value) => UpdateMemoryWarning();

    partial void OnMaxMemoryMbChanged(string value) => UpdateMemoryWarning();

    private async Task InitializeVersionsAsync()
    {
        BeginLoading("正在載入可用版本清單...");
        try
        {
            await HandleLoaderChangedAsync(SelectedLoader);
        }
        finally
        {
            EndLoading();
        }

        _ = RunSafeAsync(PreloadJavaRequirementsAsync, "背景預載 Java 需求", Logger);
    }

    private async Task PreloadJavaRequirementsAsync()
    {
        try
        {
            var token = _lifetimeToken;
            await Task.Run(() => _javaRequirementService.PreloadAllJavaRequirementsAsync(cancellationToken: token), token).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "背景預載 Java 需求失敗，沿用既有快取");
        }
    }

    private async Task UpdateJvmArgsSummaryAsync(CancellationToken token)
    {
        string version = SelectedMinecraftVersion;
        if (_customJvmArgs != null || string.IsNullOrWhiteSpace(version))
        {
            return;
        }

        try
        {
            int major = await _javaRequirementService.GetRequiredJavaMajorAsync(version, token);
            if (!token.IsCancellationRequested && _customJvmArgs == null)
            {
                JvmArgsSummary = RecommendedJvmSummary(major);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "更新建議 JVM 參數摘要失敗");
        }
    }

    /// <summary>進入版本載入狀態；可巢狀呼叫，最後一次 <see cref="EndLoading"/> 才結束</summary>
    private void BeginLoading(string statusText)
    {
        Interlocked.Increment(ref _loadingCount);
        LoadingStatusText = statusText;
        IsLoadingVersions = true;
    }

    private void EndLoading()
    {
        if (Interlocked.Decrement(ref _loadingCount) == 0)
        {
            IsLoadingVersions = false;
            LoadingStatusText = string.Empty;
        }
    }

    private void SetServerNameProgrammatically(string name)
    {
        _isProgrammaticServerNameUpdate = true;
        try
        {
            ServerName = name;
        }
        finally
        {
            _isProgrammaticServerNameUpdate = false;
        }
    }

    private void SetMinecraftVersionProgrammatically(string version)
    {
        _isProgrammaticVersionUpdate = true;
        try
        {
            SelectedMinecraftVersion = version;
        }
        finally
        {
            _isProgrammaticVersionUpdate = false;
        }
    }

    private void UpdateSynchronizedServerName()
    {
        if (!_isServerNameManuallyEdited)
        {
            SetServerNameProgrammatically(DefaultServerName);
            return;
        }

        string currentName = ServerName;
        string mcVersion = SelectedMinecraftVersion;
        foreach (string loader in AvailableLoaders)
        {
            string prefix = !string.IsNullOrWhiteSpace(mcVersion) ? $"{loader} {mcVersion}" : loader;
            if (currentName.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            {
                string suffix = currentName[prefix.Length..];
                SetServerNameProgrammatically($"{SelectedLoader}{(string.IsNullOrWhiteSpace(mcVersion) ? string.Empty : " " + mcVersion)}{suffix}");
                return;
            }
        }
    }

    private void UpdateLoaderStateSync()
    {
        LoaderVersions.ReplaceAll((string[])[LatestStableVersionText(SelectedLoader)]);
        SelectedLoaderVersion = LoaderVersions[0];
        IsLoaderVersionEnabled = CurrentLoaderKind is LoaderKind.Forge or LoaderKind.NeoForge;
    }

    [RelayCommand]
    public void OpenEula() => _ui.OpenUrlOrWarn(_launcher, EulaUrl);

    [RelayCommand]
    public async Task OpenManageJavaAsync()
    {
        using var vm = new ManageJavaViewModel(
            _javaDetector,
            _javaRequirementService,
            _javaInstaller,
            JavaPath,
            SelectedMinecraftVersion,
            _fileSystem,
            _ui);

        if (await _ui.ShowManageJavaAsync(vm) == true && !string.IsNullOrWhiteSpace(vm.ResultJavaPath))
        {
            JavaPath = vm.ResultJavaPath;
        }
    }

    [RelayCommand]
    public async Task ConfigureJvmArgsAsync()
    {
        int? javaMajor = _javaRequirementService.GetCachedJavaMajor(SelectedMinecraftVersion);
        var vm = new JvmArgsViewModel(javaMajor, ParsedMaxMemoryMb, CurrentLoaderKind, _customJvmArgs);
        if (await _ui.ShowJvmArgsAsync(vm) == true)
        {
            var finalArgs = vm.GetFinalJvmArgs();
            _customJvmArgs = [.. finalArgs];
            JvmArgsSummary = finalArgs.Count > 0
                ? $"已套用 {finalArgs.Count} 個 JVM 參數"
                : "未使用自訂 JVM 參數";
            Logger.Information("JVM 參數已設定，共 {Count} 個參數", finalArgs.Count);
            if (vm.RejectedArgs.Count > 0)
            {
                _ui.Notify($"下列 JVM 參數可執行外部命令，已排除：{string.Join("、", vm.RejectedArgs)}", NotificationType.Warning);
            }
        }
    }

    /// <summary>重設表單；載入器改變時由切換流程重新載入版本，避免沿用舊載入器的版本清單</summary>
    [RelayCommand(CanExecute = nameof(CanResetForm))]
    public async Task ResetFormAsync()
    {
        if (!await _ui.ConfirmAsync("確定要重設建立伺服器表單的所有欄位內容嗎？", "確認重設表單"))
        {
            return;
        }

        _customJvmArgs = null;
        _isServerNameManuallyEdited = false;
        _isUserManuallySelectedVersion = false;
        MinMemoryMb = DefaultMinMemoryText;
        MaxMemoryMb = DefaultMaxMemoryText;
        JavaPath = string.Empty;

        if (!string.Equals(SelectedLoader, DefaultLoader, StringComparison.Ordinal))
        {
            SelectedLoader = DefaultLoader;
        }
        else
        {
            if (AvailableMinecraftVersions.Count > 0)
            {
                SetMinecraftVersionProgrammatically(AvailableMinecraftVersions[0]);
            }

            if (LoaderVersions.Count > 0)
            {
                SelectedLoaderVersion = LoaderVersions[0];
            }
        }

        SetServerNameProgrammatically(DefaultServerName);
        ApplyCachedJvmSummary();
        Logger.Information("建立伺服器表單已重設為預設值（Paper {Version}）", SelectedMinecraftVersion);
    }

    private static string LatestStableVersionText(string loader) => $"最新穩定版（{loader}）";

    private void ApplyCachedJvmSummary() =>
        JvmArgsSummary = RecommendedJvmSummary(_javaRequirementService.GetCachedJavaMajor(SelectedMinecraftVersion));

    private static string RecommendedJvmSummary(int? javaMajor) =>
        javaMajor is null or >= 21 ? "使用系統建議 JVM 參數（ZGC）" : "使用系統建議 JVM 參數（G1GC）";

    private void UpdateMemoryWarning()
    {
        var check = Core.Utilities.MemoryHelpers.CheckServerMemory(MaxMemoryMb, MinMemoryMb, _systemMemoryMb);
        MemoryWarningText = check.Level == Core.Utilities.MemoryCheckLevel.Ok ? string.Empty : $"警告：{check.Message}";
        IsMemoryError = check.Level == Core.Utilities.MemoryCheckLevel.Error;
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        _lifetime.Cancel();
        _versionFetch.Dispose();
        _selectionFetch.Dispose();
        _lifetime.Dispose();
    }
}
