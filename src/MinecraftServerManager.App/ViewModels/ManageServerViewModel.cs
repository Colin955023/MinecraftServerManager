using System.Collections.ObjectModel;
using System.IO;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Views;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Servers;
using MinecraftServerManager.Infrastructure.Settings;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 伺服器列表項目模型（對齊 ManageServerFrame 的 7 個欄位）
/// </summary>
public sealed class ServerRowItem
{
    public string Name { get; init; } = string.Empty;

    public string Version { get; init; } = string.Empty;

    public string Loader { get; init; } = string.Empty;

    public string Status { get; init; } = "已停止";

    public string Size { get; init; } = "-";

    public string BackupStatus { get; init; } = "無備份";

    public string Path { get; init; } = string.Empty;
}

/// <summary>
/// 管理伺服器頁面 ViewModel
/// </summary>
public sealed partial class ManageServerViewModel : PageViewModel
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("ManageServer");

    private readonly SettingsManager? _settingsManager;
    private readonly IServerManager? _serverManager;
    private readonly IServerBackupService? _backupService;
    private readonly IServerRuntime? _serverRuntime;
    private readonly IServerInspector? _serverInspector;
    private readonly IServerLaunchPlanner? _launchPlanner;
    private readonly IServerPropertiesStore? _propertiesStore;
    private readonly IExternalLauncher? _launcher;
    private readonly Action<string>? _navigateCallback;
    private readonly Action<string, bool>? _notificationSink;

    [ObservableProperty]
    private string _detectPath = string.Empty;

    [ObservableProperty]
    private ServerRowItem? _selectedServer;

    [ObservableProperty]
    private string _selectedServerInfo = "選擇一個伺服器以查看詳細資訊";

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(StartServerCommand))]
    [NotifyCanExecuteChangedFor(nameof(StopServerCommand))]
    [NotifyCanExecuteChangedFor(nameof(MonitorServerCommand))]
    [NotifyCanExecuteChangedFor(nameof(ConfigureServerCommand))]
    [NotifyCanExecuteChangedFor(nameof(OpenServerFolderCommand))]
    [NotifyCanExecuteChangedFor(nameof(BackupServerCommand))]
    [NotifyCanExecuteChangedFor(nameof(RestoreBackupCommand))]
    [NotifyCanExecuteChangedFor(nameof(DeleteServerCommand))]
    private bool _hasSelectedServer;

    public ManageServerViewModel(
        SettingsManager? settingsManager = null,
        IServerManager? serverManager = null,
        IServerBackupService? backupService = null,
        IServerRuntime? serverRuntime = null,
        IServerInspector? serverInspector = null,
        IServerLaunchPlanner? launchPlanner = null,
        IServerPropertiesStore? propertiesStore = null,
        Action<string>? navigateCallback = null,
        Action<string, bool>? notificationSink = null,
        IExternalLauncher? launcher = null)
        : base("manage", "管理現有伺服器", "檢視已安裝伺服器清單，進行啟動、停止、設定與備份維護")
    {
        _settingsManager = settingsManager;
        _serverManager = serverManager;
        _backupService = backupService;
        _serverRuntime = serverRuntime;
        _serverInspector = serverInspector ?? new ServerInspector();
        _launchPlanner = launchPlanner ?? new ServerLaunchPlanner();
        _propertiesStore = propertiesStore;
        _navigateCallback = navigateCallback;
        _notificationSink = notificationSink;
        _launcher = launcher;

        _detectPath = ResolveServersDirectory();
        Servers = [];
    }

    public ObservableCollection<ServerRowItem> Servers { get; }

    private string ResolveServersDirectory()
    {
        if (_settingsManager is null)
        {
            return string.Empty;
        }

        try
        {
            return _settingsManager.GetValidatedServersRootPath();
        }
        catch
        {
            return _settingsManager.GetServersRoot();
        }
    }

    partial void OnSelectedServerChanged(ServerRowItem? value)
    {
        HasSelectedServer = value is not null;
        SelectedServerInfo = value is not null
            ? $"已選取伺服器：{value.Name} ({value.Version} / {value.Loader}) — 狀態：{value.Status}"
            : "選擇一個伺服器以查看詳細資訊";
    }

    [RelayCommand]
    public async Task DetectServers() => await RefreshServers();

    [RelayCommand]
    public void AddServer() => _navigateCallback?.Invoke("create");

    [RelayCommand]
    public async Task RefreshServers()
    {
        DetectPath = ResolveServersDirectory();
        if (_serverManager is not null)
        {
            try
            {
                var serverEntries = await _serverManager.GetAllServersAsync();
                Servers.Clear();
                foreach (var s in serverEntries)
                {
                    Servers.Add(new ServerRowItem
                    {
                        Name = s.Name.Value,
                        Version = s.MinecraftVersion.Value,
                        Loader = s.LoaderType.ToString(),
                        Status = _serverRuntime?.IsRunning == true ? "執行中" : "已停止",
                        Path = s.Path
                    });
                }
                Logger.Information("成功重新整理伺服器清單，共 {Count} 個伺服器，路徑: {Path}", Servers.Count, DetectPath);
                _notificationSink?.Invoke($"已成功重新整理伺服器列表（共 {Servers.Count} 個）", false);
                return;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "載入伺服器清單失敗: {Message}", ex.Message);
                _notificationSink?.Invoke($"載入伺服器清單失敗：{ex.Message}", true);
                return;
            }
        }

        _notificationSink?.Invoke("已重新整理伺服器列表", false);
    }

    /// <summary>
    /// 重新整理伺服器清單並選取指定名稱之伺服器
    /// </summary>
    public async Task RefreshAndSelectServerAsync(string serverName)
    {
        await RefreshServers();
        var target = Servers.FirstOrDefault(s => string.Equals(s.Name, serverName, StringComparison.OrdinalIgnoreCase));
        if (target is not null)
        {
            SelectedServer = target;
        }
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task StartServer()
    {
        if (SelectedServer is null)
        {
            return;
        }

        if (_serverRuntime is not null && _serverManager is not null)
        {
            try
            {
                var server = await _serverManager.GetServerAsync(SelectedServer.Name);
                if (server is not null)
                {
                    // 透過 ServerInspector 與 ServerLaunchPlanner 建立強型別啟動計畫
                    var inspection = await _serverInspector!.InspectAsync(server.Path).ConfigureAwait(true);
                    var plan = _launchPlanner!.CreatePlan(server, inspection);

                    await _serverRuntime.StartAsync(plan).ConfigureAwait(true);

                    SelectedServer = new ServerRowItem
                    {
                        Name = SelectedServer.Name,
                        Version = SelectedServer.Version,
                        Loader = SelectedServer.Loader,
                        Status = "執行中",
                        Size = SelectedServer.Size,
                        BackupStatus = SelectedServer.BackupStatus,
                        Path = SelectedServer.Path
                    };
                    Logger.Information("伺服器已成功啟動: {Name} (版本: {Version})", server.Name.Value, server.MinecraftVersion.Value);
                    _notificationSink?.Invoke($"伺服器「{server.Name.Value}」已依據啟動計畫成功啟動", false);
                    return;
                }
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "啟動伺服器失敗: {Message}", ex.Message);
                _notificationSink?.Invoke($"啟動伺服器失敗：{ex.Message}", true);
                return;
            }
        }

        _notificationSink?.Invoke($"啟動伺服器「{SelectedServer.Name}」", false);
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task StopServer()
    {
        if (SelectedServer is null)
        {
            return;
        }

        if (_serverRuntime is not null && _serverRuntime.IsRunning)
        {
            try
            {
                await _serverRuntime.StopAsync(TimeSpan.FromSeconds(10)).ConfigureAwait(true);
                SelectedServer = new ServerRowItem
                {
                    Name = SelectedServer.Name,
                    Version = SelectedServer.Version,
                    Loader = SelectedServer.Loader,
                    Status = "已停止",
                    Size = SelectedServer.Size,
                    BackupStatus = SelectedServer.BackupStatus,
                    Path = SelectedServer.Path
                };
                Logger.Information("伺服器已成功停止: {Name}", SelectedServer.Name);
                _notificationSink?.Invoke($"已成功停止伺服器「{SelectedServer.Name}」", false);
                return;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "停止伺服器失敗: {Message}", ex.Message);
                _notificationSink?.Invoke($"停止伺服器失敗：{ex.Message}", true);
                return;
            }
        }

        _notificationSink?.Invoke($"停止伺服器「{SelectedServer.Name}」", false);
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public void MonitorServer()
    {
        if (SelectedServer is null)
        {
            return;
        }

        if (_serverRuntime is not null)
        {
            var vm = new ServerMonitorViewModel(_serverRuntime, SelectedServer.Name, SelectedServer.Path, SelectedServer.Version);
            var win = new ServerMonitorWindow(vm);
            win.Show();
            _notificationSink?.Invoke($"已開啟伺服器「{SelectedServer.Name}」獨立監控主控台", false);
            return;
        }

        _notificationSink?.Invoke($"開啟伺服器「{SelectedServer.Name}」主控台與效能監控", false);
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public void ConfigureServer()
    {
        if (SelectedServer is null)
        {
            return;
        }

        var store = _propertiesStore ?? (!string.IsNullOrWhiteSpace(_settingsManager?.GetServersRoot()) ? new ServerPropertiesStore(_settingsManager.GetServersRoot()) : null);
        if (store is not null)
        {
            var vm = new ServerPropertiesViewModel(store, SelectedServer.Name);
            var dialog = new ServerPropertiesDialog(vm);
            if (dialog.ShowDialog() == true)
            {
                _notificationSink?.Invoke($"伺服器「{SelectedServer.Name}」屬性設定已更新", false);
            }
            return;
        }

        _notificationSink?.Invoke($"開啟伺服器「{SelectedServer.Name}」設定", false);
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public void OpenServerFolder()
    {
        if (SelectedServer is null)
        {
            return;
        }

        if (!Directory.Exists(SelectedServer.Path))
        {
            _notificationSink?.Invoke($"資料夾不存在：{SelectedServer.Path}", true);
            return;
        }

        if (_launcher is not null)
        {
            if (_launcher.OpenFolder(SelectedServer.Path))
            {
                _notificationSink?.Invoke($"已開啟伺服器資料夾：{SelectedServer.Path}", false);
            }
            else
            {
                _notificationSink?.Invoke($"無法開啟資料夾：{SelectedServer.Path}", true);
            }
        }
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task BackupServer()
    {
        if (SelectedServer is null)
        {
            return;
        }

        if (_backupService is not null)
        {
            try
            {
                var backup = await _backupService.CreateBackupAsync(SelectedServer.Name);
                Logger.Information("伺服器「{Name}」備份建立成功: {File}", SelectedServer.Name, backup.FileName);
                _notificationSink?.Invoke($"已成功建立伺服器「{SelectedServer.Name}」備份：{backup.FileName}", false);
                return;
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "備份伺服器失敗: {Message}", ex.Message);
                _notificationSink?.Invoke($"備份伺服器失敗：{ex.Message}", true);
                return;
            }
        }

        _notificationSink?.Invoke($"建立伺服器「{SelectedServer.Name}」備份", false);
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public void RestoreBackup()
    {
        if (SelectedServer is null)
        {
            return;
        }

        if (_backupService is not null)
        {
            var vm = new RestoreBackupViewModel(_backupService, SelectedServer.Name);
            var dialog = new RestoreBackupDialog(vm);
            if (dialog.ShowDialog() == true)
            {
                Logger.Information("伺服器「{Name}」備份已成功還原", SelectedServer.Name);
                _notificationSink?.Invoke($"伺服器「{SelectedServer.Name}」備份已安全還原", false);
            }
            return;
        }

        _notificationSink?.Invoke($"還原伺服器「{SelectedServer.Name}」備份", false);
    }

    [RelayCommand(CanExecute = nameof(HasSelectedServer))]
    public async Task DeleteServer()
    {
        if (SelectedServer is null)
        {
            return;
        }

        string name = SelectedServer.Name;
        if (_serverManager is not null)
        {
            try
            {
                var result = await _serverManager.DeleteServerAsync(name);
                if (result.Success)
                {
                    Servers.Remove(SelectedServer);
                    SelectedServer = null;
                    Logger.Information("伺服器「{Name}」已成功刪除", name);
                    _notificationSink?.Invoke($"已成功刪除伺服器「{name}」", false);
                    return;
                }
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "刪除伺服器失敗: {Message}", ex.Message);
                _notificationSink?.Invoke($"刪除伺服器失敗：{ex.Message}", true);
                return;
            }
        }

        _notificationSink?.Invoke($"刪除伺服器「{name}」", false);
    }
}
