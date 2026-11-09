using System.Globalization;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 線上模組搜尋項目模型
/// </summary>
public sealed class OnlineModRowItem
{
    public string Id { get; init; } = string.Empty;

    public string? Slug { get; init; }

    public string Title { get; set; } = string.Empty;

    public string Author { get; init; } = string.Empty;

    public string Description { get; init; } = string.Empty;

    public string Downloads { get; init; } = "0";

    public long DownloadCountRaw { get; init; }

    public string LatestVersion { get; init; } = string.Empty;

    public string ServerSide { get; init; } = string.Empty;
}

/// <summary>
/// 模組頁：線上平台、關鍵字、排序與搜尋結果
/// </summary>
public sealed partial class OnlineModSearchViewModel : ViewModelBase
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(OnlineModSearchViewModel));
    private const string CurseForgeComingSoonHint = "CurseForge 模組搜尋即將推出，敬請期待";
    private const string NoServerFilterHint = "請先選擇伺服器以篩選相容模組";
    private static readonly string[] OnlineSortOptionsCache = ["相關性", "下載量", "最新發布", "最近更新", "名稱"];
    private static readonly string[] PlatformOptionsCache = ["Modrinth", "CurseForge"];

    private readonly ModsContext _context;
    private readonly IModrinthClient _modrinthClient;
    private readonly IExternalLauncher _launcher;
    private readonly IUiService _ui;
    private readonly List<OnlineModRowItem> _allOnlineMods = [];
    private CancellationTokenSource? _searchCts;

    [ObservableProperty]
    public partial string OnlineSearchText { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string SelectedPlatform { get; set; } = "Modrinth";

    [ObservableProperty]
    public partial string SelectedOnlineSort { get; set; } = "相關性";

    [ObservableProperty]
    public partial OnlineModRowItem? SelectedOnlineMod { get; set; }

    [ObservableProperty]
    public partial string OnlineFilterHint { get; set; } = NoServerFilterHint;

    [ObservableProperty]
    public partial bool IsSearchingOnline { get; set; }

    [ObservableProperty]
    public partial string OnlineResultHint { get; set; } = string.Empty;

    /// <summary>
    /// 線上分頁是否為目前顯示分頁（由父 ViewModel 設定）
    /// </summary>
    public bool IsActiveTab { get; private set; }

    public BulkObservableCollection<OnlineModRowItem> OnlineMods { get; } = [];

    public static IReadOnlyList<string> OnlineSortOptions => OnlineSortOptionsCache;

    public static IReadOnlyList<string> PlatformOptions => PlatformOptionsCache;

    public string OpenPlatformPageButtonText => IsCurseForge ? "開啟 CurseForge 頁面" : "開啟 Modrinth 頁面";

    private bool IsCurseForge => string.Equals(SelectedPlatform, "CurseForge", StringComparison.OrdinalIgnoreCase);

    public OnlineModSearchViewModel(
        ModsContext context,
        IUiService uiService,
        IModrinthClient modrinthClient,
        IExternalLauncher launcher)
    {
        ArgumentNullException.ThrowIfNull(context);
        ArgumentNullException.ThrowIfNull(uiService);
        ArgumentNullException.ThrowIfNull(modrinthClient);
        ArgumentNullException.ThrowIfNull(launcher);
        _context = context;
        _modrinthClient = modrinthClient;
        _launcher = launcher;
        _ui = uiService;
        _context.ServerChanged += OnServerChanged;
    }

    private void OnServerChanged()
    {
        OnlineFilterHint = _context.Server is { } server
            ? $"相容條件：Minecraft {server.MinecraftVersion.Value} ｜ 載入器: {server.LoaderType} ｜ 僅限伺服器端與兩端相容模組"
            : NoServerFilterHint;
    }

    /// <summary>
    /// 通知分頁切換；首次切換至線上分頁時自動預載推薦模組
    /// </summary>
    public void SetActiveTab(bool isActive)
    {
        IsActiveTab = isActive;
        if (isActive && _allOnlineMods.Count == 0 && !IsSearchingOnline)
        {
            _ = RunSafeAsync(SearchOnlineModsAsync, "搜尋線上模組", Logger);
        }
    }

    partial void OnSelectedOnlineSortChanged(string value)
    {
        if (value is "名稱" or "下載量")
        {
            ApplyOnlineSort();
        }
        else if (_allOnlineMods.Count > 0 || IsActiveTab)
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
        if (IsCurseForge)
        {
            ClearResults();
            OnlineResultHint = CurseForgeComingSoonHint;
            return;
        }

        OnlineResultHint = string.Empty;
        if (IsActiveTab)
        {
            _ = RunSafeAsync(SearchOnlineModsAsync, "搜尋線上模組", Logger);
        }
    }

    private void ClearResults()
    {
        _allOnlineMods.Clear();
        OnlineMods.Clear();
        SelectedOnlineMod = null;
    }

    [RelayCommand]
    public async Task SearchOnlineModsAsync()
    {
        if (IsCurseForge)
        {
            ClearResults();
            OnlineResultHint = CurseForgeComingSoonHint;
            return;
        }

        // 新搜尋取消前一次搜尋，避免較慢的舊回應覆寫新結果
        var searchCts = new CancellationTokenSource();
        var previousCts = _searchCts;
        _searchCts = searchCts;
        if (previousCts is not null)
        {
            await previousCts.CancelAsync().ConfigureAwait(true);
        }

        CancellationToken token = searchCts.Token;

        IsSearchingOnline = true;
        _allOnlineMods.Clear();
        OnlineMods.Clear();

        try
        {
            string? loader = _context.LoaderId;
            string? mcVersion = _context.MinecraftVersion;
            string query = OnlineSearchText?.Trim() ?? string.Empty;
            string sortIndex = SelectedOnlineSort switch
            {
                "下載量" => "downloads",
                "最新發布" => "newest",
                "最近更新" => "updated",
                _ => "relevance"
            };
            Logger.Information("搜尋線上模組: 平台: {Platform}, 關鍵字: {Query}, 載入器: {Loader}, MC版本: {Version}, 排序: {SortIndex}", SelectedPlatform, query, loader, mcVersion, sortIndex);
            var results = await _modrinthClient.SearchModsAsync(query, loader: loader, minecraftVersion: mcVersion, index: sortIndex, cancellationToken: token);
            token.ThrowIfCancellationRequested();

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
                    ServerSide = item.ServerSide
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
        catch (OperationCanceledException) when (token.IsCancellationRequested)
        {
            Logger.Information("線上搜尋已由較新的搜尋取代");
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "線上搜尋失敗: {Message}", ex.Message);
            _ui.Notify($"搜尋失敗：{ex.Message}", NotificationType.Error);
        }
        finally
        {
            if (ReferenceEquals(_searchCts, searchCts))
            {
                _searchCts = null;
                IsSearchingOnline = false;
            }

            searchCts.Dispose();
        }
    }

    private void ApplyOnlineSort()
    {
        IEnumerable<OnlineModRowItem> sorted = SelectedOnlineSort switch
        {
            "下載量" => _allOnlineMods.OrderByDescending(static m => m.DownloadCountRaw),
            "名稱" => _allOnlineMods.OrderBy(static m => m.Title, StringNaturalComparer.Instance),
            _ => _allOnlineMods
        };

        OnlineMods.ReplaceAll(sorted);
    }

    /// <summary>
    /// 於瀏覽器開啟選取模組的線上專案頁面。
    /// </summary>
    [RelayCommand]
    public void OpenModPlatformPage()
    {
        if (SelectedOnlineMod is not { } mod)
        {
            _ui.Notify("請先選取要檢視的線上模組", NotificationType.Warning);
            return;
        }

        string url = IsCurseForge
            ? $"https://www.curseforge.com/minecraft/mc-mods/{(!string.IsNullOrWhiteSpace(mod.Slug) ? mod.Slug : mod.Id)}"
            : $"https://modrinth.com/mod/{mod.Id}";

        if (!_launcher.OpenUrl(url, isTrusted: true))
        {
            _ui.Notify($"無法開啟連結：{url}", NotificationType.Warning);
        }
    }
}
