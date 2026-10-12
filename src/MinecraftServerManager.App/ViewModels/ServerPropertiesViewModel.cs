using System.Collections.ObjectModel;
using System.Windows;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 屬性編輯控制項型別
/// </summary>
public enum PropertyEditorType
{
    Text,
    Boolean,
    Options
}

/// <summary>
/// 單項屬性編輯項目 ViewModel
/// </summary>
public sealed partial class PropertyEditItem : ObservableObject
{
    public string Key { get; }
    public string Category { get; }
    public string Description { get; }
    public string DefaultValue { get; }
    public PropertyEditorType EditorType { get; }
    public IReadOnlyList<string> Options { get; }

    [ObservableProperty]
    public partial string Value { get; set; } = string.Empty;

    [ObservableProperty]
    public partial bool BoolValue { get; set; }

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(HasError))]
    public partial string? ErrorMessage { get; set; }

    public bool HasError => !string.IsNullOrEmpty(ErrorMessage);

    public bool IsBoolean => EditorType == PropertyEditorType.Boolean;
    public bool IsOptions => EditorType == PropertyEditorType.Options;
    public bool IsText => EditorType == PropertyEditorType.Text;

    public PropertyEditItem(
        string key,
        string value,
        string category,
        string description,
        string defaultValue,
        PropertyEditorType editorType,
        IReadOnlyList<string>? options = null)
    {
        Key = key;
        Value = value;
        Category = category;
        Description = description;
        DefaultValue = defaultValue;
        EditorType = editorType;
        Options = options ?? [];

        if (editorType == PropertyEditorType.Boolean)
        {
            BoolValue = bool.TryParse(value, out bool b) && b;
        }

        Validate();
    }

    public bool Validate()
    {
        var (isValid, error) = ServerPropertiesValidator.ValidateProperty(Key, Value, DefaultValue);
        ErrorMessage = isValid ? null : error;
        return isValid;
    }

    partial void OnBoolValueChanged(bool value)
    {
        if (IsBoolean)
        {
            Value = value.ToString().ToLowerInvariant();
        }
    }

    partial void OnValueChanged(string value)
    {
        if (IsBoolean && bool.TryParse(value, out bool b))
        {
            if (BoolValue != b)
            {
                BoolValue = b;
            }
        }

        Validate();
    }

    [RelayCommand]
    public void ResetToDefault()
    {
        Value = DefaultValue;
        if (IsBoolean)
        {
            BoolValue = bool.TryParse(DefaultValue, out bool b) && b;
        }
        Validate();
    }
}

/// <summary>
/// 伺服器屬性設定對話方塊 ViewModel
/// </summary>
public sealed partial class ServerPropertiesViewModel : ObservableObject
{
    private readonly IServerPropertiesStore _propertiesStore;
    private readonly string _serverName;
    private ServerPropertiesSnapshot? _snapshot;
    private readonly List<PropertyEditItem> _allItems = [];

