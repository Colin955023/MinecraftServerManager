using System.Collections.ObjectModel;
using System.Globalization;
using System.IO;
using System.Windows;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.Win32;
using MinecraftServerManager.App.Views;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;
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

    public string Author { get; init; } = "-";

    public string LoaderType { get; init; } = "-";

    public string ModifiedTime { get; init; } = "-";

    public string Description { get; init; } = string.Empty;

    public string CurrentHash { get; init; } = string.Empty;

    public string HashAlgorithm { get; init; } = string.Empty;

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
/// 待安裝模組佇列項目
/// </summary>
public sealed class ModInstallQueueItem
{
    public string ProjectId { get; init; } = string.Empty;

    public string Title { get; init; } = string.Empty;

    public string VersionNumber { get; init; } = string.Empty;

    public string FileName { get; init; } = string.Empty;

    public string DownloadUrl { get; init; } = string.Empty;

    public string? ExpectedHash { get; init; }

    public string HashAlgorithm { get; init; } = "sha512";

    public IReadOnlyList<string> Dependencies { get; init; } = [];
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

    /// <summary>
    /// 本地模組載入防重入旗標。
    /// </summary>
    private bool _isLoadingMods;

    /// <summary>
    /// 伺服器清單載入防重入旗標。
    /// </summary>
    private bool _isLoadingServers;

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

    /// <summary>
    /// 線上搜尋結果提示。
    /// </summary>
    [ObservableProperty]
    private string _onlineResultHint = string.Empty;

    [ObservableProperty]
    private string _installQueueHint = "安裝清單：0 個項目";

    public ObservableCollection<string> Servers { get; } = [];

    /// <summary>
    /// 待安裝模組佇列。
    /// </summary>
    public ObservableCollection<ModInstallQueueItem> InstallQueue { get; } = [];

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
        if (_isLoadingServers)
        {
            return;
        }

