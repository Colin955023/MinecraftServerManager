using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Services;
using System.Collections.Concurrent;
using System.Collections.ObjectModel;
using System.Globalization;
using System.IO;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Views;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Mods;

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

    public string MinecraftVersion { get; init; } = "-";

    public long RawFileSize { get; init; }

    public string ModifiedTime { get; init; } = "-";

    public string Description { get; init; } = string.Empty;

    public string CurrentHash { get; init; } = string.Empty;

    public string HashAlgorithm { get; init; } = string.Empty;

    [ObservableProperty]
    public partial bool IsSelected { get; set; }

    [ObservableProperty]
    public partial bool IsEnabled { get; set; } = true;

    [ObservableProperty]
    public partial string SourcePlatform { get; set; } = "-";
}

/// <summary>
/// 線上模組搜尋項目模型
/// </summary>
public sealed class OnlineModRowItem
{
    public string Id { get; init; } = string.Empty;

    public string? Slug { get; init; }

    public string Title { get; init; } = string.Empty;

    public string Author { get; init; } = string.Empty;

    public string Description { get; init; } = string.Empty;

    public string Downloads { get; init; } = "0";

    public long DownloadCountRaw { get; init; }

    public string LatestVersion { get; init; } = string.Empty;

    public string ServerSide { get; init; } = string.Empty;

    public string ClientSide { get; init; } = string.Empty;
}

/// <summary>
/// 待安裝模組佇列項目
/// </summary>
public sealed class ModInstallQueueItem
{
    public string ProjectId { get; init; } = string.Empty;

    public string Title { get; init; } = string.Empty;

    public string VersionNumber { get; init; } = string.Empty;

    public string? CurrentVersion { get; init; }

    public string FileName { get; init; } = string.Empty;

    public string? OldFileName { get; init; }

    public string DownloadUrl { get; init; } = string.Empty;

    public string? ExpectedHash { get; init; }

    public string HashAlgorithm { get; init; } = "sha512";

    public IReadOnlyList<string> Dependencies { get; init; } = [];

    public ModInstallAction Action { get; init; } = ModInstallAction.Install;

    public string ActionText => Action == ModInstallAction.Update ? "更新" : "安裝";

    public string VersionDisplay => Action == ModInstallAction.Update && !string.IsNullOrWhiteSpace(CurrentVersion)
        ? $"{CurrentVersion} ➔ {VersionNumber}"
        : VersionNumber;

    public string Reason { get; init; } = "全新安裝";
}

/// <summary>
/// 模組管理頁面 ViewModel
/// </summary>
public sealed partial class ModsViewModel : PageViewModel
{
    private readonly IUiService _ui;

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("Mods");

    private readonly Action<string, bool>? _notificationSink;
    private readonly IServerManager? _serverManager;
    private readonly IModManager? _modManager;
    private readonly IModrinthClient? _modrinthClient;
    private readonly IExternalLauncher? _launcher;
    private readonly IModDependencyPlanner _dependencyPlanner;
    private readonly IModListExporter _modListExporter;

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
    public partial string SelectedServer { get; set; } = "請選擇伺服器";

    [ObservableProperty]
    public partial bool HasSelectedServer { get; set; }

