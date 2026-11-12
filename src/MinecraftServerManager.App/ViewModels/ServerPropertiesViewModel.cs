using System.Diagnostics.CodeAnalysis;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Services;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>屬性編輯控制項型別</summary>
public enum PropertyEditorType
{
    Text,
    Boolean,
    Options
}

/// <summary>單項屬性編輯項目 ViewModel</summary>
public sealed partial class PropertyEditItem : ObservableObject
{
    public string Key { get; }
    public string Category { get; }
    public string Description { get; }
    public string DefaultValue { get; }
    public PropertyEditorType EditorType { get; }
    public IReadOnlyList<string> Options { get; }

    /// <summary>屬性值；ComboBox 於清單回收或視窗關閉時可能雙向寫回 null，一律正規化為空字串</summary>
    public string Value
    {
        get;
        set => SetProperty(ref field, value ?? string.Empty);
    } = string.Empty;

    [ObservableProperty]
    public partial bool BoolValue { get; set; }

    partial void OnBoolValueChanged(bool value) => Value = value ? "true" : "false";

    [ObservableProperty]
    public partial string? ErrorMessage { get; set; }

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
            if (string.IsNullOrWhiteSpace(value))
            {
                value = !string.IsNullOrWhiteSpace(defaultValue) ? defaultValue : "false";
                Value = value;
            }

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

/// <summary>伺服器屬性設定對話方塊 ViewModel</summary>
public sealed partial class ServerPropertiesViewModel : ViewModelBase
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerPropertiesViewModel));
    private readonly IUiService _ui;

    private readonly IServerPropertiesStore _propertiesStore;
    private readonly string _serverName;
    private ServerPropertiesSnapshot? _snapshot;
    private readonly List<PropertyEditItem> _allItems = [];

    [ObservableProperty]
    public partial string SearchText { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string SelectedCategory { get; set; } = "全部";

    partial void OnSearchTextChanged(string value) => ApplyFilter();

    partial void OnSelectedCategoryChanged(string value) => ApplyFilter();

    [ObservableProperty]
    public partial string StatusMessage { get; set; } = string.Empty;

    public BulkObservableCollection<PropertyEditItem> DisplayItems { get; } = [];

    private static readonly string[] CategoriesCache =
    [
        "全部",
        "基本設定",
        "遊戲設定",
        "世界設定",
        "網路與安全",
        "遠端與進階",
        "自訂屬性"
    ];

    [SuppressMessage("Performance", "CA1822:Mark members as static", Justification = "WinUI 3 x:Bind requires instance property when bound to ViewModel")]
    public IReadOnlyList<string> Categories => CategoriesCache;

    public event Action<bool>? RequestClose;

    public ServerPropertiesViewModel(IServerPropertiesStore propertiesStore, string serverName,
        IUiService uiService)
    {
        _ui = uiService;
        _propertiesStore = propertiesStore;
        _serverName = serverName;

        _ = RunSafeAsync(LoadPropertiesAsync, "載入伺服器屬性設定", Logger);
    }

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

            foreach (string key in allKeys.OrderBy(static k => ServerPropertiesMetadata.GetCategory(k)).ThenBy(static k => k, StringComparer.OrdinalIgnoreCase))
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

            ApplyFilter();
        }
        catch (OperationCanceledException)
        {
            Logger.Information("伺服器屬性讀取操作已取消");
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "讀取伺服器屬性失敗");
            StatusMessage = $"讀取屬性失敗：{ex.Message}";
        }
    }

    private void ApplyFilter()
    {
        string query = SearchText.Trim();
        bool matchCategory = !string.Equals(SelectedCategory, "全部", StringComparison.OrdinalIgnoreCase);

        var filtered = _allItems.Where(item =>
        {
            if (matchCategory && !string.Equals(item.Category, SelectedCategory, StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }

            if (!string.IsNullOrEmpty(query))
            {
                bool keyMatch = item.Key.Contains(query, StringComparison.OrdinalIgnoreCase);
                bool descMatch = item.Description.Contains(query, StringComparison.OrdinalIgnoreCase);
                if (!keyMatch && !descMatch)
                {
                    return false;
                }
            }

            return true;
        });

        DisplayItems.ReplaceAll(filtered);
    }

    [RelayCommand]
    public async Task ResetAllToDefaultAsync()
    {
        if (!await _ui.ConfirmAsync("確定要將所有伺服器設定屬性還原為預設值嗎？", "確認還原預設", UiMessageLevel.Warning))
        {
            return;
        }

        foreach (var item in _allItems)
        {
            item.ResetToDefault();
        }
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

        try
        {
            // 僅篩選出有修改之差異項進行儲存，加速寫入效率
            var patches = ChangedItems(_snapshot).ToDictionary(static item => item.Key, static item => item.Value.Trim(), StringComparer.OrdinalIgnoreCase);

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
        catch (OperationCanceledException)
        {
            Logger.Information("伺服器屬性儲存操作已取消");
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "儲存伺服器屬性失敗");
            StatusMessage = $"儲存失敗：{ex.Message}";
        }
    }

    public bool HasUnsavedChanges => _snapshot is not null && ChangedItems(_snapshot).Any();

    private IEnumerable<PropertyEditItem> ChangedItems(ServerPropertiesSnapshot snapshot) =>
        _allItems.Where(item => !snapshot.Properties.TryGetValue(item.Key, out string? orig) ||
            !string.Equals(orig.Trim(), item.Value.Trim(), StringComparison.Ordinal));

    public Task<bool> ConfirmDiscardAsync() =>
        ConfirmDiscardChangesAsync(_ui, HasUnsavedChanges, "有尚未儲存的伺服器屬性變更，確定要捨棄變更並關閉嗎？");

    [RelayCommand]
    public async Task CancelAsync()
    {
        if (await ConfirmDiscardAsync())
        {
            RequestClose?.Invoke(false);
        }
    }
}
