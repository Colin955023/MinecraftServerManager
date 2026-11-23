using System.Diagnostics.CodeAnalysis;
using System.Globalization;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>伺服器名單管理對話方塊 ViewModel</summary>
public sealed partial class PlayerManagementViewModel : DialogViewModelBase, IUnsavedChangesPrompt
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(PlayerManagementViewModel));
    private readonly IServerPlayerConfigStore _configStore;
    private readonly IUiService _ui;
    private readonly List<ServerUserCacheEntry> _allUserCache = [];

    public PlayerManagementViewModel(
        string serverName,
        string serverPath,
        IServerPlayerConfigStore configStore,
        IUiService ui)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(serverName);
        ArgumentException.ThrowIfNullOrWhiteSpace(serverPath);
        ArgumentNullException.ThrowIfNull(configStore);
        ArgumentNullException.ThrowIfNull(ui);

        ServerName = serverName;
        ServerPath = serverPath;
        _configStore = configStore;
        _ui = ui;
    }

    public string ServerName { get; }
    public string ServerPath { get; }

    [ObservableProperty]
    public partial string PlayerSearchText { get; set; } = string.Empty;

    [ObservableProperty]
    public partial ServerUserCacheEntry? SelectedUserCacheEntry { get; set; }

    [ObservableProperty]
    public partial string StatusMessage { get; set; } = string.Empty;

    [ObservableProperty]
    public partial bool HasUnsavedChanges { get; set; }

    /// <summary>名單已成功讀取；讀取失敗時禁止儲存以免以空名單覆寫檔案</summary>
    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(SaveCommand))]
    public partial bool IsLoaded { get; private set; }

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(SaveCommand))]
    public partial bool IsSaving { get; private set; }

    // --- 各標籤頁新增表單屬性 ---
    [ObservableProperty]
    public partial ServerUserCacheEntry? SelectedWhitelistCandidate { get; set; }

    [ObservableProperty]
    public partial ServerUserCacheEntry? SelectedBanCandidate { get; set; }

    [ObservableProperty]
    public partial string BanPlayerReason { get; set; } = "Banned by an operator.";

    [ObservableProperty]
    public partial string BanIpAddress { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string BanIpReason { get; set; } = "Banned by an operator.";

    // --- 資料集合 ---
    public BulkObservableCollection<ServerUserCacheEntry> FilteredUserCache { get; } = [];
    public BulkObservableCollection<ServerUserCacheEntry> AvailableCandidates { get; } = [];
    public BulkObservableCollection<OperatorRowItem> OperatorRows { get; } = [];
    public BulkObservableCollection<ServerWhitelistEntry> Whitelist { get; } = [];
    public BulkObservableCollection<ServerBannedPlayerEntry> BannedPlayers { get; } = [];
    public BulkObservableCollection<ServerBannedIpEntry> BannedIps { get; } = [];

    private bool CanSave => IsLoaded && !IsSaving;

    partial void OnPlayerSearchTextChanged(string value) => ApplyUserCacheFilter();

    public async Task InitializeAsync()
    {
        StatusMessage = "正在讀取伺服器名單設定檔案...";
        IsLoaded = false;

        try
        {
            var bundle = await _configStore.LoadBundleAsync(ServerPath);

            _allUserCache.Clear();
            _allUserCache.AddRange(bundle.UserCache);

            var playersMap = new Dictionary<string, (string Name, string Uuid, bool IsOp, int Level, bool Bypass)>(StringComparer.OrdinalIgnoreCase);

            foreach (var u in bundle.UserCache)
            {
                if (!string.IsNullOrWhiteSpace(u.Uuid))
                {
                    playersMap[u.Uuid] = (u.Name, u.Uuid, false, 4, false);
                }
            }

            foreach (var op in bundle.Operators)
            {
                string key = !string.IsNullOrWhiteSpace(op.Uuid) ? op.Uuid : op.Name;
                if (!string.IsNullOrWhiteSpace(key))
                {
                    playersMap[key] = (op.Name, op.Uuid, true, op.Level, op.BypassesPlayerLimit);
                }
            }

            var opRows = playersMap.Values
                .OrderByDescending(x => x.IsOp)
                .ThenBy(x => x.Name, StringComparer.OrdinalIgnoreCase)
                .Select(x => new OperatorRowItem(
                    x.Name,
                    x.Uuid,
                    x.IsOp,
                    x.Level,
                    x.Bypass,
                    () =>
                    {
                        HasUnsavedChanges = true;
                        StatusMessage = "管理員名單已變更，尚未儲存";
                    }));

            OperatorRows.ReplaceAll(opRows);
            Whitelist.ReplaceAll(bundle.Whitelist);
            BannedPlayers.ReplaceAll(bundle.BannedPlayers);
            BannedIps.ReplaceAll(bundle.BannedIps);

            UpdateAvailableCandidates();
            ApplyUserCacheFilter();

            HasUnsavedChanges = false;
            IsLoaded = true;
            StatusMessage = $"讀取完成，共有 {_allUserCache.Count} 位曾連線玩家紀錄，{OperatorRows.Count} 位名冊玩家";
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "讀取伺服器名單設定失敗");
            StatusMessage = $"讀取失敗：{ex.Message}";
        }
    }

    private void ApplyUserCacheFilter()
    {
        string q = PlayerSearchText.Trim();
        var filtered = string.IsNullOrEmpty(q)
            ? _allUserCache
            : _allUserCache.Where(u => u.Name.Contains(q, StringComparison.OrdinalIgnoreCase));
        FilteredUserCache.ReplaceAll(filtered);
    }

    private void UpdateAvailableCandidates()
    {
        AvailableCandidates.ReplaceAll(_allUserCache);
        SelectedWhitelistCandidate = AvailableCandidates.FirstOrDefault();
        SelectedBanCandidate = AvailableCandidates.FirstOrDefault();
    }

    [RelayCommand]
    public void AddWhitelist()
    {
        if (SelectedWhitelistCandidate is null)
        {
            StatusMessage = "請先從下拉選單選取要加入白名單的玩家";
            return;
        }

        if (Whitelist.Any(w => IsSamePlayer(w.Uuid, w.Name, SelectedWhitelistCandidate)))
        {
            StatusMessage = $"玩家「{SelectedWhitelistCandidate.Name}」已在白名單中";
            return;
        }

        var entry = new ServerWhitelistEntry(
            Uuid: SelectedWhitelistCandidate.Uuid,
            Name: SelectedWhitelistCandidate.Name);

        Whitelist.Add(entry);
        HasUnsavedChanges = true;
        StatusMessage = $"已將「{SelectedWhitelistCandidate.Name}」加入白名單暫存";
    }

    public void RemoveWhitelist(ServerWhitelistEntry? entry)
    {
        if (entry is not null && Whitelist.Remove(entry))
        {
            HasUnsavedChanges = true;
            StatusMessage = $"已從白名單移除「{entry.Name}」";
        }
    }

    [RelayCommand]
    public void AddBannedPlayer()
    {
        if (SelectedBanCandidate is null)
        {
            StatusMessage = "請先從下拉選單選取要封鎖的玩家";
            return;
        }

        if (BannedPlayers.Any(b => IsSamePlayer(b.Uuid, b.Name, SelectedBanCandidate)))
        {
            StatusMessage = $"玩家「{SelectedBanCandidate.Name}」已在封鎖名單中";
            return;
        }

        string now = FormatMinecraftTimestamp(DateTimeOffset.Now);
        var entry = new ServerBannedPlayerEntry(
            Uuid: SelectedBanCandidate.Uuid,
            Name: SelectedBanCandidate.Name,
            Created: now,
            Source: "Server",
            Expires: "forever",
            Reason: string.IsNullOrWhiteSpace(BanPlayerReason) ? "Banned by an operator." : BanPlayerReason.Trim());

        BannedPlayers.Add(entry);
        HasUnsavedChanges = true;
        StatusMessage = $"已將「{SelectedBanCandidate.Name}」加入玩家封鎖暫存名單";
    }

    public void RemoveBannedPlayer(ServerBannedPlayerEntry? entry)
    {
        if (entry is not null && BannedPlayers.Remove(entry))
        {
            HasUnsavedChanges = true;
            StatusMessage = $"已解除封鎖玩家「{entry.Name}」";
        }
    }

    [RelayCommand]
    public void AddBannedIp()
    {
        string ip = BanIpAddress.Trim();
        if (string.IsNullOrWhiteSpace(ip))
        {
            StatusMessage = "請輸入欲封鎖的 IP 位址";
            return;
        }

        if (!System.Net.IPAddress.TryParse(ip, out var parsedIp))
        {
            StatusMessage = $"「{ip}」不是有效的 IPv4 或 IPv6 位址格式";
            return;
        }

        if (System.Net.IPAddress.Any.Equals(parsedIp) || System.Net.IPAddress.IPv6Any.Equals(parsedIp))
        {
            StatusMessage = "禁止封鎖萬用全域 IP（0.0.0.0 或 ::），否則將導致伺服器無法接受任何連線！";
            return;
        }

        if (System.Net.IPAddress.Loopback.Equals(parsedIp) || System.Net.IPAddress.IPv6Loopback.Equals(parsedIp))
        {
            StatusMessage = "禁止封鎖本機迴路 IP（127.0.0.1 或 ::1）！";
            return;
        }

        if (System.Net.IPAddress.Broadcast.Equals(parsedIp))
        {
            StatusMessage = "禁止封鎖廣播 IP（255.255.255.255）！";
            return;
        }

        string normalizedIp = parsedIp.ToString();
        if (BannedIps.Any(b => string.Equals(b.Ip, normalizedIp, StringComparison.OrdinalIgnoreCase) || string.Equals(b.Ip, ip, StringComparison.OrdinalIgnoreCase)))
        {
            StatusMessage = $"IP「{normalizedIp}」已在封鎖名單中";
            return;
        }

        string now = FormatMinecraftTimestamp(DateTimeOffset.Now);
        var entry = new ServerBannedIpEntry(
            Ip: normalizedIp,
            Created: now,
            Source: "Server",
            Expires: "forever",
            Reason: string.IsNullOrWhiteSpace(BanIpReason) ? "Banned by an operator." : BanIpReason.Trim());

        BannedIps.Add(entry);
        BanIpAddress = string.Empty;
        HasUnsavedChanges = true;
        StatusMessage = $"已將 IP「{normalizedIp}」加入封鎖暫存名單";
    }

    public void RemoveBannedIp(ServerBannedIpEntry? entry)
    {
        if (entry is not null && BannedIps.Remove(entry))
        {
            HasUnsavedChanges = true;
            StatusMessage = $"已解除封鎖 IP「{entry.Ip}」";
        }
    }

    [RelayCommand(CanExecute = nameof(CanSave))]
    public async Task SaveAsync()
    {
        if (!CanSave)
        {
            return;
        }

        IsSaving = true;
        StatusMessage = "正在儲存伺服器名單設定...";

        try
        {
            var ops = OperatorRows
                .Where(r => r.IsOp)
                .Select(r => new ServerOperatorEntry(
                    Uuid: r.Uuid,
                    Name: r.Name,
                    Level: r.Level,
                    BypassesPlayerLimit: r.BypassesPlayerLimit))
                .ToList();

            var bundle = new ServerPlayerConfigBundle(
                UserCache: _allUserCache,
                Operators: ops,
                Whitelist: (ServerWhitelistEntry[])[.. Whitelist],
                BannedPlayers: (ServerBannedPlayerEntry[])[.. BannedPlayers],
                BannedIps: (ServerBannedIpEntry[])[.. BannedIps]);

            await _configStore.SaveBundleAsync(ServerPath, bundle);
            HasUnsavedChanges = false;
            Close(true);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "儲存伺服器名單設定失敗");
            StatusMessage = $"儲存失敗：{ex.Message}";
        }
        finally
        {
            IsSaving = false;
        }
    }

    [RelayCommand]
    public async Task CancelAsync()
    {
        if (await ConfirmDiscardAsync())
        {
            Close(false);
        }
    }

    /// <summary>是否有尚未儲存之暫存變更；若有則彈出確認詢問對話方塊</summary>
    public Task<bool> ConfirmDiscardAsync() =>
        ConfirmDiscardChangesAsync(_ui, HasUnsavedChanges, "有尚未儲存的名單設定變更，確定要捨棄變更並關閉嗎？");

    /// <summary>兩端皆有 UUID 時比對 UUID，否則改比對名稱（離線模式 UUID 可能為空）</summary>
    private static bool IsSamePlayer(string uuid, string name, ServerUserCacheEntry candidate) =>
        !string.IsNullOrWhiteSpace(uuid) && !string.IsNullOrWhiteSpace(candidate.Uuid)
            ? string.Equals(uuid, candidate.Uuid, StringComparison.OrdinalIgnoreCase)
            : string.Equals(name, candidate.Name, StringComparison.OrdinalIgnoreCase);

    private static string FormatMinecraftTimestamp(DateTimeOffset dto) =>
        dto.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture) + " " + dto.ToString("zzz", CultureInfo.InvariantCulture).Replace(":", string.Empty, StringComparison.Ordinal);
}

