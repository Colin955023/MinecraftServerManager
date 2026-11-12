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

/// <summary>伺服器名單管理（ops.json, whitelist.json, banned-players.json, banned-ips.json）對話方塊 ViewModel</summary>
public sealed partial class PlayerManagementViewModel(
    string serverName,
    string serverPath,
    IServerPlayerConfigStore configStore,
    IUiService ui) : ViewModelBase
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(PlayerManagementViewModel));
    private readonly IServerPlayerConfigStore _configStore = configStore;
    private readonly IUiService _ui = ui;
    private readonly List<ServerUserCacheEntry> _allUserCache = [];

    public string ServerName { get; } = serverName;
    public string ServerPath { get; } = serverPath;

    [ObservableProperty]
    public partial string PlayerSearchText { get; set; } = string.Empty;

    partial void OnPlayerSearchTextChanged(string value) => ApplyUserCacheFilter();

    [ObservableProperty]
    public partial ServerUserCacheEntry? SelectedUserCacheEntry { get; set; }

    [ObservableProperty]
    public partial string StatusMessage { get; set; } = string.Empty;

    [ObservableProperty]
    public partial bool HasUnsavedChanges { get; set; }

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

    public event Action<bool>? RequestClose;

    public async Task InitializeAsync()
    {
        StatusMessage = "正在讀取伺服器名單設定檔案...";

        try
        {
            var bundle = await _configStore.LoadBundleAsync(ServerPath).ConfigureAwait(true);

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
            StatusMessage = $"讀取完成，共有 {_allUserCache.Count} 位曾連線玩家紀錄，{OperatorRows.Count} 位名冊玩家";
        }
        catch (Exception ex)
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

        if (Whitelist.Any(w => string.Equals(w.Uuid, SelectedWhitelistCandidate.Uuid, StringComparison.OrdinalIgnoreCase)))
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

        if (BannedPlayers.Any(b => string.Equals(b.Uuid, SelectedBanCandidate.Uuid, StringComparison.OrdinalIgnoreCase)))
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
            StatusMessage = "禁止封鎖萬用全域 IP (0.0.0.0 或 ::)，否則將導致伺服器無法接受任何連線！";
            return;
        }

        if (System.Net.IPAddress.Loopback.Equals(parsedIp) || System.Net.IPAddress.IPv6Loopback.Equals(parsedIp))
        {
            StatusMessage = "禁止封鎖本機迴路 IP (127.0.0.1 或 ::1)！";
            return;
        }

        if (System.Net.IPAddress.Broadcast.Equals(parsedIp))
        {
            StatusMessage = "禁止封鎖廣播 IP (255.255.255.255)！";
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

    [RelayCommand]
    public async Task SaveAsync()
    {
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

            await _configStore.SaveBundleAsync(ServerPath, bundle).ConfigureAwait(true);
            HasUnsavedChanges = false;
            RequestClose?.Invoke(true);
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "儲存伺服器名單設定失敗");
            StatusMessage = $"儲存失敗：{ex.Message}";
        }
    }

    [RelayCommand]
    public async Task CancelAsync()
    {
        if (await ConfirmDiscardAsync())
        {
            RequestClose?.Invoke(false);
        }
    }

    /// <summary>檢查是否有尚未儲存之暫存變更；若有則彈出確認詢問對話方塊</summary>
    public Task<bool> ConfirmDiscardAsync() =>
        ConfirmDiscardChangesAsync(_ui, HasUnsavedChanges, "有尚未儲存的名單設定變更，確定要捨棄變更並關閉嗎？");

    private static string FormatMinecraftTimestamp(DateTimeOffset dto) =>
        dto.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture) + " " + dto.ToString("zzz", CultureInfo.InvariantCulture).Replace(":", "", StringComparison.Ordinal);
}

/// <summary>管理員名單資料列項目模型</summary>
public sealed partial class OperatorRowItem(string name, string uuid, bool isOp, int level, bool bypassesPlayerLimit, Action onChanged) : ObservableObject
{
    private readonly Action _onChanged = onChanged;

    public string Name { get; init; } = name;
    public string Uuid { get; init; } = uuid;

    [ObservableProperty]
    public partial bool IsOp { get; set; } = isOp;

    [ObservableProperty]
    public partial int Level { get; set; } = level is >= 1 and <= 4 ? level : 4;

    [ObservableProperty]
    public partial bool BypassesPlayerLimit { get; set; } = bypassesPlayerLimit;

    partial void OnIsOpChanged(bool value) => _onChanged();
    partial void OnLevelChanged(int value) => _onChanged();
    partial void OnBypassesPlayerLimitChanged(bool value) => _onChanged();

    private static readonly int[] LevelsCache = [1, 2, 3, 4];
    [SuppressMessage("Performance", "CA1822:Mark members as static", Justification = "WinUI 3 x:Bind requires instance member for DataTemplate bindings")]
    public IReadOnlyList<int> AvailableLevels => LevelsCache;
}
