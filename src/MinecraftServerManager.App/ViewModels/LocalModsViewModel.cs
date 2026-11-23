using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>本地模組清單項目模型</summary>
public sealed partial class LocalModRowItem : ObservableObject
{
    public string Id { get; init; } = string.Empty;

    public string Name { get; init; } = string.Empty;

    public string Version { get; init; } = string.Empty;

    [ObservableProperty]
    public partial string FileName { get; set; } = string.Empty;

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

    public string SourcePlatform { get; init; } = "-";
}

/// <summary>模組頁：本地模組清單載入、篩選、啟用／停用、刪除、匯入與匯出</summary>
public sealed partial class LocalModsViewModel : ViewModelBase, IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(LocalModsViewModel));
    private static readonly string[] LocalFilterOptionsValues = ["全部", "已啟用", "已停用"];

    private readonly IUiService _ui;
    private readonly ModsContext _context;
    private readonly IModManager _modManager;
    private readonly IModFileService _modFileService;
    private readonly IModListExporter _modListExporter;
    private readonly IExternalLauncher _launcher;
    private readonly List<LocalModRowItem> _allLocalMods = [];
    private readonly SerialCancellation _loadCancellation = new();
    private readonly HashSet<string> _togglingMods = new(StringComparer.OrdinalIgnoreCase);
    private int _loadGeneration;

    public LocalModsViewModel(
        ModsContext context,
        IModFileService modFileService,
        IModListExporter modListExporter,
        IUiService uiService,
        IModManager modManager,
        IExternalLauncher launcher)
    {
        ArgumentNullException.ThrowIfNull(context);
        ArgumentNullException.ThrowIfNull(modFileService);
        ArgumentNullException.ThrowIfNull(modListExporter);
        ArgumentNullException.ThrowIfNull(uiService);
        ArgumentNullException.ThrowIfNull(modManager);
        ArgumentNullException.ThrowIfNull(launcher);

        _ui = uiService;
        _context = context;
        _modFileService = modFileService;
        _modListExporter = modListExporter;
        _modManager = modManager;
        _launcher = launcher;
        _context.RegisterModsChangedHandler(LoadLocalModsAsync);
    }

    [ObservableProperty]
    public partial string LocalSearchText { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string SelectedLocalFilter { get; set; } = "全部";

    [ObservableProperty]
    public partial LocalModRowItem? SelectedLocalMod { get; set; }

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(BatchToggleCommand))]
    public partial bool CanBatchToggle { get; private set; }

    [ObservableProperty]
    public partial bool CanCheckUpdates { get; private set; }

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(DeleteSelectedModCommand))]
    public partial bool CanDeleteMod { get; private set; }

    /// <summary>本地模組載入中（供空狀態判斷）</summary>
    [ObservableProperty]
    public partial bool IsLoading { get; private set; }

    public BulkObservableCollection<LocalModRowItem> LocalMods { get; } = [];

    public IReadOnlyList<string> LocalFilterOptions { get; } = LocalFilterOptionsValues;

    partial void OnLocalSearchTextChanged(string value) => ApplyLocalFilter();

    partial void OnSelectedLocalFilterChanged(string value) => ApplyLocalFilter();

    partial void OnSelectedLocalModChanged(LocalModRowItem? value) =>
        CanDeleteMod = value is not null || LocalMods.Any(static m => m.IsSelected);

    /// <summary>取得目前選取之模組（供更新檢查與批次切換使用）</summary>
    public IReadOnlyList<LocalModRowItem> GetCheckedMods() => LocalMods.Where(static m => m.IsSelected).ToList();

    [RelayCommand]
    public async Task RefreshLocalModsAsync()
    {
        await LoadLocalModsAsync();
        Logger.Information("已重新整理本地模組清單（伺服器：{Server}）", _context.Server?.Name.Value);
    }

    /// <summary>依目前伺服器快照重新載入本地模組</summary>
    public async Task LoadLocalModsAsync()
    {
        CancellationToken token = _loadCancellation.Next();
        int generation = ++_loadGeneration;
        IsLoading = true;
        try
        {
            _allLocalMods.Clear();
            LocalMods.Clear();
            SelectedLocalMod = null;
            UpdateSelectionState(0);

            if (_context.Server is not { } server)
            {
                return;
            }

            var mods = await _modManager.GetModsAsync(server.Path, cancellationToken: token);
            token.ThrowIfCancellationRequested();
            if (generation != _loadGeneration)
            {
                return;
            }

            // 以檔名去重，杜絕重複列項
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var mod in mods)
            {
                string dedupeKey = !string.IsNullOrWhiteSpace(mod.FileName) ? mod.FileName : mod.Id;
                if (seen.Add(dedupeKey))
                {
                    _allLocalMods.Add(LocalModRowMapper.ToRowItem(mod));
                }
            }

            Logger.Information("載入本地模組成功，共 {Count} 個模組（伺服器：{Server}）", _allLocalMods.Count, server.Name.Value);
            ApplyLocalFilter();
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested)
        {
            Logger.Information("載入本地模組已被較新的掃描要求取代");
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "載入本地模組失敗");
            _ui.Notify($"載入模組失敗：{ex.Message}", NotificationType.Error);
        }
        finally
        {
            if (generation == _loadGeneration)
            {
                IsLoading = false;
            }
        }
    }

    /// <summary>依搜尋文字與啟用狀態篩選本地模組</summary>
    public void ApplyLocalFilter()
    {
        string query = LocalSearchText.Trim();
        var filtered = new List<LocalModRowItem>(_allLocalMods.Count);

        foreach (var mod in _allLocalMods)
        {
            if ((SelectedLocalFilter == "已啟用" && !mod.IsEnabled) || (SelectedLocalFilter == "已停用" && mod.IsEnabled))
            {
                continue;
            }

            if (!string.IsNullOrEmpty(query) &&
                !mod.Name.Contains(query, StringComparison.OrdinalIgnoreCase) &&
                !mod.FileName.Contains(query, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            filtered.Add(mod);
        }

        // 清單重設後 ListView 的選取會一併清除，須同步清除各列旗標
        foreach (var mod in _allLocalMods)
        {
            mod.IsSelected = false;
        }

        LocalMods.ReplaceAll(filtered);
        UpdateSelectionState(0);
    }

    /// <summary>以清單目前的選取項目重建各列選取旗標並更新按鈕狀態（清單選取為唯一事實來源）</summary>
    public void SetSelectedMods(IEnumerable<LocalModRowItem> selected)
    {
        ArgumentNullException.ThrowIfNull(selected);
        HashSet<LocalModRowItem> selectedSet = [.. selected];
        foreach (var mod in LocalMods)
        {
            mod.IsSelected = selectedSet.Contains(mod);
        }

        UpdateSelectionState(selectedSet.Count);
    }

    public void UpdateSelectionState(int selectedCount)
    {
        CanBatchToggle = selectedCount >= 2;
        CanCheckUpdates = selectedCount >= 1;
        CanDeleteMod = selectedCount >= 1 || SelectedLocalMod is not null;
    }

    [RelayCommand]
    public async Task ToggleModAsync(LocalModRowItem? mod)
    {
        if (mod is null || !_context.TryRequireServer(_ui, out var server))
        {
            return;
        }

        string lockKey = !string.IsNullOrWhiteSpace(mod.FileName) ? mod.FileName : mod.Id;
        if (!_togglingMods.Add(lockKey))
        {
            return;
        }

        try
        {
            if (await ToggleCoreAsync(server.Path, mod) is { } error)
            {
                _ui.Notify($"切換模組「{mod.Name}」狀態失敗：{error}", NotificationType.Error);
            }
        }
        finally
        {
            _togglingMods.Remove(lockKey);
        }
    }

    /// <summary>切換單一模組啟用狀態並同步列項檔名；成功回傳 null，失敗回傳原因</summary>
    private async Task<string?> ToggleCoreAsync(string serverPath, LocalModRowItem mod)
    {
        bool newState = !mod.IsEnabled;
        try
        {
            // 優先以實際檔名定位，避免以模組 ID 前綴比對到其他模組
            string target = !string.IsNullOrEmpty(mod.FileName) ? mod.FileName : mod.Id;
            var result = await _modManager.SetModStateAsync(serverPath, target, newState);
            if (!result.Completed)
            {
                Logger.Warning("切換模組「{Name}」狀態失敗：{Message}", mod.Name, result.Message);
                return result.Message;
            }

            mod.IsEnabled = newState;
            if (!string.IsNullOrEmpty(mod.FileName))
            {
                var stem = ModHelpers.ModFilenameStem(mod.FileName.AsSpan());
                mod.FileName = newState ? ModHelpers.ToEnabledModFileName(stem) : ModHelpers.ToDisabledModFileName(stem);
            }

            Logger.Information("已切換模組「{Name}」狀態為：{State}", mod.Name, newState ? "啟用" : "停用");
            return null;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "切換模組「{Name}」狀態失敗", mod.Name);
            return ex.Message;
        }
    }

    [RelayCommand(CanExecute = nameof(CanBatchToggle))]
    public async Task BatchToggleAsync()
    {
        var targets = LocalMods.Where(static m => m.IsSelected).ToList();
        if (targets.Count < 2)
        {
            _ui.Notify("批次切換功能需選取至少 2 個模組", NotificationType.Warning);
            return;
        }

        if (_context.Server is not { } server)
        {
            return;
        }

        List<string> failures = [];
        foreach (var mod in targets)
        {
            if (await ToggleCoreAsync(server.Path, mod) is { } error)
            {
                failures.Add($"{mod.Name}：{error}");
            }
        }

        Logger.Information("批次切換模組狀態完成，成功：{Count} / {Total}", targets.Count - failures.Count, targets.Count);
        ApplyLocalFilter();
        if (failures.Count > 0)
        {
            ModBatchOperations.NotifySummary(_ui, "切換", targets.Count - failures.Count, failures);
        }
    }

    [RelayCommand]
    public void CopyModInfo(LocalModRowItem? item)
    {
        var target = item ?? SelectedLocalMod;
        if (target is null)
        {
            return;
        }

        try
        {
            _ui.CopyToClipboard(LocalModRowMapper.BuildModInfoText(target));
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "複製模組資訊至剪貼簿失敗");
        }
    }

    [RelayCommand]
    public async Task OpenModsFolderAsync()
    {
        if (_context.Server is not { } server)
        {
            _ui.Notify("請先選擇伺服器", NotificationType.Warning);
            return;
        }

        string modsDir;
        try
        {
            modsDir = await _modFileService.EnsureModsDirectoryAsync(server.Path);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "建立模組資料夾失敗");
            _ui.Notify($"無法建立模組資料夾：{ex.Message}", NotificationType.Error);
            return;
        }

        Logger.Information("開啟模組資料夾：{Path}", modsDir);
        _ui.OpenFolderOrWarn(_launcher, modsDir);
    }

    [RelayCommand]
    public async Task ShowInFolderAsync(LocalModRowItem? mod)
    {
        var targetMod = mod ?? SelectedLocalMod;
        if (targetMod is null || _context.Server is not { } server)
        {
            return;
        }

        string filePath;
        try
        {
            filePath = await _modFileService.ResolveModFilePathAsync(server.Path, targetMod.FileName);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "解析模組「{File}」路徑失敗", targetMod.FileName);
            _ui.Notify($"無法定位模組檔案：{ex.Message}", NotificationType.Warning);
            return;
        }

        _ui.ShowInFolderOrWarn(_launcher, filePath);
    }

    [RelayCommand]
    public async Task ImportModsAsync()
    {
        if (_context.Server is not { } server)
        {
            _ui.Notify("請先選擇伺服器以匯入模組", NotificationType.Warning);
            return;
        }

        if (await _ui.PickFilesAsync("選取要匯入的 Minecraft 模組檔案（.jar）", FileTypeChoice.Jar, multiselect: true) is not { Count: > 0 } files)
        {
            return;
        }

        List<string> failures = [];
        foreach (string file in files)
        {
            string fileName = Path.GetFileName(file);
            try
            {
                var result = await _modManager.ImportModAsync(server.Path, file);
                if (!result.Completed)
                {
                    failures.Add($"{fileName}：{result.Message}");
                }
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Error(ex, "匯入模組「{File}」失敗", fileName);
                failures.Add($"{fileName}：{ex.Message}");
            }
        }

        int count = files.Count - failures.Count;
        Logger.Information("已成功匯入 {Count} 個模組檔案至「{Server}」", count, server.Name.Value);
        await LoadLocalModsAsync();
        ModBatchOperations.NotifySummary(_ui, "匯入", count, failures);
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
            _ui.Notify("請先選取要刪除的模組", NotificationType.Warning);
            return;
        }

        if (_context.Server is not { } server)
        {
            return;
        }

        string confirmMsg = targets.Count == 1
            ? $"確定要刪除模組「{targets[0].Name}」嗎？\n此操作將永久刪除對應檔案，無法復原。"
            : $"確定要刪除選取的 {targets.Count} 個模組嗎？\n此操作將永久刪除對應檔案，無法復原。";

        if (!await _ui.ConfirmAsync(confirmMsg, "確認刪除模組", UiMessageLevel.Warning))
        {
            return;
        }

        var idsToDelete = targets
            .Select(static m => !string.IsNullOrEmpty(m.FileName) ? m.FileName : m.Id)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        try
        {
            var result = await _modManager.DeleteModsAsync(server.Path, idsToDelete);
            if (result.Completed)
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
                _ui.Notify(successMsg, NotificationType.Success);
            }
            else
            {
                Logger.Warning("刪除模組失敗：{Message}", result.Message);
                _ui.Notify($"刪除失敗：{result.Message}", NotificationType.Error);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "刪除模組失敗");
            _ui.Notify($"刪除模組失敗：{ex.Message}", NotificationType.Error);
        }
    }

    [RelayCommand]
    public async Task ExportModListAsync()
    {
        if (_context.Server is not { } server || _allLocalMods.Count == 0)
        {
            _ui.Notify("目前伺服器沒有可匯出的本地模組", NotificationType.Warning);
            return;
        }

        var rows = _allLocalMods.Select(LocalModRowMapper.ToExportRow).ToList();
        var vm = new ExportModListViewModel(server.Name.Value, rows, _modListExporter, _launcher, _ui);
        await vm.RunAsync();
    }

    public void Dispose() => _loadCancellation.Dispose();
}
