using System.Diagnostics.CodeAnalysis;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Infrastructure.Logging;

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
    public PropertyEditItem(
        string key,
        string value,
        string category,
        string description,
        string defaultValue,
        PropertyEditorType editorType,
        IReadOnlyList<string>? options = null)
    {
        ArgumentNullException.ThrowIfNull(key);
        Key = key;
        Category = category;
        Description = description;
        DefaultValue = defaultValue;
        EditorType = editorType;
        Options = options ?? [];

        if (editorType == PropertyEditorType.Boolean && string.IsNullOrWhiteSpace(value))
        {
            value = !string.IsNullOrWhiteSpace(defaultValue) ? defaultValue : "false";
        }

        InitialValue = value ?? string.Empty;
        Value = InitialValue;
        if (editorType == PropertyEditorType.Boolean)
        {
            BoolValue = bool.TryParse(InitialValue, out bool b) && b;
        }

        Validate();
    }

    public string Key { get; }
    public string Category { get; }
    public string Description { get; }
    public string DefaultValue { get; }
    public PropertyEditorType EditorType { get; }
    public IReadOnlyList<string> Options { get; }

    /// <summary>載入時的值，用於判斷是否已修改</summary>
    public string InitialValue { get; }

    /// <summary>
    /// 屬性值；null 一律於設值當下正規化為空字串，變更即重新驗證
    /// （不使用 [ObservableProperty]，以免 OnValueChanging 無法替換 null 而使通知期間出現 null）
    /// </summary>
    public string Value
    {
        get;
        set
        {
            if (SetProperty(ref field, value ?? string.Empty))
            {
                Validate();
            }
        }
    } = string.Empty;

    /// <summary>值與載入時不同（忽略前後空白）</summary>
    public bool IsChanged => !string.Equals(Value.Trim(), InitialValue.Trim(), StringComparison.Ordinal);

    [ObservableProperty]
    public partial bool BoolValue { get; set; }

    [ObservableProperty]
    public partial string? ErrorMessage { get; set; }

    public bool IsBoolean => EditorType == PropertyEditorType.Boolean;
    public bool IsOptions => EditorType == PropertyEditorType.Options;

    partial void OnBoolValueChanged(bool value) => Value = value ? "true" : "false";

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
    }
}

