using System.Globalization;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 伺服器名單管理（ops.json, whitelist.json, banned-players.json, banned-ips.json）對話方塊 ViewModel
/// </summary>
public sealed partial class PlayerManagementViewModel : ObservableObject
{
    private readonly IServerPlayerConfigStore _configStore;
    private readonly IUiService _ui;
    private readonly List<ServerUserCacheEntry> _allUserCache = [];

    public string ServerName { get; }
    public string ServerPath { get; }

    [ObservableProperty]
    public partial string PlayerSearchText { get; set; } = string.Empty;

    partial void OnPlayerSearchTextChanged(string value) => ApplyUserCacheFilter();

    [ObservableProperty]
    public partial ServerUserCacheEntry? SelectedUserCacheEntry { get; set; }

    [ObservableProperty]
    public partial bool IsLoading { get; set; } = true;

    [ObservableProperty]
    public partial string StatusMessage { get; set; } = string.Empty;

    [ObservableProperty]
    public partial bool HasUnsavedChanges { get; set; }

    // --- 各標籤頁新增表單屬性 ---
    [ObservableProperty]
    public partial ServerUserCacheEntry? SelectedOpCandidate { get; set; }

    [ObservableProperty]
    public partial OpLevelOption SelectedOpLevel { get; set; }

    [ObservableProperty]
    public partial bool OpBypassesPlayerLimit { get; set; }

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
    public BulkObservableCollection<ServerOperatorEntry> Operators { get; } = [];
    public BulkObservableCollection<ServerWhitelistEntry> Whitelist { get; } = [];
    public BulkObservableCollection<ServerBannedPlayerEntry> BannedPlayers { get; } = [];
    public BulkObservableCollection<ServerBannedIpEntry> BannedIps { get; } = [];

    [ObservableProperty]
    public partial string NewPlayerName { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string NewPlayerUuid { get; set; } = string.Empty;

    public IReadOnlyList<OpLevelOption> OpLevelOptions { get; } =
    [
        new(4, "等級 4 - 伺服器完全控制權限 (stop, save-all 等維護指令)"),
        new(3, "等級 3 - 玩家名單與權限管理 (op, deop, kick, ban 等)"),
        new(2, "等級 2 - 允許使用作弊指令與指令方塊 (gamemode, tp, give 等)"),
        new(1, "等級 1 - 僅略過出生點方塊保護 (無作弊與管理指令)"),
    ];

    public event Action<bool>? RequestClose;

    public PlayerManagementViewModel(
        string serverName,
        string serverPath,
        IServerPlayerConfigStore configStore,
        IUiService ui)
    {
        ServerName = serverName;
        ServerPath = serverPath;
        _configStore = configStore;
        _ui = ui;
        SelectedOpLevel = OpLevelOptions[0];
    }

    public async Task InitializeAsync()
    {
        IsLoading = true;
        StatusMessage = "正在讀取伺服器名單設定檔案...";

        try
        {
            var bundle = await _configStore.LoadBundleAsync(ServerPath).ConfigureAwait(true);

            _allUserCache.Clear();
            _allUserCache.AddRange(bundle.UserCache);

            Operators.ReplaceAll(bundle.Operators);

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
            StatusMessage = $"讀取失敗：{ex.Message}";
        }
        finally
        {
            IsLoading = false;
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
        SelectedOpCandidate = AvailableCandidates.FirstOrDefault();
        SelectedWhitelistCandidate = AvailableCandidates.FirstOrDefault();
        SelectedBanCandidate = AvailableCandidates.FirstOrDefault();
    }

    [RelayCommand]
    public void AddCustomPlayer()
    {
        string name = NewPlayerName.Trim();
        if (string.IsNullOrWhiteSpace(name))
        {
            StatusMessage = "請輸入玩家名稱";
            return;
        }

        string uuid = string.IsNullOrWhiteSpace(NewPlayerUuid) ? Guid.NewGuid().ToString() : NewPlayerUuid.Trim();

        if (OperatorRows.Any(r => string.Equals(r.Name, name, StringComparison.OrdinalIgnoreCase) ||
                                  (!string.IsNullOrWhiteSpace(r.Uuid) && string.Equals(r.Uuid, uuid, StringComparison.OrdinalIgnoreCase))))
        {
            StatusMessage = $"玩家「{name}」已存在於名單中";
            return;
        }

        var newRow = new OperatorRowItem(
            name,
            uuid,
            isOp: true,
            level: 4,
            bypassesPlayerLimit: false,
            () =>
            {
                HasUnsavedChanges = true;
                StatusMessage = "管理員名單已變更，尚未儲存";
            });

        OperatorRows.Insert(0, newRow);
        NewPlayerName = string.Empty;
        NewPlayerUuid = string.Empty;
        HasUnsavedChanges = true;
        StatusMessage = $"已手動新增玩家「{name}」並設為管理員 (Level 4)";
    }

    [RelayCommand]
    public void AddOperator()
    {
        if (SelectedOpCandidate is null)
        {
            StatusMessage = "請先從下拉選單選取要設為管理員的玩家";
            return;
        }

        if (Operators.Any(o => string.Equals(o.Uuid, SelectedOpCandidate.Uuid, StringComparison.OrdinalIgnoreCase)))
        {
            StatusMessage = $"玩家「{SelectedOpCandidate.Name}」已在管理員名單中";
            return;
        }

        var entry = new ServerOperatorEntry(
            Uuid: SelectedOpCandidate.Uuid,
            Name: SelectedOpCandidate.Name,
            Level: SelectedOpLevel.Level,
            BypassesPlayerLimit: OpBypassesPlayerLimit);

        Operators.Add(entry);

        var existing = OperatorRows.FirstOrDefault(r => string.Equals(r.Uuid, SelectedOpCandidate.Uuid, StringComparison.OrdinalIgnoreCase));
        if (existing is not null)
        {
            existing.IsOp = true;
            existing.Level = SelectedOpLevel.Level;
            existing.BypassesPlayerLimit = OpBypassesPlayerLimit;
        }
        else
        {
            OperatorRows.Insert(0, new OperatorRowItem(
                SelectedOpCandidate.Name,
                SelectedOpCandidate.Uuid,
                isOp: true,
                level: SelectedOpLevel.Level,
                bypassesPlayerLimit: OpBypassesPlayerLimit,
                () => HasUnsavedChanges = true));
        }

        HasUnsavedChanges = true;
        StatusMessage = $"已將「{SelectedOpCandidate.Name}」設為管理員 (Level {SelectedOpLevel.Level})";
    }

    [RelayCommand]
    public void RemoveOperator(ServerOperatorEntry? entry)
    {
        if (entry is not null)
        {
            Operators.Remove(entry);
            var existing = OperatorRows.FirstOrDefault(r => string.Equals(r.Uuid, entry.Uuid, StringComparison.OrdinalIgnoreCase));
            existing?.IsOp = false;

            HasUnsavedChanges = true;
            StatusMessage = $"已從管理員名單移除「{entry.Name}」";
        }
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

    [RelayCommand]
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

    [RelayCommand]
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

    [RelayCommand]
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
        IsLoading = true;
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
                Whitelist: [.. Whitelist],
                BannedPlayers: [.. BannedPlayers],
                BannedIps: [.. BannedIps]);

            await _configStore.SaveBundleAsync(ServerPath, bundle).ConfigureAwait(true);
            HasUnsavedChanges = false;
            RequestClose?.Invoke(true);
        }
        catch (Exception ex)
        {
            StatusMessage = $"儲存失敗：{ex.Message}";
        }
        finally
        {
            IsLoading = false;
        }
    }

