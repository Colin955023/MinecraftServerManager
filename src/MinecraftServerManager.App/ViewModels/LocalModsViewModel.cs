using System.Globalization;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Utilities;
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

    public string FileName { get; set; } = string.Empty;

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
/// 模組頁：本地模組清單載入、篩選、啟用／停用、刪除、匯入與匯出
/// </summary>
public sealed partial class LocalModsViewModel : ViewModelBase
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(LocalModsViewModel));
    private static readonly string[] LocalFilterOptionsCache = ["全部", "已啟用", "已停用"];

    private readonly IUiService _ui;
    private readonly ModsContext _context;
    private readonly IModManager _modManager;
    private readonly IModFileService _modFileService;
    private readonly IModListExporter _modListExporter;
    private readonly IExternalLauncher _launcher;
    private readonly List<LocalModRowItem> _allLocalMods = [];
    private int _loadGeneration;

    [ObservableProperty]
    public partial string LocalSearchText { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string SelectedLocalFilter { get; set; } = "全部";

    [ObservableProperty]
    public partial LocalModRowItem? SelectedLocalMod { get; set; }

    [ObservableProperty]
    public partial bool CanBatchToggle { get; set; }

    [ObservableProperty]
    public partial bool CanCheckUpdates { get; set; }

    [ObservableProperty]
    public partial bool CanDeleteMod { get; set; }

    public BulkObservableCollection<LocalModRowItem> LocalMods { get; } = [];

    public static IReadOnlyList<string> LocalFilterOptions => LocalFilterOptionsCache;

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

    partial void OnLocalSearchTextChanged(string value) => ApplyLocalFilter();

    partial void OnSelectedLocalFilterChanged(string value) => ApplyLocalFilter();

    partial void OnSelectedLocalModChanged(LocalModRowItem? value)
    {
        CanDeleteMod = value is not null || LocalMods.Any(static m => m.IsSelected);
        DeleteSelectedModCommand.NotifyCanExecuteChanged();
    }

    /// <summary>
    /// 取得目前勾選之模組（供更新檢查使用）
    /// </summary>
    public IReadOnlyList<LocalModRowItem> GetCheckedMods() => LocalMods.Where(static m => m.IsSelected).ToList();

    [RelayCommand]
    public async Task RefreshLocalModsAsync()
    {
        await LoadLocalModsAsync();
        Logger.Information("已重新整理本地模組清單 (伺服器: {Server})", _context.Server?.Name.Value);
    }

    /// <summary>
    /// 依目前伺服器快照重新載入本地模組
    /// </summary>
    public async Task LoadLocalModsAsync()
    {
        // 以世代編號取代忙碌旗標：切換伺服器時新載入覆蓋舊載入，舊結果到達後直接捨棄
        int generation = ++_loadGeneration;
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

            var mods = await _modManager.GetModsAsync(server.Path);
            if (generation != _loadGeneration)
            {
                return;
            }

            // 以檔名去重，杜絕重複列項
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var mod in mods)
            {
                string dedupeKey = !string.IsNullOrWhiteSpace(mod.Filename) ? mod.Filename : mod.Id;
                if (seen.Add(dedupeKey))
                {
                    _allLocalMods.Add(ToRowItem(mod));
                }
            }

            Logger.Information("載入本地模組成功，共 {Count} 個模組 (伺服器: {Server})", _allLocalMods.Count, server.Name.Value);
            ApplyLocalFilter();
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "載入本地模組失敗: {Message}", ex.Message);
            _ui.Notify($"載入模組失敗：{ex.Message}", NotificationType.Error);
        }
    }

    private static LocalModRowItem ToRowItem(LocalModInfo mod) => new()
    {
        Id = mod.Id,
        Name = mod.Name,
        Version = string.IsNullOrWhiteSpace(mod.Version) ? "-" : mod.Version,
        FileName = mod.Filename,
        FileSize = mod.FileSize > 0 ? UnitFormatter.FormatBytes(mod.FileSize) : "-",
        Author = string.IsNullOrWhiteSpace(mod.Author) ? "-" : mod.Author,
        LoaderType = string.IsNullOrWhiteSpace(mod.LoaderType) ? "-" : mod.LoaderType,
        MinecraftVersion = string.IsNullOrWhiteSpace(mod.MinecraftVersion) ? "-" : mod.MinecraftVersion,
        RawFileSize = mod.FileSize,
        ModifiedTime = FormatModTime(mod.FileMtime),
        Description = mod.Description,
        IsEnabled = mod.Status == ModStatus.Enabled,
        SourcePlatform = mod.Platform == ModPlatform.CurseForge ? "CurseForge" : "Modrinth",
        CurrentHash = mod.CurrentHash,
        HashAlgorithm = mod.HashAlgorithm,
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
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning("轉換模組發布時間失敗: {0}", ex.Message);
            return "-";
        }
    }

    /// <summary>
    /// 依搜尋文字與啟用狀態篩選本地模組
    /// </summary>
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

        UpdateSelectionState(LocalMods.Count(static m => m.IsSelected));
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
        if (mod is null || _context.Server is not { } server)
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
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "切換模組「{Name}」狀態失敗", mod.Name);
            _ui.Notify($"切換模組「{mod.Name}」狀態失敗：{ex.Message}", NotificationType.Error);
        }
    }

    [RelayCommand]
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
            catch (Exception ex) when (ex is not OperationCanceledException)
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

        try
        {
            _ui.CopyToClipboard(BuildModInfoText(target));
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning("複製模組資訊至剪貼簿失敗: {Message}", ex.Message);
        }
    }

    /// <summary>
    /// 組合模組資訊純文字（略過空白或 "-" 欄位）
    /// </summary>
    public static string BuildModInfoText(LocalModRowItem target)
    {
        ArgumentNullException.ThrowIfNull(target);
        var lines = new List<string>();
        AddLine(lines, "模組名稱", target.Name);
        AddLine(lines, "版本", target.Version);
        lines.Add($"狀態: {(target.IsEnabled ? "啟用" : "停用")}");
        AddLine(lines, "作者", target.Author);
        AddLine(lines, "載入器", target.LoaderType);
        AddLine(lines, "檔案大小", target.FileSize);
        AddLine(lines, "修改時間", target.ModifiedTime);
        AddLine(lines, "描述", target.Description);
        return string.Join(Environment.NewLine, lines);

        static void AddLine(List<string> lines, string label, string? value)
        {
            if (!string.IsNullOrWhiteSpace(value) && value != "-")
            {
                lines.Add($"{label}: {value.Trim()}");
            }
        }
    }

    [RelayCommand]
    public Task OpenModsFolderAsync()
    {
        if (_context.Server is not { } server)
        {
            _ui.Notify("請先選擇伺服器", NotificationType.Warning);
            return Task.CompletedTask;
        }

        string modsDir;
        try
        {
            modsDir = _modFileService.EnsureModsDirectory(server.Path);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error("建立模組資料夾失敗: {Message}", ex.Message);
            _ui.Notify($"無法建立模組資料夾：{ex.Message}", NotificationType.Error);
            return Task.CompletedTask;
        }

        Logger.Information("開啟模組資料夾: {Path}", modsDir);
        if (!_launcher.OpenFolder(modsDir))
        {
            _ui.Notify($"無法開啟資料夾：{modsDir}", NotificationType.Warning);
        }

        return Task.CompletedTask;
    }

    [RelayCommand]
    public async Task ShowInFolderAsync(LocalModRowItem? mod)
    {
        var targetMod = mod ?? SelectedLocalMod;
        if (targetMod is null || _context.Server is not { } server)
        {
            return;
        }

        string filePath = await Task.Run(() => _modFileService.ResolveModFilePath(server.Path, targetMod.FileName)).ConfigureAwait(true);
        if (!_launcher.ShowInFolder(filePath))
        {
            _ui.Notify($"無法在資料夾中顯示：{filePath}", NotificationType.Warning);
        }
    }

    [RelayCommand]
    public async Task ImportModsAsync()
    {
        if (_context.Server is not { } server)
        {
            _ui.Notify("請先選擇伺服器以匯入模組", NotificationType.Warning);
            return;
        }

        if (await _ui.PickFilesAsync("選取要匯入的 Minecraft 模組檔案 (.jar)", FileTypeChoice.Jar, multiselect: true) is not { } files)
        {
            return;
        }

        int count = 0;
        foreach (string file in files)
        {
            var result = await _modManager.ImportModAsync(server.Path, file);
            if (result.Completed || result.Partial)
            {
                count++;
            }
        }

        Logger.Information("已成功匯入 {Count} 個模組檔案至「{Server}」", count, server.Name.Value);
        await LoadLocalModsAsync();
        _ui.Notify($"已成功匯入 {count} 個模組檔案至伺服器", NotificationType.Success);
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
            _ui.Notify(successMsg, NotificationType.Success);
        }
        else
        {
            Logger.Warning("刪除模組失敗: {Message}", result.Message);
            _ui.Notify($"刪除失敗：{result.Message}", NotificationType.Error);
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

        var rows = _allLocalMods.Select(ToExportRow).ToList();
        await _ui.ShowExportModListAsync(server.Name.Value, rows, _modListExporter, _launcher);
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
}