/// <summary>伺服器屬性設定對話方塊 ViewModel</summary>
public sealed partial class ServerPropertiesViewModel : DialogViewModelBase, IUnsavedChangesPrompt
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerPropertiesViewModel));
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

    private readonly IUiService _ui;
    private readonly IServerPropertiesStore _propertiesStore;
    private readonly string _serverName;
    private readonly List<PropertyEditItem> _allItems = [];
    private ServerPropertiesSnapshot? _snapshot;

    public ServerPropertiesViewModel(
        IServerPropertiesStore propertiesStore,
        string serverName,
        IUiService uiService)
    {
        ArgumentNullException.ThrowIfNull(propertiesStore);
        ArgumentException.ThrowIfNullOrWhiteSpace(serverName);
        ArgumentNullException.ThrowIfNull(uiService);
        _ui = uiService;
        _propertiesStore = propertiesStore;
        _serverName = serverName;

        _ = RunSafeAsync(LoadPropertiesAsync, "載入伺服器屬性設定", Logger);
    }

    /// <summary>屬性已載入；載入前停用儲存與還原預設</summary>
    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(SaveCommand), nameof(ResetAllToDefaultCommand))]
    public partial bool IsLoaded { get; private set; }

    [ObservableProperty]
    public partial string SearchText { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string SelectedCategory { get; set; } = "全部";

    [ObservableProperty]
    public partial string StatusMessage { get; set; } = string.Empty;

    /// <summary>狀態訊息是否為錯誤（決定 InfoBar 嚴重性）</summary>
    [ObservableProperty]
    public partial bool IsStatusError { get; set; }

    /// <summary>已載入屬性但篩選後無符合項目</summary>
    [ObservableProperty]
    public partial bool HasNoMatches { get; set; }

    public BulkObservableCollection<PropertyEditItem> DisplayItems { get; } = [];

    [SuppressMessage("Performance", "CA1822:Mark members as static", Justification = "x:Bind 靜態路徑在 SelectedCategory 之後才更新，ItemsSource 為空時 SelectedItem 會被回寫為 null")]
    public IReadOnlyList<string> Categories => CategoriesCache;

    public bool HasUnsavedChanges => _allItems.Exists(static item => item.IsChanged);

    partial void OnSearchTextChanged(string value) => ApplyFilter();

    partial void OnSelectedCategoryChanged(string value)
    {
        // ItemsSource 重設時 ComboBox 可能回寫 null，改回「全部」避免清單被清空
        if (value is null)
        {
            SelectedCategory = "全部";
            return;
        }

        ApplyFilter();
    }

    public async Task LoadPropertiesAsync()
    {
        try
        {
            _snapshot = await _propertiesStore.ReadAsync(_serverName);
            var props = _snapshot.Properties;

            _allItems.Clear();

            // 收集所有已知的 key 與實際存在的 key
            HashSet<string> allKeys = new(StringComparer.OrdinalIgnoreCase);
            foreach (string key in ServerPropertiesMetadata.KnownKeys)
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

                if (ServerPropertiesMetadata.IsBoolean(key))
                {
                    editorType = PropertyEditorType.Boolean;
                }
                else
                {
                    IReadOnlyList<string>? opt = ServerPropertiesMetadata.GetOptions(key);
                    if (opt is not null)
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
            IsLoaded = true;
        }
        catch (OperationCanceledException)
        {
            Logger.Information("伺服器屬性讀取操作已取消");
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "讀取伺服器屬性失敗");
            SetStatus($"讀取屬性失敗：{ex.Message}", isError: true);
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
        HasNoMatches = DisplayItems.Count == 0 && _allItems.Count > 0;
    }

    [RelayCommand(CanExecute = nameof(IsLoaded))]
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
        SetStatus("已將所有屬性還原為官方預設值", isError: false);
    }

    /// <summary>還原單一屬性為預設值</summary>
    public static void ResetItem(PropertyEditItem? item) => item?.ResetToDefault();

    [RelayCommand(CanExecute = nameof(IsLoaded))]
    public async Task SaveAsync()
    {
        if (_snapshot is null)
        {
            return;
        }

        // 儲存前先對所有屬性進行嚴格驗證
        foreach (var item in _allItems)
        {
            if (!item.Validate())
            {
                SetStatus($"「{item.Key}」設定值無效：{item.ErrorMessage}", isError: true);
                return;
            }
        }

        try
        {
            // 僅篩選出有修改之差異項進行儲存，加速寫入效率
            var patches = _allItems.Where(static item => item.IsChanged).ToDictionary(static item => item.Key, static item => item.Value.Trim(), StringComparer.OrdinalIgnoreCase);

            // 若沒有任何屬性被修改，無需執行磁碟 I/O，直接成功關閉
            if (patches.Count == 0)
            {
                Close(true);
                return;
            }

            var result = await _propertiesStore.UpdateAsync(_serverName, patches, _snapshot.Revision);
            if (result.Success)
            {
                Close(true);
            }
            else
            {
                SetStatus($"儲存失敗：{result.Message}", isError: true);
            }
        }
        catch (OperationCanceledException)
        {
            Logger.Information("伺服器屬性儲存操作已取消");
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "儲存伺服器屬性失敗");
            SetStatus($"儲存失敗：{ex.Message}", isError: true);
        }
    }

    public Task<bool> ConfirmDiscardAsync() =>
        ConfirmDiscardChangesAsync(_ui, HasUnsavedChanges, "有尚未儲存的伺服器屬性變更，確定要捨棄變更並關閉嗎？");

    [RelayCommand]
    public async Task CancelAsync()
    {
        if (await ConfirmDiscardAsync())
        {
            Close(false);
        }
    }

    private void SetStatus(string message, bool isError)
    {
        IsStatusError = isError;
        StatusMessage = message;
    }
}
