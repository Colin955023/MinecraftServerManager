using System.Collections.ObjectModel;
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
    private string _value = string.Empty;

    [ObservableProperty]
    private bool _boolValue;

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
        _value = value;
        Category = category;
        Description = description;
        DefaultValue = defaultValue;
        EditorType = editorType;
        Options = options ?? Array.Empty<string>();

        if (editorType == PropertyEditorType.Boolean)
        {
            _boolValue = bool.TryParse(value, out bool b) && b;
        }
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
            if (_boolValue != b)
            {
                _boolValue = b;
                OnPropertyChanged(nameof(BoolValue));
            }
        }
    }

    [RelayCommand]
    public void ResetToDefault()
    {
        Value = DefaultValue;
        if (IsBoolean)
        {
            BoolValue = bool.TryParse(DefaultValue, out bool b) && b;
        }
    }
}

/// <summary>
/// 伺服器屬性設定對話框 ViewModel
/// </summary>
public sealed partial class ServerPropertiesViewModel : ObservableObject
{
    private readonly IServerPropertiesStore _propertiesStore;
    private readonly string _serverName;
    private ServerPropertiesSnapshot? _snapshot;
    private readonly List<PropertyEditItem> _allItems = [];

    [ObservableProperty]
    private string _searchText = string.Empty;

    [ObservableProperty]
    private string _selectedCategory = "全部";

    [ObservableProperty]
    private string _motd = "A Minecraft Server";

    [ObservableProperty]
    private string _serverPort = "25565";

    [ObservableProperty]
    private string _maxPlayers = "20";

    [ObservableProperty]
    private string _selectedDifficulty = "easy";

    [ObservableProperty]
    private string _selectedGamemode = "survival";

    [ObservableProperty]
    private bool _pvp = true;

    [ObservableProperty]
    private bool _onlineMode = true;

    [ObservableProperty]
    private bool _whiteList;

    [ObservableProperty]
    private string _statusMessage = string.Empty;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsNotSaving))]
    private bool _isSaving;

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

        IsSaving = true;
        try
        {
            var patches = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (var item in _allItems)
            {
                patches[item.Key] = item.Value.Trim();
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
