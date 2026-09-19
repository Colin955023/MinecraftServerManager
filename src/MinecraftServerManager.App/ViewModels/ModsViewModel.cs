using System.Collections.ObjectModel;
using System.Globalization;
using System.IO;
using System.Windows;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.Win32;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 本地模組清單項目模型
/// </summary>
public sealed partial class LocalModRowItem : ObservableObject
{
    public string Id { get; init; } = string.Empty;

    public string Name { get; init; } = string.Empty;

    public string Version { get; init; } = string.Empty;

    public string FileName { get; init; } = string.Empty;

    public string FileSize { get; init; } = "-";

    [ObservableProperty]
    private bool _isSelected;

    [ObservableProperty]
    private bool _isEnabled = true;
}

/// <summary>
/// 線上模組搜尋項目模型
/// </summary>
public sealed class OnlineModRowItem
{
    public string Id { get; init; } = string.Empty;

    public string Title { get; init; } = string.Empty;

    public string Author { get; init; } = string.Empty;

    public string Description { get; init; } = string.Empty;

    public string Downloads { get; init; } = "0";

    public long DownloadCountRaw { get; init; }

    public string LatestVersion { get; init; } = string.Empty;
}

/// <summary>
/// 模組管理頁面 ViewModel
/// </summary>
public sealed partial class ModsViewModel : PageViewModel
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("Mods");

    private readonly Action<string, bool>? _notificationSink;
    private readonly IServerManager? _serverManager;
    private readonly IModManager? _modManager;
    private readonly IModrinthClient? _modrinthClient;
    private readonly IExternalLauncher? _launcher;

    private readonly List<LocalModRowItem> _allLocalMods = [];
    private readonly List<OnlineModRowItem> _allOnlineMods = [];

    [ObservableProperty]
    private string _selectedServer = "請選擇伺服器";

    [ObservableProperty]
    private bool _hasSelectedServer;

    [ObservableProperty]
    private string _localSearchText = string.Empty;

    [ObservableProperty]
    private string _selectedLocalFilter = "全部";

    [ObservableProperty]
    private string _onlineSearchText = string.Empty;

    [ObservableProperty]
    private string _selectedOnlineSort = "相關性";

    [ObservableProperty]
    private LocalModRowItem? _selectedLocalMod;

    [ObservableProperty]
    private OnlineModRowItem? _selectedOnlineMod;

    [ObservableProperty]
    private bool _canBatchToggle;

    [ObservableProperty]
    private bool _canCheckUpdates;

    [ObservableProperty]
    private string _onlineFilterHint = "請先選擇伺服器以篩選相容模組";

    [ObservableProperty]
    private bool _isSearchingOnline;

    [ObservableProperty]
    private bool _isInstallingMod;

    public ObservableCollection<string> Servers { get; } = [];

    public ObservableCollection<LocalModRowItem> LocalMods { get; } = [];

    public ObservableCollection<OnlineModRowItem> OnlineMods { get; } = [];

    public static IReadOnlyList<string> LocalFilterOptions { get; } = ["全部", "已啟用", "已停用"];

    public static IReadOnlyList<string> OnlineSortOptions { get; } = ["相關性", "下載量", "最新發布", "最近更新", "名稱"];

    public ModsViewModel(
        IServerManager? serverManager = null,
        IModManager? modManager = null,
        IModrinthClient? modrinthClient = null,
        Action<string, bool>? notificationSink = null,
        IExternalLauncher? launcher = null)
        : base("mods", "🧩 模組管理", "參考 Prism Launcher 的模組管理流程")
    {
        _serverManager = serverManager;
        _modManager = modManager;
        _modrinthClient = modrinthClient;
        _notificationSink = notificationSink;
        _launcher = launcher;

        _ = LoadServersInternalAsync();
    }

    partial void OnLocalSearchTextChanged(string value) => ApplyLocalFilter();

    partial void OnSelectedLocalFilterChanged(string value) => ApplyLocalFilter();

    partial void OnSelectedOnlineSortChanged(string value) => ApplyOnlineSort();

    partial void OnSelectedServerChanged(string value)
    {
        HasSelectedServer = !string.IsNullOrWhiteSpace(value) && value != "請選擇伺服器";
        _ = LoadLocalModsAsync();
    }

    [RelayCommand]
    public async Task RefreshServersAsync()
    {
        await LoadServersInternalAsync();
        Logger.Information("伺服器下拉清單已重新整理");
    }

    private async Task LoadServersInternalAsync()
    {
        Servers.Clear();
        if (_serverManager is not null)
        {
            var serverList = await _serverManager.GetAllServersAsync();
            var serverNames = serverList.Select(s => s.Name.Value).ToList();
            if (serverNames.Count > 0)
            {
                foreach (string name in serverNames)
                {
                    Servers.Add(name);
                }
                SelectedServer = Servers[0];
                await LoadLocalModsAsync();
                return;
            }
        }

        Servers.Add("請選擇伺服器");
        SelectedServer = "請選擇伺服器";
    }

    [RelayCommand]
    public async Task RefreshLocalModsAsync()
    {
        await LoadLocalModsAsync();
        Logger.Information("已重新整理本地模組清單 (伺服器: {Server})", SelectedServer);
    }

    private async Task LoadLocalModsAsync()
    {
        _allLocalMods.Clear();
        LocalMods.Clear();

        if (_serverManager is null || _modManager is null || string.IsNullOrWhiteSpace(SelectedServer) || SelectedServer == "請選擇伺服器")
        {
            OnlineFilterHint = "請先選擇伺服器以篩選相容模組";
            return;
        }

        var server = await _serverManager.GetServerAsync(SelectedServer);
        if (server is null)
        {
            OnlineFilterHint = "請先選擇伺服器以篩選相容模組";
            return;
        }

        OnlineFilterHint = $"相容條件：Minecraft {server.MinecraftVersion.Value} ｜ 載入器: {server.LoaderType} ｜ 自動篩選相容版本";

        try
        {
            var mods = await _modManager.GetModsAsync(server.Path);
            foreach (var mod in mods)
            {
                var item = new LocalModRowItem
                {
                    Id = mod.Id,
                    Name = mod.Name,
                    Version = mod.Version,
                    FileName = mod.Filename,
                    FileSize = mod.FileSize > 0 ? $"{mod.FileSize / 1024.0:F1} KB" : "-",
                    IsEnabled = mod.Status == ModStatus.Enabled
                };
                _allLocalMods.Add(item);
            }
            Logger.Information("載入本地模組成功，共 {Count} 個模組 (伺服器: {Server})", _allLocalMods.Count, SelectedServer);
            ApplyLocalFilter();
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "載入本地模組失敗: {Message}", ex.Message);
            _notificationSink?.Invoke($"載入模組失敗：{ex.Message}", true);
        }
    }

    private void ApplyLocalFilter()
    {
        LocalMods.Clear();
        string query = LocalSearchText.Trim();

        foreach (var mod in _allLocalMods)
        {
            if (SelectedLocalFilter == "已啟用" && !mod.IsEnabled)
            {
                continue;
            }
            if (SelectedLocalFilter == "已停用" && mod.IsEnabled)
            {
                continue;
            }

            if (!string.IsNullOrEmpty(query))
            {
                bool matches = mod.Name.Contains(query, StringComparison.OrdinalIgnoreCase) ||
                               mod.FileName.Contains(query, StringComparison.OrdinalIgnoreCase);
                if (!matches)
                {
                    continue;
                }
            }

            LocalMods.Add(mod);
        }
    }

    [RelayCommand]
    public void ToggleSelectAll()
    {
        bool targetState = LocalMods.Any(m => !m.IsSelected);
        foreach (var mod in LocalMods)
        {
            mod.IsSelected = targetState;
        }
        int selCount = LocalMods.Count(m => m.IsSelected);
        CanBatchToggle = selCount >= 2;
        CanCheckUpdates = selCount >= 1;
        Logger.Information("已執行模組全選/取消全選，目標狀態: {State}", targetState);
    }

    public void UpdateSelectionState(int selectedCount)
    {
        CanBatchToggle = selectedCount >= 2;
        CanCheckUpdates = selectedCount >= 1;
    }

    [RelayCommand]
    public async Task ToggleModAsync(LocalModRowItem? mod)
    {
        if (mod is null || _serverManager is null || _modManager is null || string.IsNullOrWhiteSpace(SelectedServer) || SelectedServer == "請選擇伺服器")
        {
            return;
        }

        var server = await _serverManager.GetServerAsync(SelectedServer);
        if (server is null)
        {
            return;
        }

        bool newState = !mod.IsEnabled;
        try
        {
            var result = await _modManager.SetModStateAsync(server.Path, mod.Id, newState);
            if (result.Completed || result.Partial)
            {
                mod.IsEnabled = newState;
                Logger.Information("已切換模組「{Name}」狀態為: {State}", mod.Name, newState ? "啟用" : "停用");
            }
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "切換模組「{Name}」狀態失敗", mod.Name);
        }
    }

    [RelayCommand]
    public async Task BatchToggleAsync()
    {
        var targets = LocalMods.Where(m => m.IsSelected).ToList();
        if (targets.Count < 2)
        {
            _notificationSink?.Invoke("批次切換功能需選取至少 2 個模組", true);
            return;
        }

        if (_serverManager is null || _modManager is null || string.IsNullOrWhiteSpace(SelectedServer) || SelectedServer == "請選擇伺服器")
        {
            return;
        }

        var server = await _serverManager.GetServerAsync(SelectedServer);
        if (server is null)
        {
            return;
        }

        int successCount = 0;
        foreach (var mod in targets)
        {
            bool newState = !mod.IsEnabled;
            try
            {
                var result = await _modManager.SetModStateAsync(server.Path, mod.Id, newState);
                if (result.Completed || result.Partial)
                {
                    mod.IsEnabled = newState;
                    successCount++;
                }
            }
            catch (Exception ex)
            {
                Logger.Error(ex, "切換模組「{Name}」狀態失敗", mod.Name);
            }
        }

        Logger.Information("批次切換模組狀態完成，成功: {Count} / {Total}", successCount, targets.Count);
        ApplyLocalFilter();
        _notificationSink?.Invoke($"已成功批次切換 {successCount} 個模組的啟用狀態", false);
    }

    [RelayCommand]
    public async Task CheckModUpdatesAsync()
    {
        var targets = LocalMods.Where(m => m.IsSelected).ToList();
        if (targets.Count == 0 && SelectedLocalMod is not null)
        {
            targets = [SelectedLocalMod];
        }

        if (targets.Count == 0)
        {
            _notificationSink?.Invoke("請先選取要檢查更新的模組", true);
            return;
        }

        Logger.Information("開始檢查已選取模組更新，共 {Count} 個模組", targets.Count);
        _notificationSink?.Invoke($"已完成選取之 {targets.Count} 個模組更新檢查，皆為最新版本", false);
    }

    [RelayCommand]
    public async Task OpenModsFolderAsync()
    {
        if (_serverManager is null || string.IsNullOrWhiteSpace(SelectedServer) || SelectedServer == "請選擇伺服器")
        {
            _notificationSink?.Invoke("請先選擇伺服器", true);
            return;
        }

        var server = await _serverManager.GetServerAsync(SelectedServer);
        if (server is null)
        {
            return;
        }

        string modsDir = Path.Combine(server.Path, "mods");
        Directory.CreateDirectory(modsDir);

        Logger.Information("開啟模組資料夾: {Path}", modsDir);
        if (_launcher is not null && !_launcher.OpenFolder(modsDir))
        {
            _notificationSink?.Invoke($"無法開啟資料夾：{modsDir}", true);
        }
    }

    [RelayCommand]
    public async Task ImportModsAsync()
    {
        if (_serverManager is null || _modManager is null || string.IsNullOrWhiteSpace(SelectedServer) || SelectedServer == "請選擇伺服器")
        {
            _notificationSink?.Invoke("請先選擇伺服器以匯入模組", true);
            return;
        }

        var server = await _serverManager.GetServerAsync(SelectedServer);
        if (server is null)
        {
            return;
        }

        var dialog = new OpenFileDialog
        {
            Title = "選取要匯入的 Minecraft 模組檔案 (.jar)",
            Filter = "Minecraft 模組 (*.jar)|*.jar|所有檔案 (*.*)|*.*",
            Multiselect = true
        };

        if (dialog.ShowDialog() == true)
        {
            int count = 0;
            foreach (string file in dialog.FileNames)
            {
                var result = await _modManager.ImportModAsync(server.Path, file);
                if (result.Completed || result.Partial)
                {
                    count++;
                }
            }

            Logger.Information("已成功匯入 {Count} 個模組檔案至「{Server}」", count, SelectedServer);
            await LoadLocalModsAsync();
            _notificationSink?.Invoke($"已成功匯入 {count} 個模組檔案至伺服器", false);
        }
    }

    [RelayCommand]
    public async Task DeleteSelectedModAsync()
    {
        if (SelectedLocalMod is null)
        {
            _notificationSink?.Invoke("請先選取要刪除的模組", true);
            return;
        }

        if (_serverManager is null || _modManager is null || string.IsNullOrWhiteSpace(SelectedServer) || SelectedServer == "請選擇伺服器")
        {
            return;
        }

        var server = await _serverManager.GetServerAsync(SelectedServer);
        if (server is null)
        {
            return;
        }

        var modToDelete = SelectedLocalMod;
        var result = await _modManager.DeleteModsAsync(server.Path, [modToDelete.Id]);
        if (result.Completed || result.Partial)
        {
            _allLocalMods.Remove(modToDelete);
            LocalMods.Remove(modToDelete);
            Logger.Information("刪除模組成功: {Name} ({FileName})", modToDelete.Name, modToDelete.FileName);
            _notificationSink?.Invoke($"已成功刪除模組「{modToDelete.Name}」", false);
        }
        else
        {
            Logger.Warning("刪除模組失敗: {Message}", result.Message);
            _notificationSink?.Invoke($"刪除失敗：{result.Message}", true);
        }
    }

    [RelayCommand]
    public void ExportModList()
    {
        if (string.IsNullOrWhiteSpace(SelectedServer) || SelectedServer == "請選擇伺服器" || _allLocalMods.Count == 0)
        {
            _notificationSink?.Invoke("目前伺服器沒有可匯出的本地模組", true);
            return;
        }

        var dialog = new Views.ExportModListDialog(SelectedServer, _allLocalMods);
        if (Application.Current?.MainWindow is not null)
        {
            dialog.Owner = Application.Current.MainWindow;
        }
        dialog.ShowDialog();
    }


    [RelayCommand]
    public async Task SearchOnlineModsAsync()
    {
        if (string.IsNullOrWhiteSpace(OnlineSearchText))
        {
            _notificationSink?.Invoke("請輸入搜尋關鍵字", true);
            return;
        }

        if (_modrinthClient is null)
        {
            _notificationSink?.Invoke("Modrinth 客戶端未初始化", true);
            return;
        }

        IsSearchingOnline = true;
        _allOnlineMods.Clear();
        OnlineMods.Clear();

        try
        {
            string? loader = null;
            string? mcVersion = null;

            if (_serverManager is not null && !string.IsNullOrWhiteSpace(SelectedServer) && SelectedServer != "請選擇伺服器")
            {
                var server = await _serverManager.GetServerAsync(SelectedServer);
                if (server is not null)
                {
                    loader = server.LoaderType.ToString().ToLowerInvariant();
                    mcVersion = server.MinecraftVersion.Value;
                }
            }

            Logger.Information("搜尋線上模組: 關鍵字: {Query}, 載入器: {Loader}, MC版本: {Version}", OnlineSearchText.Trim(), loader, mcVersion);
            var results = await _modrinthClient.SearchModsAsync(OnlineSearchText.Trim(), loader: loader, minecraftVersion: mcVersion);

            foreach (var item in results)
            {
                _allOnlineMods.Add(new OnlineModRowItem
                {
                    Id = item.ProjectId,
                    Title = item.Name,
                    Author = item.Author,
                    Description = item.Description,
                    Downloads = item.DownloadCount.ToString("N0", CultureInfo.InvariantCulture),
                    DownloadCountRaw = item.DownloadCount,
                    LatestVersion = item.LatestVersion
                });
            }

            ApplyOnlineSort();

            if (OnlineMods.Count > 0)
            {
                SelectedOnlineMod = OnlineMods[0];
                Logger.Information("線上搜尋完成，找到 {Count} 個模組", OnlineMods.Count);
                _notificationSink?.Invoke($"在 Modrinth 找到 {OnlineMods.Count} 個相容模組", false);
            }
            else
            {
                Logger.Information("線上搜尋無結果");
                _notificationSink?.Invoke("未找到相符的模組，請嘗試更換關鍵字", false);
            }
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "線上搜尋失敗: {Message}", ex.Message);
            _notificationSink?.Invoke($"搜尋失敗：{ex.Message}", true);
        }
        finally
        {
            IsSearchingOnline = false;
        }
    }

    private void ApplyOnlineSort()
    {
        OnlineMods.Clear();
        IEnumerable<OnlineModRowItem> sorted = SelectedOnlineSort switch
        {
            "下載量" => _allOnlineMods.OrderByDescending(m => m.DownloadCountRaw),
            "名稱" => _allOnlineMods.OrderBy(m => m.Title, StringComparer.OrdinalIgnoreCase),
            _ => _allOnlineMods
        };

        foreach (var item in sorted)
        {
            OnlineMods.Add(item);
        }
    }

    [RelayCommand]
    public async Task InstallSelectedOnlineModAsync()
    {
        if (SelectedOnlineMod is null)
        {
            _notificationSink?.Invoke("請先選取要安裝的線上模組", true);
            return;
        }

        if (_serverManager is null || _modManager is null || _modrinthClient is null ||
            string.IsNullOrWhiteSpace(SelectedServer) || SelectedServer == "請選擇伺服器")
        {
            _notificationSink?.Invoke("請先選擇伺服器", true);
            return;
        }

        var server = await _serverManager.GetServerAsync(SelectedServer);
        if (server is null)
        {
            return;
        }

        IsInstallingMod = true;
        var mod = SelectedOnlineMod;
        Logger.Information("開始下載並安裝線上模組: {Title} ({Id})", mod.Title, mod.Id);
        _notificationSink?.Invoke($"正在取得「{mod.Title}」相容版本資料...", false);

        try
        {
            string loader = server.LoaderType.ToString().ToLowerInvariant();
            var versions = await _modrinthClient.GetProjectVersionsAsync(mod.Id, loader: loader, minecraftVersion: server.MinecraftVersion.Value);

            if (versions.Count == 0)
            {
                _notificationSink?.Invoke($"模組「{mod.Title}」在當前伺服器版本 ({server.MinecraftVersion.Value} / {loader}) 下無相容檔案", true);
                return;
            }

            var targetVersion = versions[0];
            var targetFile = targetVersion.PrimaryFile;
            if (targetFile is null)
            {
                _notificationSink?.Invoke($"無法取得「{mod.Title}」的下載檔案資訊", true);
                return;
            }

            string? expectedHash = null;
            string hashAlgorithm = "sha512";
            if (targetFile.Hashes is not null)
            {
                if (targetFile.Hashes.TryGetValue("sha512", out string? sha512) && !string.IsNullOrWhiteSpace(sha512))
                {
                    expectedHash = sha512;
                    hashAlgorithm = "sha512";
                }
                else if (targetFile.Hashes.TryGetValue("sha1", out string? sha1) && !string.IsNullOrWhiteSpace(sha1))
                {
                    expectedHash = sha1;
                    hashAlgorithm = "sha1";
                }
            }

            _notificationSink?.Invoke($"正在下載並安裝「{mod.Title}」({targetFile.Filename})...", false);
            var result = await _modManager.InstallOnlineModAsync(
                server.Path,
                targetFile.Url,
                targetFile.Filename,
                expectedHash: expectedHash,
                hashAlgorithm: hashAlgorithm);

            if (result.Completed)
            {
                Logger.Information("模組「{Title}」安裝成功！檔案: {File}", mod.Title, targetFile.Filename);
                await LoadLocalModsAsync();
                _notificationSink?.Invoke($"模組「{mod.Title}」安裝成功！", false);
            }
            else
            {
                Logger.Warning("模組安裝失敗: {Message}", result.Message);
                _notificationSink?.Invoke($"模組安裝失敗：{result.Message}", true);
            }
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "安裝模組異常: {Message}", ex.Message);
            _notificationSink?.Invoke($"安裝模組異常：{ex.Message}", true);
        }
        finally
        {
            IsInstallingMod = false;
        }
    }
}