    [ObservableProperty]
    public partial string SearchText { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string SelectedCategory { get; set; } = "全部";

    [ObservableProperty]
    public partial string Motd { get; set; } = "A Minecraft Server";

    [ObservableProperty]
    public partial string ServerPort { get; set; } = "25565";

    [ObservableProperty]
    public partial string MaxPlayers { get; set; } = "20";

    [ObservableProperty]
    public partial string SelectedDifficulty { get; set; } = "easy";

    [ObservableProperty]
    public partial string SelectedGamemode { get; set; } = "survival";

    [ObservableProperty]
    public partial bool Pvp { get; set; } = true;

    [ObservableProperty]
    public partial bool OnlineMode { get; set; } = true;

    [ObservableProperty]
    public partial bool WhiteList { get; set; }

    [ObservableProperty]
    public partial string StatusMessage { get; set; } = string.Empty;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsNotSaving))]
    public partial bool IsSaving { get; set; }

    public bool IsNotSaving => !IsSaving;

    public ObservableCollection<PropertyEditItem> DisplayItems { get; } = [];

    public IReadOnlyList<string> Categories { get; } =
    [
        "全部",
        "基本設定",
        "遊戲設定",
        "世界設定",
        "網路與安全",
        "遠端與進階",
        "自訂屬性"
    ];

    public string WindowTitle { get; }

    public IReadOnlyList<string> Difficulties { get; } = ["peaceful", "easy", "normal", "hard"];

    public IReadOnlyList<string> Gamemodes { get; } = ["survival", "creative", "adventure", "spectator"];

    public event Action<bool>? RequestClose;

    public ServerPropertiesViewModel(IServerPropertiesStore propertiesStore, string serverName)
    {
        _propertiesStore = propertiesStore;
        _serverName = serverName;
        WindowTitle = $"伺服器設定 — {serverName}";

        _ = LoadPropertiesAsync();
    }

    partial void OnSearchTextChanged(string value) => ApplyFilter();

    partial void OnSelectedCategoryChanged(string value) => ApplyFilter();

    public async Task LoadPropertiesAsync()
    {
        try
        {
            _snapshot = await _propertiesStore.ReadAsync(_serverName).ConfigureAwait(true);
            var props = _snapshot.Properties;

            _allItems.Clear();

            // 收集所有已知的 key 與實際存在的 key
            HashSet<string> allKeys = new(StringComparer.OrdinalIgnoreCase);
            foreach (string key in ServerPropertiesMetadata.Descriptions.Keys)
            {
                allKeys.Add(key);
            }
            foreach (string key in props.Keys)
            {
                allKeys.Add(key);
            }

            foreach (string key in allKeys.OrderBy(k => ServerPropertiesMetadata.GetCategory(k)).ThenBy(k => k, StringComparer.OrdinalIgnoreCase))
            {
                string category = ServerPropertiesMetadata.GetCategory(key);
                string description = ServerPropertiesMetadata.GetDescription(key);
                string defaultValue = ServerPropertiesMetadata.GetDefault(key, string.Empty);
                string currentValue = props.TryGetValue(key, out string? v) ? v : defaultValue;

                PropertyEditorType editorType;
                IReadOnlyList<string>? options = null;

                if (ServerPropertiesMetadata.BooleanKeys.Contains(key))
                {
                    editorType = PropertyEditorType.Boolean;
                }
                else
                {
                    string[]? opt = ServerPropertiesMetadata.GetOptions(key);
                    if (opt is not null && opt.Length > 0)
                    {
                        editorType = PropertyEditorType.Options;
                        options = opt;
                    }
                    else
                    {
                        editorType = PropertyEditorType.Text;
                    }
                }

                PropertyEditItem item = new(key, currentValue, category, description, defaultValue, editorType, options);
                _allItems.Add(item);
            }

            // 同步快捷屬性
            SyncLegacyProperties();

            ApplyFilter();
        }
        catch (Exception ex)
        {
            StatusMessage = $"讀取屬性失敗：{ex.Message}";
        }
    }

    private void SyncLegacyProperties()
    {
        PropertyEditItem? motdItem = _allItems.FirstOrDefault(i => string.Equals(i.Key, "motd", StringComparison.OrdinalIgnoreCase));
        if (motdItem is not null)
        {
            Motd = motdItem.Value;
        }

        PropertyEditItem? portItem = _allItems.FirstOrDefault(i => string.Equals(i.Key, "server-port", StringComparison.OrdinalIgnoreCase));
        if (portItem is not null)
        {
            ServerPort = portItem.Value;
        }

        PropertyEditItem? mpItem = _allItems.FirstOrDefault(i => string.Equals(i.Key, "max-players", StringComparison.OrdinalIgnoreCase));
        if (mpItem is not null)
        {
            MaxPlayers = mpItem.Value;
        }

        PropertyEditItem? diffItem = _allItems.FirstOrDefault(i => string.Equals(i.Key, "difficulty", StringComparison.OrdinalIgnoreCase));
        if (diffItem is not null)
        {
            SelectedDifficulty = diffItem.Value;
        }

        PropertyEditItem? gmItem = _allItems.FirstOrDefault(i => string.Equals(i.Key, "gamemode", StringComparison.OrdinalIgnoreCase));
        if (gmItem is not null)
        {
            SelectedGamemode = gmItem.Value;
        }

        PropertyEditItem? pvpItem = _allItems.FirstOrDefault(i => string.Equals(i.Key, "pvp", StringComparison.OrdinalIgnoreCase));
        if (pvpItem is not null)
        {
            Pvp = pvpItem.BoolValue;
        }

        PropertyEditItem? omItem = _allItems.FirstOrDefault(i => string.Equals(i.Key, "online-mode", StringComparison.OrdinalIgnoreCase));
        if (omItem is not null)
        {
            OnlineMode = omItem.BoolValue;
        }

        PropertyEditItem? wlItem = _allItems.FirstOrDefault(i => string.Equals(i.Key, "white-list", StringComparison.OrdinalIgnoreCase));
        if (wlItem is not null)
        {
            WhiteList = wlItem.BoolValue;
        }
    }

    private void ApplyFilter()
    {
        DisplayItems.Clear();
        string query = SearchText.Trim();
        bool matchCategory = !string.Equals(SelectedCategory, "全部", StringComparison.OrdinalIgnoreCase);

        foreach (var item in _allItems)
        {
            if (matchCategory && !string.Equals(item.Category, SelectedCategory, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            if (!string.IsNullOrEmpty(query))
            {
                bool keyMatch = item.Key.Contains(query, StringComparison.OrdinalIgnoreCase);
                bool descMatch = item.Description.Contains(query, StringComparison.OrdinalIgnoreCase);
                if (!keyMatch && !descMatch)
                {
                    continue;
                }
            }

            DisplayItems.Add(item);
        }
    }

    [RelayCommand]
    public void ResetAllToDefault()
    {
        if (!Views.DialogHelper.Confirm("確定要將所有伺服器設定屬性還原為預設值嗎？", "確認還原預設", MessageBoxImage.Warning))
        {
            return;
        }

        foreach (var item in _allItems)
        {
            item.ResetToDefault();
        }
        SyncLegacyProperties();
        StatusMessage = "已將所有屬性還原為官方預設值";
    }

    [RelayCommand]
    public async Task SaveAsync()
    {
        if (_snapshot is null)
        {
            StatusMessage = "屬性尚未載入完成";
            return;
        }

        // 儲存前先對所有屬性進行嚴格驗證
        foreach (var item in _allItems)
        {
            if (!item.Validate())
            {
                StatusMessage = $"「{item.Key}」設定值無效：{item.ErrorMessage}";
                return;
            }
        }

        IsSaving = true;
        try
        {
            // 僅篩選出有修改之差異項進行儲存，加速寫入效率
            var patches = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (var item in _allItems)
            {
                string currentVal = item.Value.Trim();
                string? originalVal = _snapshot.Properties.TryGetValue(item.Key, out string? orig) ? orig.Trim() : null;

                if (originalVal is null || !string.Equals(originalVal, currentVal, StringComparison.Ordinal))
                {
                    patches[item.Key] = currentVal;
                }
            }

            // 若沒有任何屬性被修改，無需執行磁碟 I/O，直接成功關閉
            if (patches.Count == 0)
            {
                RequestClose?.Invoke(true);
                return;
            }

            var result = await _propertiesStore.UpdateAsync(_serverName, patches, _snapshot.Revision).ConfigureAwait(true);
            if (result.Success)
            {
                RequestClose?.Invoke(true);
            }
            else
            {
                StatusMessage = $"儲存失敗：{result.Message}";
            }
        }
        catch (Exception ex)
        {
            StatusMessage = $"儲存異常：{ex.Message}";
        }
        finally
        {
            IsSaving = false;
        }
    }

    [RelayCommand]
    public void Cancel() => RequestClose?.Invoke(false);
}
