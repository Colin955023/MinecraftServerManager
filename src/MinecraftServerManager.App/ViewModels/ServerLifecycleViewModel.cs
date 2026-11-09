using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 伺服器管理頁：伺服器啟動、停止與監控視窗開啟
/// </summary>
public sealed partial class ServerLifecycleViewModel : ViewModelBase, IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerLifecycleViewModel));

    private readonly IUiService _ui;
    private readonly IServerManager _serverManager;
    private readonly IServerRuntime _serverRuntime;
    private readonly IServerInspector _serverInspector;
    private readonly IServerLaunchPlanner _launchPlanner;
    private readonly IServerLogReader _logReader;
    private readonly IServerPropertiesStore _propertiesStore;
    private readonly ILocalFileSystem _fileSystem;
    private readonly IJavaRuntimeDetector _javaDetector;
    private readonly IMinecraftJavaRequirementService _javaRequirementService;
    private readonly ServerListViewModel _list;
    private IMonitorWindow? _activeMonitorWindow;
    private ServerMonitorViewModel? _activeMonitorViewModel;

    /// <summary>
    /// 啟動後偵測提前結束的等待時間
    /// </summary>
    private static readonly TimeSpan EarlyExitProbeDelay = TimeSpan.FromSeconds(3);

    public ServerLifecycleViewModel(
        IServerManager serverManager,
        IServerRuntime serverRuntime,
        IServerInspector serverInspector,
        IServerLaunchPlanner launchPlanner,
        IServerLogReader logReader,
        IServerPropertiesStore propertiesStore,
        ILocalFileSystem fileSystem,
        ServerListViewModel list,
        IUiService uiService,
        IJavaRuntimeDetector javaDetector,
        IMinecraftJavaRequirementService javaRequirementService)
    {
        ArgumentNullException.ThrowIfNull(uiService);
        ArgumentNullException.ThrowIfNull(javaDetector);
        ArgumentNullException.ThrowIfNull(javaRequirementService);
        ArgumentNullException.ThrowIfNull(serverManager);
        ArgumentNullException.ThrowIfNull(serverRuntime);
        ArgumentNullException.ThrowIfNull(serverInspector);
        ArgumentNullException.ThrowIfNull(launchPlanner);
        ArgumentNullException.ThrowIfNull(logReader);
        ArgumentNullException.ThrowIfNull(propertiesStore);
        ArgumentNullException.ThrowIfNull(fileSystem);
        ArgumentNullException.ThrowIfNull(list);

        _ui = uiService;
        _serverManager = serverManager;
        _serverRuntime = serverRuntime;
        _serverInspector = serverInspector;
        _launchPlanner = launchPlanner;
        _logReader = logReader;
        _propertiesStore = propertiesStore;
        _fileSystem = fileSystem;
        _javaDetector = javaDetector;
        _javaRequirementService = javaRequirementService;
        _list = list;
        _list.SelectionStateChanged += OnSelectionStateChanged;
    }

    public void Dispose()
    {
        _list.SelectionStateChanged -= OnSelectionStateChanged;
        _activeMonitorViewModel?.Dispose();
        _activeMonitorViewModel = null;
    }

    private bool CanStartOrMonitorServer() => _list.CanStartOrMonitorServer;

    private bool HasSelectedServer() => _list.HasSelectedServer;

    private void OnSelectionStateChanged()
    {
        StartServerCommand.NotifyCanExecuteChanged();
        StopServerCommand.NotifyCanExecuteChanged();
        MonitorServerCommand.NotifyCanExecuteChanged();
    }

    [RelayCommand(CanExecute = nameof(CanStartOrMonitorServer))]
    public async Task StartServer()
    {
        if (_list.SelectedServer is not { HasMissingFiles: false } selected)
        {
            return;
        }

        await StartServerByNameAsync(selected.Name);
    }

    /// <summary>
    /// 依據伺服器名稱精準啟動伺服器，不仰賴清單選取項目
    /// </summary>
    public async Task<bool> StartServerByNameAsync(string serverName)
    {
        if (string.IsNullOrWhiteSpace(serverName))
        {
            return false;
        }

        if (_serverRuntime.IsRunning)
        {
            _ui.Notify("目前已有伺服器正在執行中，請先停止現有伺服器", NotificationType.Warning);
            return false;
        }

        try
        {
            var server = await _serverManager.GetServerAsync(serverName);
            if (server is null)
            {
                _ui.Notify($"找不到伺服器「{serverName}」", NotificationType.Error);
                return false;
            }

            var inspection = await _serverInspector.InspectAsync(server.Path).ConfigureAwait(true);
            string? missingTarget = await Task.Run(() => ResolveMissingLaunchTarget(server.Path, inspection.LaunchTarget.Value)).ConfigureAwait(true);
            if (missingTarget is not null)
            {
                Logger.Error("啟動目標檔案不存在: {Target}", missingTarget);
                _list.RequestStatusRefresh();
                await _ui.ShowErrorAsync($"啟動目標檔案不存在：\n{missingTarget}", "啟動伺服器失敗");
                return false;
            }

            var (javaPath, javaError) = await ResolveJavaExecutableAsync(server.MinecraftVersion.Value, server.LoaderType).ConfigureAwait(true);
            if (javaError is not null)
            {
                Logger.Error("解析 Java 執行環境失敗: {Message}", javaError);
                await _ui.ShowErrorAsync($"解析 Java 執行環境失敗：\n{javaError}", "啟動伺服器失敗");
                return false;
            }

            var plan = _launchPlanner.CreatePlan(server, inspection.LaunchTarget.Value, javaPath);

            MonitorServerByName(server.Name.Value, server.Path, server.MinecraftVersion.Value);

            await _serverRuntime.StartAsync(plan).ConfigureAwait(true);
            _list.RequestStatusRefresh();

            string? earlyExit = await DetectEarlyExitAsync().ConfigureAwait(true);
            if (earlyExit is not null)
            {
                Logger.Error("伺服器啟動後異常結束: {Message}", earlyExit);
                await _ui.ShowErrorAsync($"伺服器啟動後異常結束：\n{earlyExit}", "伺服器異常結束");
                _list.RequestStatusRefresh();
                return false;
            }

            Logger.Information("伺服器已成功啟動: {Name} (版本: {Version})", server.Name.Value, server.MinecraftVersion.Value);
            return true;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "啟動伺服器失敗: {Message}", ex.Message);
            await _ui.ShowErrorAsync($"啟動伺服器失敗：\n{ex.Message}", "啟動伺服器失敗");
            return false;
        }
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task StopServer()
    {
        if (_list.SelectedServer is not { } selected || !_serverRuntime.IsRunning)
        {
            return;
        }

        try
        {
            await _serverRuntime.StopAsync(TimeSpan.FromSeconds(10)).ConfigureAwait(true);
            _list.RequestStatusRefresh();
            Logger.Information("伺服器已成功傳送停止請求: {Name}", selected.Name);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "停止伺服器失敗: {Message}", ex.Message);
            _ui.Notify($"停止伺服器失敗：{ex.Message}", NotificationType.Error);
        }
    }

    [RelayCommand(CanExecute = nameof(CanStartOrMonitorServer))]
    public void MonitorServer()
    {
        if (_list.SelectedServer is not { HasMissingFiles: false } selected)
        {
            return;
        }

        MonitorServerByName(selected.Name, selected.Path, selected.Version);
    }

    /// <summary>
    /// 開啟（或帶至前景）指定伺服器的監控視窗
    /// </summary>
    public void MonitorServerByName(string serverName, string serverPath, string mcVersion)
    {
        if (_activeMonitorWindow is { IsOpen: true })
        {
            _activeMonitorWindow.BringToFront();
            return;
        }

        var vm = new ServerMonitorViewModel(
            _serverRuntime,
            _logReader,
            _propertiesStore,
            serverName,
            _ui,
            serverPath,
            mcVersion,
            startRequestHandler: () => StartServerByNameAsync(serverName));
        _activeMonitorViewModel = vm;
        _activeMonitorWindow = _ui.OpenServerMonitor(vm);
        _activeMonitorWindow.Closed += () =>
        {
            _activeMonitorWindow = null;
            _activeMonitorViewModel?.Dispose();
            _activeMonitorViewModel = null;
        };
    }

    /// <summary>
    /// 驗證啟動 JAR 或腳本是否確實存在，存在則回傳 null，缺失則回傳檔名。
    /// </summary>
    private string? ResolveMissingLaunchTarget(string serverPath, string launchTarget)
    {
        string target = string.IsNullOrWhiteSpace(launchTarget) ? "server.jar" : launchTarget.Trim();
        if (target.StartsWith('@'))
        {
            target = target[1..].Trim();
        }

        try
        {
            string fullPath = Path.GetFullPath(Path.Combine(serverPath, target));
            return _fileSystem.FileExists(fullPath) ? null : target;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning("驗證啟動目標路徑失敗: {0}", ex.Message);
            return target;
        }
    }

    /// <summary>
    /// 依據 Minecraft 版本與載入器解析所需的 Java 實體執行檔路徑。
    /// </summary>
    /// <returns>成功時回傳 (路徑, null)；失敗時回傳 (null, 錯誤訊息)。</returns>
    private async Task<(string? JavaPath, string? Error)> ResolveJavaExecutableAsync(string minecraftVersion, LoaderKind loader)
    {
        int requiredMajor;
        try
        {
            requiredMajor = await _javaRequirementService.GetRequiredJavaMajorAsync(minecraftVersion, loader).ConfigureAwait(true);
        }
        catch (Exception exception) when (exception is not OperationCanceledException)
        {
            Logger.Warning("查詢 Minecraft {Version} 所需 Java 版本失敗（{Message}），回退使用系統預設 java", minecraftVersion, exception.Message);
            return ("java", null);
        }

        JavaRuntimeInfo? runtime;
        try
        {
            runtime = await _javaDetector.FindBestMatchAsync(requiredMajor).ConfigureAwait(true);
        }
        catch (Exception exception) when (exception is not OperationCanceledException)
        {
            Logger.Warning(exception, "偵測 Java {Major} 執行環境時發生錯誤：{Message}", requiredMajor, exception.Message);
            return (null, $"偵測 Java {requiredMajor} 執行環境時發生錯誤：{exception.Message}");
        }

        if (runtime is null)
        {
            return (null, $"本機未安裝 Minecraft {minecraftVersion} 所需的 Java {requiredMajor}，請至「建立伺服器」頁面透過 winget 安裝後再啟動");
        }

        Logger.Information(
            "已解析 Minecraft {Version} 的 Java 執行檔: {Path} (major {Major})",
            minecraftVersion,
            runtime.ExecutablePath,
            runtime.MajorVersion);

        return (runtime.ExecutablePath, null);
    }

    /// <summary>
    /// 啟動後等待一段時間，若子行程已異常結束則回傳錯誤訊息。
    /// </summary>
    private async Task<string?> DetectEarlyExitAsync()
    {
        await Task.Delay(EarlyExitProbeDelay).ConfigureAwait(true);

        if (_serverRuntime.IsRunning)
        {
            return null;
        }

        int exitCode = _serverRuntime.ExitCode ?? -1;
        return exitCode == 0
            ? null
            : $"伺服器啟動後立即結束（結束代碼 {exitCode}），請開啟監控主控台檢視詳細輸出以確認原因";
    }
}