    [ObservableProperty]
    public partial string LocalSearchText { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string SelectedLocalFilter { get; set; } = "全部";

    [ObservableProperty]
    public partial string OnlineSearchText { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string SelectedPlatform { get; set; } = "Modrinth";

    public string OpenPlatformPageButtonText => string.Equals(SelectedPlatform, "CurseForge", StringComparison.OrdinalIgnoreCase)
        ? "開啟 CurseForge 頁面"
        : "開啟 Modrinth 頁面";

    [ObservableProperty]
    public partial string SelectedOnlineSort { get; set; } = "相關性";

    [ObservableProperty]
    public partial LocalModRowItem? SelectedLocalMod { get; set; }

    [ObservableProperty]
    public partial OnlineModRowItem? SelectedOnlineMod { get; set; }

    [ObservableProperty]
    public partial bool CanBatchToggle { get; set; }

    [ObservableProperty]
    public partial bool CanCheckUpdates { get; set; }

    [ObservableProperty]
    public partial bool CanDeleteMod { get; set; }

    [ObservableProperty]
    public partial string OnlineFilterHint { get; set; } = "請先選擇伺服器以篩選相容模組";

    [ObservableProperty]
    public partial bool IsSearchingOnline { get; set; }

    [ObservableProperty]
    public partial bool IsInstallingMod { get; set; }

    /// <summary>
    /// 線上搜尋結果提示。
    /// </summary>
    [ObservableProperty]
    public partial string OnlineResultHint { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string InstallQueueHint { get; set; } = "安裝清單：0 個項目";

    [ObservableProperty]
    public partial int SelectedTabIndex { get; set; }
    public ObservableCollection<string> Servers { get; } = [];

    /// <summary>
    /// 待安裝模組佇列。
    /// </summary>
    public ObservableCollection<ModInstallQueueItem> InstallQueue { get; } = [];

    public BulkObservableCollection<LocalModRowItem> LocalMods { get; } = [];

    public BulkObservableCollection<OnlineModRowItem> OnlineMods { get; } = [];

    public static IReadOnlyList<string> LocalFilterOptions { get; } = ["全部", "已啟用", "已停用"];

    public static IReadOnlyList<string> OnlineSortOptions { get; } = ["相關性", "下載量", "最新發布", "最近更新", "名稱"];
    public static IReadOnlyList<string> PlatformOptions { get; } = ["Modrinth", "CurseForge"];

    public ModsViewModel(
        IServerManager? serverManager = null,
        IModManager? modManager = null,
        IModrinthClient? modrinthClient = null,
        Action<string, bool>? notificationSink = null,
        IExternalLauncher? launcher = null,
        IModDependencyPlanner? dependencyPlanner = null,
        IModListExporter? modListExporter = null,
        IUiService? uiService = null)
        : base("mods", "🧩 模組管理", "現代化高效模組管理流程")
    {
        _ui = uiService ?? NoOpUiService.Instance;
        _serverManager = serverManager;
        _modManager = modManager;
        _modrinthClient = modrinthClient;
        _notificationSink = notificationSink;
        _launcher = launcher;
        _dependencyPlanner = dependencyPlanner ?? throw new ArgumentNullException(nameof(dependencyPlanner));
        _modListExporter = modListExporter ?? throw new ArgumentNullException(nameof(modListExporter));

        _ = RunSafeAsync(LoadServersInternalAsync, "初始化伺服器清單", Logger);
    }

    partial void OnSelectedTabIndexChanged(int value)
    {
        if (value == 1 && _allOnlineMods.Count == 0 && !IsSearchingOnline)
        {
            _ = RunSafeAsync(SearchOnlineModsAsync, "搜尋線上模組", Logger);
        }
    }

    partial void OnLocalSearchTextChanged(string value) => ApplyLocalFilter();

    partial void OnSelectedLocalFilterChanged(string value) => ApplyLocalFilter();

    partial void OnSelectedOnlineSortChanged(string value)
    {
        if (value is "名稱" or "下載量")
        {
            ApplyOnlineSort();
        }
        else if ((_allOnlineMods.Count > 0 || SelectedTabIndex == 1) && !IsSearchingOnline)
        {
            _ = RunSafeAsync(SearchOnlineModsAsync, "搜尋線上模組", Logger);
        }
        else
        {
            ApplyOnlineSort();
        }
    }

    partial void OnSelectedPlatformChanged(string value)
    {
        OnPropertyChanged(nameof(OpenPlatformPageButtonText));
        if (value == "CurseForge")
        {
            _allOnlineMods.Clear();
            OnlineMods.Clear();
            SelectedOnlineMod = null;
            OnlineResultHint = "CurseForge 模組搜尋即將推出，敬請期待";
        }
        else
        {
            OnlineResultHint = string.Empty;
            if (SelectedTabIndex == 1)
            {
                _ = RunSafeAsync(SearchOnlineModsAsync, "搜尋線上模組", Logger);
            }
        }
    }

    partial void OnSelectedLocalModChanged(LocalModRowItem? value)
    {
        CanDeleteMod = value is not null || LocalMods.Any(m => m.IsSelected);
        DeleteSelectedModCommand.NotifyCanExecuteChanged();
    }

    partial void OnSelectedServerChanged(string value)
    {
        HasSelectedServer = !string.IsNullOrWhiteSpace(value) && value != "請選擇伺服器";
        _ = RunSafeAsync(LoadLocalModsAsync, "載入本機模組清單", Logger);
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
                var serverList = allServers.Where(static s => s.LoaderType is LoaderKind.Fabric or LoaderKind.Forge or LoaderKind.NeoForge or LoaderKind.Quilt).ToList();
                var serverNames = serverList.Select(static s => s.Name.Value).ToList();
                if (serverNames.Count > 0)
                {
                    foreach (string name in serverNames)
                    {
                        Servers.Add(name);
                    }

                    // 保留既有選取項目，避免重新整理後重設回第一筆
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
        catch (Exception ex)
        {
            Logger.Error(ex, "載入伺服器清單失敗: {Message}", ex.Message);
            _notificationSink?.Invoke($"載入伺服器清單失敗：{ex.Message}", true);
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
            CanDeleteMod = false;
            DeleteSelectedModCommand.NotifyCanExecuteChanged();

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

            OnlineFilterHint = $"相容條件：Minecraft {server.MinecraftVersion.Value} ｜ 載入器: {server.LoaderType} ｜ 僅限伺服器端與兩端相容模組";

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
                    MinecraftVersion = string.IsNullOrWhiteSpace(mod.MinecraftVersion) ? "-" : mod.MinecraftVersion,
                    RawFileSize = mod.FileSize,
                    ModifiedTime = FormatModTime(mod.FileMtime),
                    Description = mod.Description,
                    IsEnabled = mod.Status == ModStatus.Enabled,
                    SourcePlatform = mod.Platform switch
                    {
                        ModPlatform.CurseForge => "CurseForge",
                        _ => "Modrinth"
                    },
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

    private static string FormatModSize(long bytes) =>
        bytes > 0 ? Core.Utilities.UnitFormatter.FormatBytes(bytes) : "-";

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
        string query = LocalSearchText.Trim();
        var filtered = new List<LocalModRowItem>(_allLocalMods.Count);

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

            filtered.Add(mod);
        }

        LocalMods.ReplaceAll(filtered);
        UpdateSelectionState(LocalMods.Count(static m => m.IsSelected));
    }

    [RelayCommand]
    public void ToggleSelectAll()
    {
        bool targetState = LocalMods.Any(static m => !m.IsSelected);
        foreach (var mod in LocalMods)
        {
            mod.IsSelected = targetState;
        }
        int selCount = LocalMods.Count(static m => m.IsSelected);
        UpdateSelectionState(selCount);
        Logger.Information("已執行模組全選/取消全選，目標狀態: {State}", targetState);
    }

    public void UpdateSelectionState(int selectedCount)
    {
        CanBatchToggle = selectedCount >= 2;
        CanCheckUpdates = selectedCount >= 1;
        CanDeleteMod = selectedCount >= 1 || SelectedLocalMod is not null;
        DeleteSelectedModCommand.NotifyCanExecuteChanged();
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
        var targets = LocalMods.Where(static m => m.IsSelected).ToList();
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
    public void CopyModInfo(LocalModRowItem? item)
    {
        var target = item ?? SelectedLocalMod;
        if (target is null)
        {
            return;
        }

        var lines = new List<string>();
        if (!string.IsNullOrWhiteSpace(target.Name))
        {
            lines.Add($"模組名稱: {target.Name.Trim()}");
        }
        if (!string.IsNullOrWhiteSpace(target.Version) && target.Version != "-")
        {
            lines.Add($"版本: {target.Version.Trim()}");
        }
        lines.Add($"狀態: {(target.IsEnabled ? "啟用" : "停用")}");
        if (!string.IsNullOrWhiteSpace(target.Author) && target.Author != "-")
        {
            lines.Add($"作者: {target.Author.Trim()}");
        }
        if (!string.IsNullOrWhiteSpace(target.LoaderType) && target.LoaderType != "-")
        {
            lines.Add($"載入器: {target.LoaderType.Trim()}");
        }
        if (!string.IsNullOrWhiteSpace(target.FileSize) && target.FileSize != "-")
        {
            lines.Add($"檔案大小: {target.FileSize.Trim()}");
        }
        if (!string.IsNullOrWhiteSpace(target.ModifiedTime) && target.ModifiedTime != "-")
        {
            lines.Add($"修改時間: {target.ModifiedTime.Trim()}");
        }
        if (!string.IsNullOrWhiteSpace(target.Description))
        {
            lines.Add($"描述: {target.Description.Trim()}");
        }

        string text = string.Join(Environment.NewLine, lines);
        try
        {
            _ui.CopyToClipboard(text);
        }
        catch (Exception ex)
        {
            Logger.Warning("複製模組資訊至剪貼簿失敗: {Message}", ex.Message);
        }
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

        Logger.Information("開始檢查已選取模組更新，共 {Count} 個模組（預設優先使用 Modrinth）", targets.Count);

        string loader = server.LoaderType.ToString().ToLowerInvariant();
        string mcVer = server.MinecraftVersion.Value;
        var installedMods = _modManager is not null ? await _modManager.GetModsAsync(server.Path).ConfigureAwait(true) : [];

        IOperationProgress? progressDialog = _ui.ShowModOperationProgress("檢查模組更新中", "正在大量比對檔案雜湊...");

        try
        {
            progressDialog?.UpdateProgress(0, targets.Count, $"正在向 Modrinth 批次查詢 {targets.Count} 個模組雜湊資訊...");

            // 階段 1：收集所有雜湊，以 1 次批量請求反查官方 ProjectId
            var sha512Hashes = targets
                .Where(m => !string.IsNullOrWhiteSpace(m.CurrentHash) && string.Equals(m.HashAlgorithm, "sha512", StringComparison.OrdinalIgnoreCase))
                .Select(m => m.CurrentHash!)
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToList();
            var sha1Hashes = targets
                .Where(m => !string.IsNullOrWhiteSpace(m.CurrentHash) && string.Equals(m.HashAlgorithm, "sha1", StringComparison.OrdinalIgnoreCase))
                .Select(m => m.CurrentHash!)
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToList();

            var projectMapByHash = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            if (sha512Hashes.Count > 0)
            {
                try
                {
                    var lookupResults = await _modrinthClient.LookupVersionsByHashesAsync(sha512Hashes, "sha512").ConfigureAwait(true);
                    foreach (var (hash, result) in lookupResults)
                    {
                        if (!string.IsNullOrWhiteSpace(result?.ProjectId))
                        {
                            projectMapByHash[hash] = result.ProjectId;
                        }
                    }
                }
                catch (Exception ex)
                {
                    Logger.Warning("批次查詢 SHA-512 雜湊失敗: {Error}", ex.Message);
                }
            }
            if (sha1Hashes.Count > 0)
            {
                try
                {
                    var lookupResults = await _modrinthClient.LookupVersionsByHashesAsync(sha1Hashes, "sha1").ConfigureAwait(true);
                    foreach (var (hash, result) in lookupResults)
                    {
                        if (!string.IsNullOrWhiteSpace(result?.ProjectId))
                        {
                            projectMapByHash[hash] = result.ProjectId;
                        }
                    }
                }
                catch (Exception ex)
                {
                    Logger.Warning("批次查詢 SHA-1 雜湊失敗: {Error}", ex.Message);
                }
            }

            // 階段 2：平行查詢相容版本並執行相容性與語意版本比對（MaxDegreeOfParallelism = 4）
            var candidates = new ConcurrentBag<ModUpdateCandidateItem>();
            int completedCount = 0;
            int totalCount = targets.Count;

            progressDialog?.UpdateProgress(0, totalCount, "正在平行查詢相容版本清單...");

            await Parallel.ForEachAsync(targets, new ParallelOptions { MaxDegreeOfParallelism = 4 }, async (mod, token) =>
            {
                try
                {
                    IReadOnlyList<OnlineModVersion> versions = [];

                    // 優先使用批量雜湊反查到的 ProjectId
                    if (!string.IsNullOrWhiteSpace(mod.CurrentHash) && projectMapByHash.TryGetValue(mod.CurrentHash, out string? projectId))
                    {
                        versions = await _modrinthClient.GetProjectVersionsAsync(projectId, loader: loader, minecraftVersion: mcVer, cancellationToken: token).ConfigureAwait(false);
                    }

                    // 雜湊反查未果時，回退至 mod.Id 查詢
                    if (versions.Count == 0 && !string.IsNullOrWhiteSpace(mod.Id))
                    {
                        versions = await _modrinthClient.GetProjectVersionsAsync(mod.Id, loader: loader, minecraftVersion: mcVer, cancellationToken: token).ConfigureAwait(false);
                    }

                    // 最後回退至以模組名稱搜尋
                    if (versions.Count == 0 && !string.IsNullOrWhiteSpace(mod.Name))
                    {
                        var search = await _modrinthClient.SearchModsAsync(mod.Name, loader: loader, minecraftVersion: mcVer, cancellationToken: token).ConfigureAwait(false);
                        var matched = search.FirstOrDefault(p => string.Equals(p.Name, mod.Name, StringComparison.OrdinalIgnoreCase) || string.Equals(p.Slug, mod.Id, StringComparison.OrdinalIgnoreCase));
                        if (matched is not null)
                        {
                            versions = await _modrinthClient.GetProjectVersionsAsync(matched.ProjectId, loader: loader, minecraftVersion: mcVer, cancellationToken: token).ConfigureAwait(false);
                        }
                    }

                    if (versions.Count > 0)
                    {
                        OnlineModVersion? compatibleLatest = null;
                        foreach (var ver in versions)
                        {
                            if (string.IsNullOrWhiteSpace(ver.VersionNumber) ||
                                ver.PrimaryFile is null ||
                                string.IsNullOrWhiteSpace(ver.PrimaryFile.Url))
                            {
                                continue;
                            }

                            // 標準相容性評估：執行相容性與相依性評估，排除硬性不相容與衝突版本
                            var report = _dependencyPlanner.EvaluateCompatibility(ver, mcVer, loader, installedMods);
                            if (!report.HasHardErrors && report.IncompatibleInstalled.Count == 0)
                            {
                                if (compatibleLatest is null || FlexVersion.Compare(ver.VersionNumber, compatibleLatest.VersionNumber) > 0)
                                {
                                    compatibleLatest = ver;
                                }
                            }
                        }

                        if (compatibleLatest is not null)
                        {
                            var primaryFile = compatibleLatest.PrimaryFile!;
                            string? sha512 = null;
                            string? sha1 = null;
                            if (primaryFile.Hashes is not null)
                            {
                                primaryFile.Hashes.TryGetValue("sha512", out sha512);
                                primaryFile.Hashes.TryGetValue("sha1", out sha1);
                            }

                            // 1. 雜湊比對：若本地模組雜湊與線上最新版本之雜湊相符，代表已是同一檔案最新版
                            bool hashMatches = false;
                            if (!string.IsNullOrWhiteSpace(mod.CurrentHash))
                            {
                                if ((sha512 is not null && string.Equals(mod.CurrentHash, sha512, StringComparison.OrdinalIgnoreCase)) ||
                                    (sha1 is not null && string.Equals(mod.CurrentHash, sha1, StringComparison.OrdinalIgnoreCase)))
                                {
                                    hashMatches = true;
                                }
                            }

                            // 2. 語意版本比對：依據 FlexVersion 規格比對，線上最新版本必須大於本地版本
                            int versionComparison = FlexVersion.Compare(compatibleLatest.VersionNumber, mod.Version);

                            // 只有在版本更大且雜湊不同時，才判定為有可用更新，杜絕降級與虛假更新
                            if (!hashMatches && versionComparison > 0)
                            {
                                string? expectedHash = sha512 ?? sha1;
                                string? hashAlgo = sha512 is not null ? "sha512" : (sha1 is not null ? "sha1" : null);

                                candidates.Add(new ModUpdateCandidateItem
                                {
                                    ModName = mod.Name,
                                    CurrentVersion = mod.Version,
                                    NewVersion = compatibleLatest.VersionNumber,
                                    FileName = !string.IsNullOrWhiteSpace(primaryFile.Filename) ? primaryFile.Filename : $"{mod.Name}-{compatibleLatest.VersionNumber}.jar",
                                    DownloadUrl = primaryFile.Url,
                                    ExpectedHash = expectedHash,
                                    HashAlgorithm = hashAlgo,
                                    LocalMod = mod,
                                });
                            }
                        }
                    }
                }
                catch (Exception ex)
                {
                    Logger.Warning("檢查模組「{Name}」更新失敗: {Error}", mod.Name, ex.Message);
                }
                finally
                {
                    int done = Interlocked.Increment(ref completedCount);
                    progressDialog?.UpdateProgress(done, totalCount, $"正在檢查 ({done}/{totalCount}): {mod.Name}...");
                }
            }).ConfigureAwait(true);

            progressDialog?.Close();
            progressDialog = null;

            var sortedCandidates = candidates.OrderBy(c => c.ModName).ToList();

            if (sortedCandidates.Count > 0)
            {
                if (_ui.ShowModUpdates(sortedCandidates) is { } toUpdate)
                {
                    if (toUpdate.Count > 0)
                    {
                        await PerformModUpdatesAsync(server.Path, toUpdate).ConfigureAwait(true);
                        await LoadLocalModsAsync().ConfigureAwait(true);
                        _notificationSink?.Invoke($"已成功更新 {toUpdate.Count} 個模組！", false);
                    }
                }
            }
            else
            {
                _notificationSink?.Invoke($"檢查完成，選取的 {targets.Count} 個模組皆為相容最新版本", false);
            }
        }
        finally
        {
            progressDialog?.Close();
        }
    }

    private async Task PerformModUpdatesAsync(string serverPath, IReadOnlyList<ModUpdateCandidateItem> items, CancellationToken cancellationToken = default)
    {
        if (_modManager is null || items.Count == 0)
        {
            return;
        }

        var unofficial = items.Where(static i => !ModFileInstaller.IsOfficialModrinthSource(i.DownloadUrl)).ToList();
        if (unofficial.Count > 0)
        {
            string msg = "下列模組更新下載來源非官方 Modrinth CDN：\n" +
                         string.Join("\n", unofficial.Select(static u => $"• {u.ModName}: {u.DownloadUrl}")) +
                         "\n\n非官方來源可能存在安全風險，是否仍要繼續下載並更新？";
            if (!_ui.Confirm(msg, "非官方下載來源警告", UiMessageLevel.Warning))
            {
                return;
            }
        }

        IOperationProgress? updateProgressDialog = _ui.ShowModOperationProgress("正在更新模組", "準備下載新版本...");

        try
        {
            IModManager modManager = _modManager;
            int completedCount = 0;
            int totalCount = items.Count;
            updateProgressDialog?.UpdateProgress(0, totalCount, "已啟動模組並行下載更新佇列...");

            await Parallel.ForEachAsync(items, new ParallelOptions
            {
                MaxDegreeOfParallelism = 3,
                CancellationToken = cancellationToken
            }, async (item, token) =>
            {
                try
                {
                    var installResult = await modManager.InstallOnlineModAsync(
                        serverPath,
                        item.DownloadUrl,
                        item.FileName,
                        item.ExpectedHash,
                        item.HashAlgorithm,
                        cancellationToken: token).ConfigureAwait(false);

                    if (installResult?.Completed == true)
                    {
                        if (!item.LocalMod.IsEnabled)
                        {
                            await modManager.SetModStateAsync(serverPath, item.FileName, false, token).ConfigureAwait(false);
                        }

                        if (!string.Equals(item.LocalMod.FileName, item.FileName, StringComparison.OrdinalIgnoreCase))
                        {
                            string oldTarget = !string.IsNullOrEmpty(item.LocalMod.FileName) ? item.LocalMod.FileName : item.LocalMod.Id;
                            await modManager.DeleteModsAsync(serverPath, [oldTarget], cancellationToken: token).ConfigureAwait(false);
                        }

                        Logger.Information("成功更新模組「{Name}」至版本 {Version}", item.ModName, item.NewVersion);
                    }
                    else
                    {
                        Logger.Warning("更新模組「{Name}」失敗: {Error}", item.ModName, installResult?.Message ?? "未知錯誤");
                    }
                }
                catch (Exception ex) when (ex is not OperationCanceledException)
                {
                    Logger.Error(ex, "更新模組「{Name}」異常: {Message}", item.ModName, ex.Message);
                }
                finally
                {
                    int done = Interlocked.Increment(ref completedCount);
                    updateProgressDialog?.UpdateProgress(done, totalCount, $"正在更新模組 ({done}/{totalCount}): {item.ModName}...");
                }
            }).ConfigureAwait(true);
        }
        finally
        {
            updateProgressDialog?.Close();
            ModFileInstaller.CleanupStagingDirectory(Path.Combine(serverPath, "mods"));
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
        SafeFileSystem.CreateDirectory(modsDir);

        Logger.Information("開啟模組資料夾: {Path}", modsDir);
        if (_launcher is not null && !_launcher.OpenFolder(modsDir, isTrusted: true))
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

        string filePath = await Task.Run(() => ResolveModFilePath(server.Path, targetMod.FileName)).ConfigureAwait(true);

        if (_launcher is not null && !_launcher.ShowInFolder(filePath, isTrusted: true))
        {
            _notificationSink?.Invoke($"無法在資料夾中顯示：{filePath}", true);
        }
    }

    private static ModListExportRow ToExportRow(LocalModRowItem m) => new(
        Id: m.Id,
        Name: m.Name,
        Version: m.Version,
        FileName: m.FileName,
        FileSize: m.FileSize,
        Author: m.Author,
        LoaderType: m.LoaderType,
        MinecraftVersion: m.MinecraftVersion,
        ModifiedTime: m.ModifiedTime,
        Description: m.Description,
        IsEnabled: m.IsEnabled);

    private static string ResolveModFilePath(string serverPath, string fileName)
    {
        string filePath = Path.Combine(serverPath, "mods", fileName);
        if (SafeFileSystem.FileExists(filePath))
        {
            return filePath;
        }

        string disabledPath = filePath + ".disabled";
        return SafeFileSystem.FileExists(disabledPath) ? disabledPath : Path.Combine(serverPath, "mods");
    }

    private static void DeleteModFileIfExists(string serverPath, string path)
    {
        if (SafeFileSystem.FileExists(path))
        {
            SafeFileSystem.DeleteWithin(serverPath, path);
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

        if (_ui.PickFiles("選取要匯入的 Minecraft 模組檔案 (.jar)", "Minecraft 模組 (*.jar)|*.jar|所有檔案 (*.*)|*.*", multiselect: true) is { } files)
        {
            int count = 0;
            foreach (string file in files)
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

    [RelayCommand(CanExecute = nameof(CanDeleteMod))]
    public async Task DeleteSelectedModAsync()
    {
        var targets = LocalMods.Where(static m => m.IsSelected).ToList();
        if (targets.Count == 0 && SelectedLocalMod is not null)
        {
            targets = [SelectedLocalMod];
        }

        if (targets.Count == 0)
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

        string confirmMsg = targets.Count == 1
            ? $"確定要刪除模組「{targets[0].Name}」嗎？\n此操作將永久刪除對應檔案，無法復原。"
            : $"確定要刪除選取的 {targets.Count} 個模組嗎？\n此操作將永久刪除對應檔案，無法復原。";

        if (!_ui.Confirm(confirmMsg, "確認刪除模組", UiMessageLevel.Warning))
        {
            return;
        }

        var idsToDelete = targets
            .Select(static m => !string.IsNullOrEmpty(m.FileName) ? m.FileName : m.Id)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        var result = await _modManager.DeleteModsAsync(server.Path, idsToDelete);
        if (result.Completed || result.Partial)
        {
            foreach (var mod in targets)
            {
                _allLocalMods.Remove(mod);
                LocalMods.Remove(mod);
            }

            SelectedLocalMod = null;
            UpdateSelectionState(0);

            string successMsg = targets.Count == 1
                ? $"已成功刪除模組「{targets[0].Name}」"
                : $"已成功刪除 {targets.Count} 個模組";
            Logger.Information("刪除模組成功，共 {Count} 個模組", targets.Count);
            _notificationSink?.Invoke(successMsg, false);
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

        var rows = _allLocalMods.Select(ToExportRow).ToList();
        _ui.ShowExportModList(SelectedServer, rows, _modListExporter, _launcher);
    }


    [RelayCommand]
    public async Task SearchOnlineModsAsync()
    {
        if (SelectedPlatform == "CurseForge")
        {
            _allOnlineMods.Clear();
            OnlineMods.Clear();
            SelectedOnlineMod = null;
            OnlineResultHint = "CurseForge 模組搜尋即將推出，敬請期待";
            return;
        }

        if (_modrinthClient is null)
        {
            _notificationSink?.Invoke("Modrinth 用戶端未初始化", true);
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

            string query = OnlineSearchText?.Trim() ?? string.Empty;
            string sortIndex = SelectedOnlineSort switch
            {
                "下載量" => "downloads",
                "最新發布" => "newest",
                "最近更新" => "updated",
                _ => "relevance"
            };
            Logger.Information("搜尋線上模組: 平台: {Platform}, 關鍵字: {Query}, 載入器: {Loader}, MC版本: {Version}, 排序: {SortIndex}", SelectedPlatform, query, loader, mcVersion, sortIndex);
            var results = await _modrinthClient.SearchModsAsync(query, loader: loader, minecraftVersion: mcVersion, index: sortIndex);

            foreach (var item in results)
            {
                _allOnlineMods.Add(new OnlineModRowItem
                {
                    Id = item.ProjectId,
                    Slug = item.Slug,
                    Title = item.Name,
                    Author = item.Author,
                    Description = item.Description,
                    Downloads = item.Downloads.ToString("N0", CultureInfo.InvariantCulture),
                    DownloadCountRaw = item.Downloads,
                    LatestVersion = item.LatestVersion,
                    ServerSide = item.ServerSide,
                    ClientSide = item.ClientSide
                });
            }

            ApplyOnlineSort();

            if (OnlineMods.Count > 0)
            {
                SelectedOnlineMod = OnlineMods[0];
                Logger.Information("線上搜尋完成，找到 {Count} 個模組", OnlineMods.Count);
                OnlineResultHint = string.IsNullOrWhiteSpace(query)
                    ? $"已為您預載 {OnlineMods.Count} 個伺服器相容推薦模組"
                    : $"在 {SelectedPlatform} 找到 {OnlineMods.Count} 個伺服器相容模組";
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
        IEnumerable<OnlineModRowItem> sorted = SelectedOnlineSort switch
        {
            "下載量" => _allOnlineMods.OrderByDescending(static m => m.DownloadCountRaw),
            "名稱" => _allOnlineMods.OrderBy(static m => m.Title, StringComparer.OrdinalIgnoreCase),
            _ => _allOnlineMods
        };

        OnlineMods.ReplaceAll(sorted);
    }

    /// <summary>
    /// 取得所有相容版本並彈出版本選擇對話方塊。
    /// </summary>
    [RelayCommand]
    public async Task PickOnlineModVersionAsync(OnlineModRowItem? mod)
    {
        mod ??= SelectedOnlineMod;
        if (mod is null || _modrinthClient is null)
        {
            return;
        }

        // 偵測伺服器端環境相容性，防範純用戶端模組造成伺服器當機
        if (string.Equals(mod.ServerSide, "unsupported", StringComparison.OrdinalIgnoreCase))
        {
            bool proceed = _ui.Confirm(
                $"模組「{mod.Title}」在 Modrinth 標記為純用戶端模組 (server_side: unsupported)，在伺服器端執行可能引發當機！\n\n是否仍要強行挑選版本並加入安裝清單？",
                "伺服器端環境不相容警告",
                UiMessageLevel.Warning);
            if (!proceed)
            {
                return;
            }
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
        if (_ui.ShowModVersionPicker(pickerVm) != true || pickerVm.QueuedVersion is null)
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

        if (chosen.Dependencies.Count > 0 && _serverManager is not null && HasSelectedServer && _modManager is not null && _modrinthClient is not null)
        {
            try
            {
                var server = await _serverManager.GetServerAsync(SelectedServer);
                if (server is not null)
                {
                    var installed = await _modManager.GetModsAsync(server.Path);
                    var rawDeps = chosen.Dependencies
                        .Select(d => new OnlineModDependency(d, ModDependencyType.Required))
                        .ToList();

                    var missingDeps = await _dependencyPlanner.ResolveDependenciesRecursivelyAsync(
                        _modrinthClient,
                        rawDeps,
                        server.MinecraftVersion.Value,
                        server.LoaderType.ToString(),
                        installed);

                    var toAdd = missingDeps
                        .Where(plan => plan.TargetVersion.PrimaryFile is not null && !InstallQueue.Any(q => string.Equals(q.FileName, plan.TargetVersion.PrimaryFile.Filename, StringComparison.OrdinalIgnoreCase)))
                        .ToList();

                    if (toAdd.Count > 0)
                    {
                        var installItems = toAdd.Where(p => p.Action == ModInstallAction.Install).ToList();
                        var updateItems = toAdd.Where(p => p.Action == ModInstallAction.Update).ToList();

                        var sb = new System.Text.StringBuilder();
                        sb.AppendLine(CultureInfo.InvariantCulture, $"模組「{mod.Title}」偵測到 {toAdd.Count} 個必要相依模組規劃：");

                        if (installItems.Count > 0)
                        {
                            sb.AppendLine("\n【全新安裝】");
                            foreach (var item in installItems)
                            {
                                sb.AppendLine(CultureInfo.InvariantCulture, $"• {item.TargetVersion.DisplayName} ({item.TargetVersion.PrimaryFile?.Filename})");
                            }
                        }

                        if (updateItems.Count > 0)
                        {
                            sb.AppendLine("\n【更新升級】");
                            foreach (var item in updateItems)
                            {
                                sb.AppendLine(CultureInfo.InvariantCulture, $"• {item.TargetVersion.DisplayName} ({item.ExistingLocalMod?.Version} ➔ {item.TargetVersion.VersionNumber})");
                            }
                        }

                        sb.AppendLine("\n是否將這些相依模組一併加入安裝清單？");

                        bool confirm = _ui.Confirm(sb.ToString(), "發現必要相依模組");

                        if (confirm)
                        {
                            foreach (var plan in toAdd)
                            {
                                var depVer = plan.TargetVersion;
                                var pf = depVer.PrimaryFile!;
                                string? hash = ExtractHash(pf, out string algo);
                                string projId = !string.IsNullOrWhiteSpace(depVer.ProjectId) ? depVer.ProjectId : depVer.VersionId;
                                InstallQueue.Add(new ModInstallQueueItem
                                {
                                    ProjectId = projId,
                                    Title = depVer.DisplayName,
                                    VersionNumber = depVer.VersionNumber,
                                    CurrentVersion = plan.ExistingLocalMod?.Version,
                                    FileName = pf.Filename,
                                    OldFileName = plan.ExistingLocalMod?.Filename,
                                    DownloadUrl = pf.Url,
                                    ExpectedHash = hash,
                                    HashAlgorithm = algo,
                                    Dependencies = [.. depVer.Dependencies.Select(d => d.ProjectId ?? string.Empty).Where(id => id.Length > 0)],
                                    Action = plan.Action,
                                    Reason = plan.Reason
                                });
                            }
                            _notificationSink?.Invoke($"已將 {toAdd.Count} 個相依模組加入安裝清單", false);
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Logger.Warning("檢查相依模組時發生異常: {Message}", ex.Message);
            }
        }

        UpdateInstallQueueHint();

        if (pickerVm.InstallImmediately)
        {
            await InstallQueuedModsAsync();
        }
    }

    /// <summary>
    /// 完成相依性評估後統一批次下載安裝。
    /// </summary>
    [RelayCommand]
    public async Task InstallQueuedModsAsync(CancellationToken cancellationToken = default)
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

        var server = await _serverManager.GetServerAsync(SelectedServer, cancellationToken);
        if (server is null)
        {
            return;
        }

        // 相依性評估：排除佇列中與伺服器本機已安裝的模組
        var queuedProjects = InstallQueue
            .Select(i => i.ProjectId)
            .Where(id => !string.IsNullOrWhiteSpace(id))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);

        var installedMods = await _modManager.GetModsAsync(server.Path, cancellationToken: cancellationToken).ConfigureAwait(true);
        var installedIdentifiers = installedMods
            .Where(m => !string.IsNullOrWhiteSpace(m.Id))
            .Select(m => m.Id.Trim())
            .ToHashSet(StringComparer.OrdinalIgnoreCase);

        var missingDependencies = InstallQueue
            .SelectMany(i => i.Dependencies)
            .Where(id => !string.IsNullOrWhiteSpace(id) && !queuedProjects.Contains(id) && !installedIdentifiers.Contains(id))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        if (missingDependencies.Count > 0)
        {
            Logger.Warning("安裝清單存在未涵蓋的相依模組，共 {Count} 項", missingDependencies.Count);
            _notificationSink?.Invoke($"注意：安裝清單有 {missingDependencies.Count} 個未納入的相依模組，安裝後可能無法正常載入", true);
        }

        IsInstallingMod = true;
        var pending = InstallQueue.ToList();
        var pendingTargetFileNames = pending
            .Select(static item => Path.GetFileName(item.FileName))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);

        var unofficial = pending.Where(i => !ModFileInstaller.IsOfficialModrinthSource(i.DownloadUrl)).ToList();
        if (unofficial.Count > 0)
        {
            string msg = "下列待安裝模組下載來源非官方 Modrinth CDN：\n" +
                         string.Join("\n", unofficial.Select(u => $"• {u.Title}: {u.DownloadUrl}")) +
                         "\n\n非官方來源可能存在安全風險，是否仍要繼續下載並安裝？";
            if (!_ui.Confirm(msg, "非官方下載來源警告", UiMessageLevel.Warning))
            {
                IsInstallingMod = false;
                return;
            }
        }

        IOperationProgress? installProgressDialog = _ui.ShowModOperationProgress("正在安裝模組", "準備下載模組檔案...");

        try
        {
            IModManager modManager = _modManager;
            int completedCount = 0;
            int totalCount = pending.Count;
            installProgressDialog?.UpdateProgress(0, totalCount, "已排入模組並行下載佇列...");

            var succeededItems = new ConcurrentBag<ModInstallQueueItem>();

            await Parallel.ForEachAsync(pending, new ParallelOptions
            {
                MaxDegreeOfParallelism = 3,
                CancellationToken = cancellationToken
            }, async (item, token) =>
            {
                try
                {
                    var result = await modManager.InstallOnlineModAsync(
                        server.Path,
                        item.DownloadUrl,
                        item.FileName,
                        expectedHash: item.ExpectedHash,
                        hashAlgorithm: item.HashAlgorithm,
                        cancellationToken: token).ConfigureAwait(false);

                    if (result?.Completed != true)
                    {
                        string message = result?.Message ?? (token.IsCancellationRequested ? "已取消安裝" : "下載工作未回傳結果");
                        Logger.Warning("模組「{Title}」安裝失敗: {Message}", item.Title, message);
                        _notificationSink?.Invoke($"模組「{item.Title}」安裝失敗：{message}", true);
                        return;
                    }

                    if (item.Action == ModInstallAction.Update && !string.IsNullOrWhiteSpace(item.OldFileName) &&
                        !string.Equals(item.OldFileName, item.FileName, StringComparison.OrdinalIgnoreCase) &&
                        !pendingTargetFileNames.Contains(Path.GetFileName(item.OldFileName)))
                    {
                        try
                        {
                            string modsDir = Path.Combine(server.Path, "mods");
                            string oldPath = Path.Combine(modsDir, item.OldFileName);
                            string oldDisabled = oldPath + ".disabled";
                            DeleteModFileIfExists(server.Path, oldPath);
                            DeleteModFileIfExists(server.Path, oldDisabled);
                        }
                        catch (Exception ex)
                        {
                            Logger.Warning("刪除舊版本模組檔案「{Old}」失敗: {Message}", item.OldFileName, ex.Message);
                        }
                    }

                    succeededItems.Add(item);
                }
                catch (Exception ex) when (ex is not OperationCanceledException)
                {
                    Logger.Error(ex, "安裝模組「{Title}」異常: {Message}", item.Title, ex.Message);
                    _notificationSink?.Invoke($"安裝「{item.Title}」異常：{ex.Message}", true);
                }
                finally
                {
                    int done = Interlocked.Increment(ref completedCount);
                    installProgressDialog?.UpdateProgress(done, totalCount, $"正在安裝模組 ({done}/{totalCount}): {item.Title}...");
                }
            }).ConfigureAwait(true);

            foreach (var item in succeededItems)
            {
                InstallQueue.Remove(item);
            }

            int success = succeededItems.Count;
            Logger.Information("批次安裝完成，成功 {Success} / {Total}", success, pending.Count);
            await LoadLocalModsAsync().ConfigureAwait(true);

            if (pending.Count > 0)
            {
                int failed = pending.Count - success;
                string summaryMsg = $"已成功安裝 {success} 個模組！" + (failed > 0 ? $"\n其中 {failed} 個模組安裝失敗，請檢查網路連線或記錄檔。" : string.Empty);
                _notificationSink?.Invoke(summaryMsg, failed > 0);
            }
        }
        finally
        {
            installProgressDialog?.Close();
            IsInstallingMod = false;
            UpdateInstallQueueHint();
            if (!string.IsNullOrWhiteSpace(server?.Path))
            {
                ModFileInstaller.CleanupStagingDirectory(Path.Combine(server.Path, "mods"));
            }
        }
    }

    /// <summary>
    /// 檢視待安裝佇列清單視窗
    /// </summary>
    [RelayCommand]
    public void ViewInstallQueue()
    {
        bool? confirmed = _ui.ShowModInstallQueue(InstallQueue);
        UpdateInstallQueueHint();

        if (confirmed == true && InstallQueue.Count > 0)
        {
            _ = RunSafeAsync(() => InstallQueuedModsAsync(), "安裝佇列模組", Logger);
        }
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
    /// 於瀏覽器開啟選取模組的線上專案頁面。
    /// </summary>
    [RelayCommand]
    public void OpenModPlatformPage()
    {
        if (SelectedOnlineMod is null)
        {
            _notificationSink?.Invoke("請先選取要檢視的線上模組", true);
            return;
        }

        string url;
        if (string.Equals(SelectedPlatform, "CurseForge", StringComparison.OrdinalIgnoreCase))
        {
            string slug = !string.IsNullOrWhiteSpace(SelectedOnlineMod.Slug) ? SelectedOnlineMod.Slug : SelectedOnlineMod.Id;
            url = $"https://www.curseforge.com/minecraft/mc-mods/{slug}";
        }
        else
        {
            url = $"https://modrinth.com/mod/{SelectedOnlineMod.Id}";
        }

        if (_launcher is not null && !_launcher.OpenUrl(url, isTrusted: true))
        {
            _notificationSink?.Invoke($"無法開啟連結：{url}", true);
        }
    }

    private void UpdateInstallQueueHint()
    {
        if (InstallQueue.Count == 0)
        {
            InstallQueueHint = "安裝佇列為空";
            return;
        }

        int installs = InstallQueue.Count(static i => i.Action == ModInstallAction.Install);
        int updates = InstallQueue.Count(static i => i.Action == ModInstallAction.Update);

        InstallQueueHint = updates > 0
            ? $"安裝清單：{installs} 個新增，{updates} 個更新"
            : $"安裝清單：{installs} 個項目待安裝";
    }

    private static string? ExtractHash(ModFile? file, out string algorithm)
    {
        algorithm = "sha512";
        if (file?.Hashes is null)
        {
            return null;
        }

        if (file.Hashes.TryGetValue("sha512", out string? sha512) && !string.IsNullOrWhiteSpace(sha512))
        {
            algorithm = "sha512";
            return sha512;
        }

        if (file.Hashes.TryGetValue("sha1", out string? sha1) && !string.IsNullOrWhiteSpace(sha1))
        {
            algorithm = "sha1";
            return sha1;
        }

        return null;
    }
}