    [RelayCommand]
    public void Cancel()
    {
        if (ConfirmDiscard())
        {
            RequestClose?.Invoke(false);
        }
    }

    /// <summary>
    /// 檢查是否有尚未儲存之暫存變更；若有則彈出確認詢問對話方塊
    /// </summary>
    public bool ConfirmDiscard()
    {
        if (!HasUnsavedChanges)
        {
            return true;
        }

        return _ui.Confirm("有尚未儲存的名單設定變更，確定要捨棄變更並關閉嗎？", "捨棄變更", UiMessageLevel.Warning);
    }

    private static string FormatMinecraftTimestamp(DateTimeOffset dto) =>
        dto.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture) + " " + dto.ToString("zzz", CultureInfo.InvariantCulture).Replace(":", "");
}

public sealed record OpLevelOption(int Level, string Display);

/// <summary>
/// 管理員名單資料列項目模型
/// </summary>
public sealed partial class OperatorRowItem : ObservableObject
{
    private readonly Action? _onChanged;

    public string Name { get; init; } = string.Empty;
    public string Uuid { get; init; } = string.Empty;

    [ObservableProperty]
    public partial bool IsOp { get; set; }

    [ObservableProperty]
    public partial int Level { get; set; } = 4;

    [ObservableProperty]
    public partial bool BypassesPlayerLimit { get; set; }

    partial void OnIsOpChanged(bool value) => _onChanged?.Invoke();
    partial void OnLevelChanged(int value) => _onChanged?.Invoke();
    partial void OnBypassesPlayerLimitChanged(bool value) => _onChanged?.Invoke();

    public static IReadOnlyList<int> AvailableLevels { get; } = [1, 2, 3, 4];

    public OperatorRowItem(string name, string uuid, bool isOp, int level, bool bypassesPlayerLimit, Action? onChanged = null)
    {
        Name = name;
        Uuid = uuid;
        IsOp = isOp;
        Level = level is >= 1 and <= 4 ? level : 4;
        BypassesPlayerLimit = bypassesPlayerLimit;
        _onChanged = onChanged;
    }
}
