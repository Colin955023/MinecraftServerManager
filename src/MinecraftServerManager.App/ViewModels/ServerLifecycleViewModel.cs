using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>伺服器管理頁：伺服器啟動、停止與監控視窗開啟</summary>
public sealed partial class ServerLifecycleViewModel : ViewModelBase, IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerLifecycleViewModel));

    /// <summary>啟動後偵測提前結束的等待時間</summary>
    private static readonly TimeSpan EarlyExitProbeDelay = TimeSpan.FromSeconds(3);

    private readonly IUiService _ui;
    private readonly IServerManager _serverManager;
    private readonly IServerRuntimeHost _runtimeHost;
    private readonly ServerStopCoordinator _stopCoordinator;
    private readonly ServerStartPreflight _preflight;
    private readonly IServerInspector _serverInspector;
    private readonly IServerLaunchPlanner _launchPlanner;
    private readonly IServerLogReader _logReader;
    private readonly IServerPropertiesStore _propertiesStore;
    private readonly ILocalFileSystem _fileSystem;
    private readonly IJavaRuntimeDetector _javaDetector;
    private readonly IMinecraftJavaRequirementService _javaRequirementService;
    private readonly ServerListViewModel _list;
    private readonly Dictionary<string, (IMonitorWindow Window, ServerMonitorViewModel ViewModel, Action OnClosed)> _monitors = new(StringComparer.OrdinalIgnoreCase);
    private readonly HashSet<string> _starting = new(StringComparer.OrdinalIgnoreCase);

    public ServerLifecycleViewModel(
        IServerManager serverManager,
        IServerRuntimeHost runtimeHost,
        ServerStopCoordinator stopCoordinator,
        ServerStartPreflight preflight,
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
        ArgumentNullException.ThrowIfNull(runtimeHost);
        ArgumentNullException.ThrowIfNull(stopCoordinator);
        ArgumentNullException.ThrowIfNull(preflight);
        ArgumentNullException.ThrowIfNull(serverInspector);
        ArgumentNullException.ThrowIfNull(launchPlanner);
        ArgumentNullException.ThrowIfNull(logReader);
        ArgumentNullException.ThrowIfNull(propertiesStore);
        ArgumentNullException.ThrowIfNull(fileSystem);
        ArgumentNullException.ThrowIfNull(list);

        _ui = uiService;
        _serverManager = serverManager;
        _runtimeHost = runtimeHost;
        _stopCoordinator = stopCoordinator;
        _preflight = preflight;
        _serverInspector = serverInspector;
        _launchPlanner = launchPlanner;
        _logReader = logReader;
        _propertiesStore = propertiesStore;
        _fileSystem = fileSystem;
        _javaDetector = javaDetector;
        _javaRequirementService = javaRequirementService;
        _list = list;
        _list.RegisterDependentCommands(StartServerCommand, StopServerCommand, MonitorServerCommand);
    }

    public void Dispose()
    {
        var entries = _monitors.Values.ToArray();
        _monitors.Clear();

        foreach (var (window, viewModel, onClosed) in entries)
        {
            window.Closed -= onClosed;
            window.Close();
            viewModel.Dispose();
        }
    }

    private bool CanStartOrMonitorServer() => _list.CanStartOrMonitorServer;

    private bool HasSelectedServer() => _list.HasSelectedServer;

    [RelayCommand(CanExecute = nameof(CanStartOrMonitorServer))]
    public Task StartServerAsync() => _list.RunForSelectedServerAsync(async selected =>
    {
        if (!selected.HasMissingFiles)
        {
            await StartServerByNameAsync(selected.Name);
        }
    });

    /// <summary>依據伺服器名稱精準啟動伺服器，不仰賴清單選取項目；同一伺服器同時僅允許一個啟動流程</summary>
    public async Task<bool> StartServerByNameAsync(string serverName)
    {
        if (string.IsNullOrWhiteSpace(serverName))
        {
            return false;
        }

        var runtime = _runtimeHost.GetRuntime(serverName);
        if (runtime.IsRunning)
        {
            _ui.Notify($"伺服器「{serverName}」已在執行中", NotificationType.Warning);
            return false;
        }

        if (!_starting.Add(serverName))
        {
            _ui.Notify($"伺服器「{serverName}」正在啟動中，請稍候", NotificationType.Info);
            return false;
        }

        try
        {
            return await StartCoreAsync(serverName, runtime);
        }
        finally
        {
            _starting.Remove(serverName);
        }
    }

    private async Task<bool> StartCoreAsync(string serverName, IServerRuntime runtime)
    {
        try
        {
            if (await _ui.GetServerOrWarnAsync(_serverManager, serverName, NotificationType.Error) is not { } server)
            {
                return false;
            }

            var inspection = await _serverInspector.InspectAsync(server.Path);
            string? missingTarget = await ResolveMissingLaunchTargetAsync(server.Path, inspection.LaunchTarget.Value);
            if (missingTarget is not null)
            {
                Logger.Error("啟動目標檔案不存在：{Target}", missingTarget);
                _list.RequestStatusRefresh();
                await _ui.ShowErrorAsync($"啟動目標檔案不存在：\n{missingTarget}", "啟動伺服器失敗");
                return false;
            }

            var (javaPath, javaMajor, javaError) = await ResolveJavaExecutableAsync(server.MinecraftVersion.Value);
            if (javaError is not null)
            {
                Logger.Error("Java 版本檢查未通過，已阻擋啟動：{Message}", javaError);
                await _ui.ShowErrorAsync($"Java 版本不相符或無法確認，已阻擋啟動：\n{javaError}", "啟動伺服器失敗");
                return false;
            }

            if (!await _preflight.RunAsync(server))
            {
                return false;
            }

            var plan = _launchPlanner.CreatePlan(server, inspection.LaunchTarget.Value, javaPath, javaMajor);

            MonitorServerByName(server.Name.Value, server.Path, server.MinecraftVersion.Value);

            await runtime.StartAsync(plan);
            _list.RequestStatusRefresh();

            string? earlyExit = await DetectEarlyExitAsync(serverName, runtime);
            if (earlyExit is not null)
            {
                Logger.Error("伺服器啟動後異常結束：{Message}", earlyExit);
                await _ui.ShowErrorAsync($"伺服器啟動後異常結束：\n{earlyExit}", "伺服器異常結束");
                _list.RequestStatusRefresh();
                return false;
            }

            Logger.Information("伺服器已成功啟動：{Name}（版本：{Version}）", server.Name.Value, server.MinecraftVersion.Value);
            return true;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "啟動伺服器失敗");
            await _ui.ShowErrorAsync($"啟動伺服器失敗：\n{ex.Message}", "啟動伺服器失敗");
            return false;
        }
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public Task StopServerAsync() => _list.RunForSelectedServerAsync(async selected =>
    {
        if (!_runtimeHost.IsRunning(selected.Name))
        {
            return;
        }

        await _stopCoordinator.StopAsync(selected.Name);
        _list.RequestStatusRefresh();
        Logger.Information("伺服器停止流程已結束：{Name}", selected.Name);
    }, "停止伺服器失敗", Logger);

    [RelayCommand(CanExecute = nameof(CanStartOrMonitorServer))]
    public void MonitorServer()
    {
        if (_list.SelectedServer is { HasMissingFiles: false } selected)
        {
            MonitorServerByName(selected.Name, selected.Path, selected.Version);
        }
    }

    /// <summary>開啟（或帶至前景）指定伺服器的監控視窗</summary>
    public void MonitorServerByName(string serverName, string serverPath, string mcVersion)
    {
        if (_monitors.TryGetValue(serverName, out var existing))
        {
            if (existing.Window.IsOpen)
            {
                existing.Window.BringToFront();
                return;
            }

            existing.ViewModel.Dispose();
            _monitors.Remove(serverName);
        }

        var vm = new ServerMonitorViewModel(
            _runtimeHost.GetRuntime(serverName),
            _logReader,
            _propertiesStore,
            serverName,
            _ui,
            serverPath,
            mcVersion,
            _stopCoordinator,
            startRequestHandler: () => StartServerByNameAsync(serverName));
        var window = _ui.OpenServerMonitor(vm);
        Action? onClosed = null;
        onClosed = () =>
        {
            window.Closed -= onClosed;
            if (_monitors.TryGetValue(serverName, out var current) && ReferenceEquals(current.ViewModel, vm))
            {
                _monitors.Remove(serverName);
            }

            vm.Dispose();
        };
        _monitors[serverName] = (window, vm, onClosed);
        window.Closed += onClosed;
    }

    /// <summary>驗證啟動 JAR 或腳本是否確實存在，存在則回傳 null，缺失則回傳檔名</summary>
    private async Task<string?> ResolveMissingLaunchTargetAsync(string serverPath, string launchTarget)
    {
        string target = string.IsNullOrWhiteSpace(launchTarget) ? ServerDefaults.ServerJarFileName : launchTarget.Trim();
        if (target.StartsWith('@'))
        {
            target = target[1..].Trim();
        }

        try
        {
            string fullPath = Path.GetFullPath(Path.Combine(serverPath, target));
            return await _fileSystem.FileExistsAsync(fullPath).ConfigureAwait(false) ? null : target;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "驗證啟動目標路徑失敗");
            return target;
        }
    }

    /// <summary>依據 Minecraft 版本與載入器解析所需的 Java 實體執行檔路徑</summary>
    /// <returns>成功時回傳 (路徑, null)；失敗時回傳 (null, 錯誤訊息)。</returns>
    private async Task<(string? JavaPath, int? JavaMajor, string? Error)> ResolveJavaExecutableAsync(string minecraftVersion)
    {
        int requiredMajor;
        try
        {
            requiredMajor = await _javaRequirementService.GetRequiredJavaMajorAsync(minecraftVersion);
        }
        catch (Exception exception) when (exception is not OperationCanceledException)
        {
            Logger.Error(exception, "查詢 Minecraft {Version} 官方指定的 Java major 版本失敗，已阻擋啟動", minecraftVersion);
            return (null, null, $"無法取得 Minecraft {minecraftVersion} 官方指定的 Java major 版本（請確認網路連線後重試）：{exception.Message}");
        }

        var runtime = await JavaResolutionHelper.FindMatchingJavaAsync(_javaDetector, requiredMajor);
        if (runtime is null)
        {
            string installed = await JavaResolutionHelper.FormatInstalledJavaVersionsAsync(_javaDetector);
            return (null, null, $"Minecraft {minecraftVersion} 官方指定 Java {requiredMajor}，主版本必須完全一致才能啟動；本機已安裝：{installed}。請至「建立伺服器」頁面的「管理 Java」安裝 Java {requiredMajor} 後再啟動");
        }

        Logger.Information(
            "已解析 Minecraft {Version} 的 Java 執行檔：{Path}（major {Major}）",
            minecraftVersion,
            runtime.ExecutablePath,
            runtime.MajorVersion);

        return (runtime.ExecutablePath, runtime.MajorVersion, null);
    }

    /// <summary>啟動後等待行程至多一段時間；異常結束（非使用者主動停止）時回傳錯誤訊息</summary>
    private async Task<string?> DetectEarlyExitAsync(string serverName, IServerRuntime runtime)
    {
        ProcessExitResult? exit = await runtime.WaitForExitAsync(EarlyExitProbeDelay);
        if (exit is null || exit.ExitCode == 0 || exit.WasForceStopped || _stopCoordinator.IsStopping(serverName))
        {
            return null;
        }

        return $"伺服器啟動後立即結束（結束代碼 {exit.ExitCode}），請開啟監控主控台檢視詳細輸出以確認原因";
    }
}