        _isLoadingServers = true;
        try
        {
            string previous = SelectedServer;
            Servers.Clear();

            if (_serverManager is not null)
            {
                var allServers = await _serverManager.GetAllServersAsync();
                var serverList = allServers.Where(s => s.LoaderType is LoaderKind.Fabric or LoaderKind.Forge or LoaderKind.NeoForge or LoaderKind.Quilt).ToList();
                var serverNames = serverList.Select(s => s.Name.Value).ToList();
                if (serverNames.Count > 0)
                {
                    foreach (string name in serverNames)
                    {
                        Servers.Add(name);
                    }

                    // 保留既有選取項目，避免刷新後重置回第一筆
                    string target = serverNames.Contains(previous, StringComparer.OrdinalIgnoreCase)
                        ? previous
                        : serverNames[0];

                    if (string.Equals(SelectedServer, target, StringComparison.Ordinal))
                    {
                        // 選取值未變更不會觸發 OnSelectedServerChanged，需主動載入一次
                        await LoadLocalModsAsync();
                    }
                    else
                    {
                        // 指派後由 OnSelectedServerChanged 單一路徑觸發載入，不重複呼叫
                        SelectedServer = target;
                    }

                    return;
                }
            }

            Servers.Add("請選擇伺服器");
            SelectedServer = "請選擇伺服器";
        }
        finally
        {
            _isLoadingServers = false;
        }
    }

    [RelayCommand]
    public async Task RefreshLocalModsAsync()
    {
        await LoadLocalModsAsync();
        Logger.Information("已重新整理本地模組清單 (伺服器: {Server})", SelectedServer);
    }

    private async Task LoadLocalModsAsync()
    {
        if (_isLoadingMods)
        {
            return;
        }

        _isLoadingMods = true;
        try
        {
            _allLocalMods.Clear();
            LocalMods.Clear();
            SelectedLocalMod = null;
            CanBatchToggle = false;
            CanCheckUpdates = false;

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

            var mods = await _modManager.GetModsAsync(server.Path);

            // 清空後再加入，並以檔名去重，杜絕重複列項
            _allLocalMods.Clear();
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var mod in mods)
            {
                string dedupeKey = !string.IsNullOrWhiteSpace(mod.Filename) ? mod.Filename : mod.Id;
                if (!seen.Add(dedupeKey))
                {
                    continue;
                }

                _allLocalMods.Add(new LocalModRowItem
                {
                    Id = mod.Id,
                    Name = mod.Name,
                    Version = string.IsNullOrWhiteSpace(mod.Version) ? "-" : mod.Version,
                    FileName = mod.Filename,
                    FileSize = FormatModSize(mod.FileSize),
                    Author = string.IsNullOrWhiteSpace(mod.Author) ? "-" : mod.Author,
                    LoaderType = string.IsNullOrWhiteSpace(mod.LoaderType) ? "-" : mod.LoaderType,
                    ModifiedTime = FormatModTime(mod.FileMtime),
                    Description = mod.Description,
                    IsEnabled = mod.Status == ModStatus.Enabled,
                    CurrentHash = mod.CurrentHash,
                    HashAlgorithm = mod.HashAlgorithm
                });
            }

            Logger.Information("載入本地模組成功，共 {Count} 個模組 (伺服器: {Server})", _allLocalMods.Count, SelectedServer);
            ApplyLocalFilter();
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "載入本地模組失敗: {Message}", ex.Message);
            _notificationSink?.Invoke($"載入模組失敗：{ex.Message}", true);
        }
        finally
        {
            _isLoadingMods = false;
        }
    }

    private static string FormatModSize(long bytes) => bytes switch
    {
        >= 1024L * 1024 => $"{bytes / (1024.0 * 1024):F2} MB",
        >= 1024L => $"{bytes / 1024.0:F2} KB",
        > 0 => $"{bytes} B",
        _ => "-"
    };

    private static string FormatModTime(double unixSeconds)
    {
        if (unixSeconds <= 0)
        {
            return "-";
        }

        try
        {
            return DateTimeOffset.FromUnixTimeSeconds((long)unixSeconds)
                .ToLocalTime()
                .ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture);
        }
        catch
        {
            return "-";
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

        UpdateSelectionState(LocalMods.Count(m => m.IsSelected));
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
                string targetIdentifier = !string.IsNullOrEmpty(mod.FileName) ? mod.FileName : mod.Id;
                var result = await _modManager.SetModStateAsync(server.Path, targetIdentifier, newState);
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
    }

    [RelayCommand]
    public async Task CheckModUpdatesAsync()
    {
        var targets = LocalMods.Where(m => m.IsSelected).ToList();
        if (targets.Count == 0)
        {
            _notificationSink?.Invoke("請先選取要檢查更新的模組", true);
            return;
        }

        if (_serverManager is null || _modrinthClient is null || string.IsNullOrWhiteSpace(SelectedServer) || SelectedServer == "請選擇伺服器")
        {
            _notificationSink?.Invoke("請先選擇伺服器以檢查更新", true);
            return;
        }

        var server = await _serverManager.GetServerAsync(SelectedServer);
        if (server is null)
        {
            return;
        }

        Logger.Information("開始檢查已選取模組更新，共 {Count} 個模組", targets.Count);
        _notificationSink?.Invoke($"正在檢查 {targets.Count} 個模組的更新...", false);

        string loader = server.LoaderType.ToString().ToLowerInvariant();
        string mcVer = server.MinecraftVersion.Value;
        var candidates = new List<ModUpdateCandidateItem>();

        ModOperationProgressDialog? progressDialog = null;
        if (Application.Current is not null)
        {
            progressDialog = new ModOperationProgressDialog("檢查模組更新中", "正在連接 Modrinth 查詢最新相容版本...");
            if (Application.Current.MainWindow is not null)
            {
                progressDialog.Owner = Application.Current.MainWindow;
            }
            progressDialog.Show();
        }

        try
        {
            for (int i = 0; i < targets.Count; i++)
            {
                var mod = targets[i];
                progressDialog?.UpdateProgress(i + 1, targets.Count, $"正在檢查 ({i + 1}/{targets.Count}): {mod.Name}...");

                try
                {
                    IReadOnlyList<OnlineModVersion> versions = [];

                    if (!string.IsNullOrWhiteSpace(mod.CurrentHash) && !string.IsNullOrWhiteSpace(mod.HashAlgorithm))
                    {
                        var lookup = await _modrinthClient.LookupVersionByHashAsync(mod.CurrentHash, mod.HashAlgorithm.ToLowerInvariant());
                        if (lookup is not null && !string.IsNullOrWhiteSpace(lookup.ProjectId))
                        {
                            versions = await _modrinthClient.GetProjectVersionsAsync(lookup.ProjectId, loader: loader, minecraftVersion: mcVer);
                        }
                    }

                    if (versions.Count == 0)
                    {
                        versions = await _modrinthClient.GetProjectVersionsAsync(mod.Id, loader: loader, minecraftVersion: mcVer);
                    }

                    if (versions.Count == 0)
                    {
                        var search = await _modrinthClient.SearchModsAsync(mod.Name, loader: loader, minecraftVersion: mcVer);
                        var matched = search.FirstOrDefault(p => string.Equals(p.Name, mod.Name, StringComparison.OrdinalIgnoreCase) || string.Equals(p.Slug, mod.Id, StringComparison.OrdinalIgnoreCase));
                        if (matched is not null)
                        {
                            versions = await _modrinthClient.GetProjectVersionsAsync(matched.ProjectId, loader: loader, minecraftVersion: mcVer);
                        }
                    }

                    if (versions.Count > 0)
                    {
                        var latest = versions[0];
                        var primaryFile = latest.PrimaryFile;
                        if (primaryFile is not null &&
                            !string.IsNullOrWhiteSpace(latest.VersionNumber) &&
                            !string.Equals(latest.VersionNumber, mod.Version, StringComparison.OrdinalIgnoreCase) &&
                            !string.Equals(mod.Version, "-", StringComparison.Ordinal) &&
                            !string.IsNullOrWhiteSpace(primaryFile.Url))
                        {
                            string? sha512 = null;
                            string? sha1 = null;
                            if (primaryFile.Hashes is not null)
                            {
                                primaryFile.Hashes.TryGetValue("sha512", out sha512);
                                primaryFile.Hashes.TryGetValue("sha1", out sha1);
                            }
                            string? expectedHash = sha512 ?? sha1;
                            string? hashAlgo = sha512 is not null ? "sha512" : (sha1 is not null ? "sha1" : null);

                            candidates.Add(new ModUpdateCandidateItem
                            {
                                ModName = mod.Name,
                                CurrentVersion = mod.Version,
                                NewVersion = latest.VersionNumber,
                                FileName = !string.IsNullOrWhiteSpace(primaryFile.Filename) ? primaryFile.Filename : $"{mod.Name}-{latest.VersionNumber}.jar",
                                DownloadUrl = primaryFile.Url,
                                ExpectedHash = expectedHash,
                                HashAlgorithm = hashAlgo,
                                LocalMod = mod,
                            });
                        }
                    }
                }
                catch (Exception ex)
                {
                    Logger.Warning("檢查模組「{Name}」更新失敗: {Error}", mod.Name, ex.Message);
                }
            }
        }
        finally
        {
            progressDialog?.Close();
        }

        if (candidates.Count > 0)
        {
            _notificationSink?.Invoke($"發現 {candidates.Count} 個模組有可用更新", false);
            var updateDialog = new ModUpdatesDialog(candidates);
            if (Application.Current?.MainWindow is not null)
            {
                updateDialog.Owner = Application.Current.MainWindow;
            }

            if (updateDialog.ShowDialog() == true)
            {
                var toUpdate = updateDialog.GetSelectedItems();
                if (toUpdate.Count > 0)
                {
                    await PerformModUpdatesAsync(server.Path, toUpdate).ConfigureAwait(true);
                    await LoadLocalModsAsync().ConfigureAwait(true);
                    _notificationSink?.Invoke($"已成功更新 {toUpdate.Count} 個模組！", false);
                    DialogHelper.ShowInfo($"成功更新 {toUpdate.Count} 個模組至最新相容版本！", "更新完成");
                }
            }
        }
        else
        {
            DialogHelper.ShowInfo($"檢查完成，所選取的 {targets.Count} 個模組皆為最新相容版本，無需更新。", "已是最新版本");
            _notificationSink?.Invoke($"檢查完成，選取的 {targets.Count} 個模組皆為相容最新版本", false);
        }
    }

    private async Task PerformModUpdatesAsync(string serverPath, IReadOnlyList<ModUpdateCandidateItem> items)
    {
        ModOperationProgressDialog? updateProgressDialog = null;
        if (Application.Current is not null)
        {
            updateProgressDialog = new ModOperationProgressDialog("正在更新模組", "準備下載新版本...");
            if (Application.Current.MainWindow is not null)
            {
                updateProgressDialog.Owner = Application.Current.MainWindow;
            }
            updateProgressDialog.Show();
        }

        try
        {
            for (int i = 0; i < items.Count; i++)
            {
                var item = items[i];
                updateProgressDialog?.UpdateProgress(i + 1, items.Count, $"正在下載並更新 ({i + 1}/{items.Count}): {item.FileName}...");

                if (_modManager is not null)
                {
                    var installResult = await _modManager.InstallOnlineModAsync(
                        serverPath,
                        item.DownloadUrl,
                        item.FileName,
                        item.ExpectedHash,
                        item.HashAlgorithm).ConfigureAwait(false);

                    if (installResult.Completed)
                    {
                        if (!item.LocalMod.IsEnabled)
                        {
                            await _modManager.SetModStateAsync(serverPath, item.FileName, false).ConfigureAwait(false);
                        }

                        if (!string.Equals(item.LocalMod.FileName, item.FileName, StringComparison.OrdinalIgnoreCase))
                        {
                            string oldTarget = !string.IsNullOrEmpty(item.LocalMod.FileName) ? item.LocalMod.FileName : item.LocalMod.Id;
                            await _modManager.DeleteModsAsync(serverPath, [oldTarget]).ConfigureAwait(false);
                        }

                        Logger.Information("成功更新模組「{Name}」至版本 {Version}", item.ModName, item.NewVersion);
                    }
                    else
                    {
                        Logger.Warning("更新模組「{Name}」失敗: {Error}", item.ModName, installResult.Message);
                    }
                }
            }
        }
        finally
        {
            updateProgressDialog?.Close();
        }
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
    public async Task ShowInFolderAsync(LocalModRowItem? mod)
    {
        var targetMod = mod ?? SelectedLocalMod;
        if (targetMod is null)
        {
            return;
        }

        if (_serverManager is null || string.IsNullOrWhiteSpace(SelectedServer) || SelectedServer == "請選擇伺服器")
        {
            return;
        }

        var server = await _serverManager.GetServerAsync(SelectedServer);
        if (server is null)
        {
            return;
        }

        string filePath = Path.Combine(server.Path, "mods", targetMod.FileName);
        if (!File.Exists(filePath))
        {
            string disabledPath = filePath + ".disabled";
            if (File.Exists(disabledPath))
            {
                filePath = disabledPath;
            }
            else
            {
                filePath = Path.Combine(server.Path, "mods");
            }
        }

        if (_launcher is not null && !_launcher.ShowInFolder(filePath))
        {
            _notificationSink?.Invoke($"無法在資料夾中顯示：{filePath}", true);
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
        if (!DialogHelper.Confirm(
            $"確定要刪除模組「{modToDelete.Name}」嗎？\n此操作將永久刪除對應檔案，無法復原。",
            "確認刪除模組",
            MessageBoxImage.Warning))
        {
            return;
        }

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

        var dialog = new ExportModListDialog(SelectedServer, _allLocalMods);
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
                OnlineResultHint = $"在 Modrinth 找到 {OnlineMods.Count} 個相容模組";
            }
            else
            {
                Logger.Information("線上搜尋無結果");
                OnlineResultHint = "未找到相符的模組，請嘗試更換關鍵字";
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

    /// <summary>
    /// 取得所有相容版本並彈出版本選擇對話框。
    /// </summary>
    [RelayCommand]
    public async Task PickOnlineModVersionAsync(OnlineModRowItem? mod)
    {
        mod ??= SelectedOnlineMod;
        if (mod is null || _modrinthClient is null)
        {
            return;
        }

        string? loader = null;
        string? mcVersion = null;
        if (_serverManager is not null && HasSelectedServer)
        {
            var server = await _serverManager.GetServerAsync(SelectedServer);
            if (server is not null)
            {
                loader = server.LoaderType.ToString().ToLowerInvariant();
                mcVersion = server.MinecraftVersion.Value;
            }
        }

        var pickerVm = new ModVersionPickerViewModel(_modrinthClient, mod.Id, mod.Title, loader, mcVersion);
        var dialog = new ModVersionPickerDialog(pickerVm);
        if (Application.Current?.MainWindow is not null)
        {
            dialog.Owner = Application.Current.MainWindow;
        }

        if (dialog.ShowDialog() != true || pickerVm.QueuedVersion is null)
        {
            return;
        }

        var chosen = pickerVm.QueuedVersion;
        var queueItem = new ModInstallQueueItem
        {
            ProjectId = mod.Id,
            Title = mod.Title,
            VersionNumber = chosen.VersionNumber,
            FileName = chosen.FileName,
            DownloadUrl = chosen.DownloadUrl,
            ExpectedHash = chosen.ExpectedHash,
            HashAlgorithm = chosen.HashAlgorithm,
            Dependencies = chosen.Dependencies
        };

        if (!InstallQueue.Any(i => string.Equals(i.FileName, queueItem.FileName, StringComparison.OrdinalIgnoreCase)))
        {
            InstallQueue.Add(queueItem);
        }

        UpdateInstallQueueHint();

        if (pickerVm.InstallImmediately)
        {
            await InstallQueuedModsAsync();
        }
    }

    /// <summary>
    /// 將目前選取的線上模組導向版本選擇流程。
    /// </summary>
    [RelayCommand]
    public async Task QueueSelectedOnlineModAsync()
    {
        if (SelectedOnlineMod is null)
        {
            _notificationSink?.Invoke("請先選取要安裝的線上模組", true);
            return;
        }

        await PickOnlineModVersionAsync(SelectedOnlineMod);
    }

    /// <summary>
    /// 進行相依性檢測後統一批次下載安裝。
    /// </summary>
    [RelayCommand]
    public async Task InstallQueuedModsAsync()
    {
        if (InstallQueue.Count == 0)
        {
            _notificationSink?.Invoke("安裝清單目前沒有項目", true);
            return;
        }

        if (_serverManager is null || _modManager is null || !HasSelectedServer)
        {
            _notificationSink?.Invoke("請先選擇伺服器", true);
            return;
        }

        var server = await _serverManager.GetServerAsync(SelectedServer);
        if (server is null)
        {
            return;
        }

        // 相依性檢測：警示清單中尚未涵蓋的必要相依模組
        var queuedProjects = InstallQueue.Select(i => i.ProjectId).ToHashSet(StringComparer.OrdinalIgnoreCase);
        var missingDependencies = InstallQueue
            .SelectMany(i => i.Dependencies)
            .Where(id => !queuedProjects.Contains(id))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        if (missingDependencies.Count > 0)
        {
            Logger.Warning("安裝清單存在未涵蓋的相依模組，共 {Count} 項", missingDependencies.Count);
            _notificationSink?.Invoke($"注意：安裝清單有 {missingDependencies.Count} 個未納入的相依模組，安裝後可能無法正常載入", true);
        }

        IsInstallingMod = true;
        int success = 0;
        var pending = InstallQueue.ToList();

        try
        {
            foreach (var item in pending)
            {
                try
                {
                    var result = await _modManager.InstallOnlineModAsync(
                        server.Path,
                        item.DownloadUrl,
                        item.FileName,
                        expectedHash: item.ExpectedHash,
                        hashAlgorithm: item.HashAlgorithm);

                    if (result.Completed)
                    {
                        success++;
                        InstallQueue.Remove(item);
                    }
                    else
                    {
                        Logger.Warning("模組「{Title}」安裝失敗: {Message}", item.Title, result.Message);
                        _notificationSink?.Invoke($"模組「{item.Title}」安裝失敗：{result.Message}", true);
                    }
                }
                catch (Exception exception)
                {
                    Logger.Error(exception, "安裝模組「{Title}」異常: {Message}", item.Title, exception.Message);
                    _notificationSink?.Invoke($"安裝「{item.Title}」異常：{exception.Message}", true);
                }
            }

            Logger.Information("批次安裝完成，成功 {Success} / {Total}", success, pending.Count);
            await LoadLocalModsAsync();
        }
        finally
        {
            IsInstallingMod = false;
            UpdateInstallQueueHint();
        }
    }

    /// <summary>
    /// 檢視待安裝清單內容而不執行安裝。
    /// </summary>
    [RelayCommand]
    public void ViewInstallQueue()
    {
        if (InstallQueue.Count == 0)
        {
            DialogHelper.ShowInfo("目前安裝清單沒有任何待安裝項目。\n\n您可以在「瀏覽模組」清單中雙擊模組，選擇版本並加入安裝清單。", "安裝清單");
            return;
        }

        string items = string.Join("\n", InstallQueue.Select((item, idx) => $"{idx + 1}. {item.Title} (版本: {item.VersionNumber}, 檔案: {item.FileName})"));
        DialogHelper.ShowInfo($"目前待安裝模組清單 (共 {InstallQueue.Count} 項)：\n\n{items}\n\n確認無誤後，可點擊「開始安裝」按鈕批次下載與安裝。", "檢視安裝清單");
    }

    /// <summary>
    /// 清空安裝清單。
    /// </summary>
    [RelayCommand]
    public void ClearInstallQueue()
    {
        InstallQueue.Clear();
        UpdateInstallQueueHint();
    }

    /// <summary>
    /// 於瀏覽器開啟選取模組的 Modrinth 頁面。
    /// </summary>
    [RelayCommand]
    public void OpenModrinthPage()
    {
        if (SelectedOnlineMod is null)
        {
            _notificationSink?.Invoke("請先選取要檢視的線上模組", true);
            return;
        }

        string url = $"https://modrinth.com/mod/{SelectedOnlineMod.Id}";
        if (_launcher is not null && !_launcher.OpenUrl(url))
        {
            _notificationSink?.Invoke($"無法開啟連結：{url}", true);
        }
    }

    private void UpdateInstallQueueHint() =>
        InstallQueueHint = $"安裝清單：{InstallQueue.Count} 個項目";

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