/// <summary>管理員名單資料列項目模型</summary>
public sealed partial class OperatorRowItem : ObservableObject
{
    private static readonly int[] LevelsCache = [1, 2, 3, 4];

    private readonly Action _onChanged;

    public OperatorRowItem(string name, string uuid, bool isOp, int level, bool bypassesPlayerLimit, Action onChanged)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(name);
        ArgumentNullException.ThrowIfNull(uuid);
        ArgumentNullException.ThrowIfNull(onChanged);

        Name = name;
        Uuid = uuid;
        _onChanged = onChanged;
        IsOp = isOp;
        Level = level is >= 1 and <= 4 ? level : 4;
        BypassesPlayerLimit = bypassesPlayerLimit;
    }

    public string Name { get; init; }
    public string Uuid { get; init; }

    [ObservableProperty]
    public partial bool IsOp { get; set; }

    [ObservableProperty]
    public partial int Level { get; set; }

    [ObservableProperty]
    public partial bool BypassesPlayerLimit { get; set; }

    [SuppressMessage("Performance", "CA1822:Mark members as static", Justification = "x:Bind 靜態路徑在 Level 之後才更新，ItemsSource 為空時 SelectedItem 回寫 null 會擲出例外")]
    public IReadOnlyList<int> AvailableLevels => LevelsCache;

    partial void OnIsOpChanged(bool value) => _onChanged();
    partial void OnLevelChanged(int value) => _onChanged();
    partial void OnBypassesPlayerLimitChanged(bool value) => _onChanged();
}
