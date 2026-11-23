using System.ComponentModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>模組管理頁面：伺服器選取、分頁導覽與各子 ViewModel</summary>
public sealed partial class ModsViewModel : PageViewModel, IDisposable
{
    private const string NoServerPlaceholder = "請選擇伺服器";

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ModsViewModel));
    private static readonly string[] NoServerPlaceholderArray = [NoServerPlaceholder];

    private readonly IServerManager _serverManager;
    private readonly IUiService _ui;
    private bool _isLoadingServers;
    private bool _reloadPending;
    private bool _disposed;

    /// <summary>子 ViewModel 由 <see cref="PageViewModelFactory"/> 以同一 <paramref name="context"/> 組裝後注入</summary>
    public ModsViewModel(
        ModsContext context,
        LocalModsViewModel local,
        OnlineModSearchViewModel online,
        ModInstallQueueViewModel queue,
        ModUpdateViewModel updates,
        IServerManager serverManager,
        IUiService uiService)
        : base("模組管理")
    {
        ArgumentNullException.ThrowIfNull(context);
        ArgumentNullException.ThrowIfNull(local);
        ArgumentNullException.ThrowIfNull(online);
        ArgumentNullException.ThrowIfNull(queue);
        ArgumentNullException.ThrowIfNull(updates);
        ArgumentNullException.ThrowIfNull(serverManager);
        ArgumentNullException.ThrowIfNull(uiService);

        Context = context;
        Local = local;
        Online = online;
        Queue = queue;
        Updates = updates;
        _serverManager = serverManager;
        _ui = uiService;
        Local.PropertyChanged += OnLocalPropertyChanged;
    }

    [ObservableProperty]
    public partial string SelectedServer { get; set; } = NoServerPlaceholder;

    [ObservableProperty]
    public partial bool HasSelectedServer { get; set; }

    [ObservableProperty]
    public partial int SelectedTabIndex { get; set; }

    /// <summary>線上分頁首次切換後才建立（之後保留以免重建）</summary>
    [ObservableProperty]
    public partial bool IsOnlineTabCreated { get; private set; }

    public BulkObservableCollection<string> Servers { get; } = [];

    /// <summary>子 ViewModel 共用之伺服器狀態</summary>
    public ModsContext Context { get; }

    /// <summary>本地模組清單</summary>
    public LocalModsViewModel Local { get; }

    /// <summary>線上模組搜尋</summary>
    public OnlineModSearchViewModel Online { get; }

    /// <summary>安裝佇列</summary>
    public ModInstallQueueViewModel Queue { get; }

    /// <summary>更新檢查</summary>
    public ModUpdateViewModel Updates { get; }

    private void OnLocalPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(LocalModsViewModel.CanCheckUpdates))
        {
            CheckModUpdatesCommand.NotifyCanExecuteChanged();
        }
    }

    partial void OnSelectedTabIndexChanged(int value)
    {
        bool online = value == 1;
        IsOnlineTabCreated |= online;
        Online.SetActiveTab(online);
    }

    partial void OnSelectedServerChanged(string value)
    {
        HasSelectedServer = !string.IsNullOrWhiteSpace(value) && value != NoServerPlaceholder;
        _ = RunSafeAsync(ReloadSelectedServerAsync, "載入本機模組清單", Logger);
    }

    [RelayCommand]
    public async Task RefreshServersAsync()
    {
        await LoadServersInternalAsync();
        Logger.Information("伺服器下拉清單已重新整理");
    }

    /// <summary>重新讀取選取伺服器設定快照並重新載入本地模組</summary>
    public async Task ReloadSelectedServerAsync()
    {
        ServerConfig? server = null;
        string requestedServer = SelectedServer;
        if (HasSelectedServer)
        {
            try
            {
                server = await _serverManager.GetServerAsync(requestedServer);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Error(ex, "讀取伺服器「{Name}」設定失敗", requestedServer);
                _ui.Notify($"讀取伺服器設定失敗：{ex.Message}", NotificationType.Error);
            }
        }

        // 讀取期間使用者已改選其他伺服器時，捨棄過時結果（新的選取會另行觸發載入）
        if (!string.Equals(requestedServer, SelectedServer, StringComparison.Ordinal))
        {
            return;
        }

        Context.SetServer(server);
        await Local.LoadLocalModsAsync();
    }

    private async Task LoadServersInternalAsync()
    {
        if (_isLoadingServers)
        {
            // 載入中再收到請求：結束後補跑一次，避免漏掉最新狀態
            _reloadPending = true;
            return;
        }

        _isLoadingServers = true;
        try
        {
            string previous = SelectedServer;
            var allServers = await _serverManager.GetAllServersAsync();
            var serverNames = allServers
                .Where(static s => s.LoaderType is LoaderKind.Fabric or LoaderKind.Forge or LoaderKind.NeoForge or LoaderKind.Quilt)
                .Select(static s => s.Name.Value)
                .ToList();
            if (serverNames.Count > 0)
            {
                Servers.ReplaceAll(serverNames);

                // 保留既有選取項目，避免重新整理後重設回第一筆
                string target = serverNames.Contains(previous, StringComparer.OrdinalIgnoreCase)
                    ? previous
                    : serverNames[0];

                if (string.Equals(SelectedServer, target, StringComparison.Ordinal))
                {
                    // 選取值未變更不會觸發 OnSelectedServerChanged，需主動載入一次
                    await ReloadSelectedServerAsync();
                }
                else
                {
                    // 指派後由 OnSelectedServerChanged 單一路徑觸發載入，不重複呼叫
                    SelectedServer = target;
                }

                return;
            }

            Servers.ReplaceAll(NoServerPlaceholderArray);
            SelectedServer = NoServerPlaceholder;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "載入伺服器清單失敗");
            _ui.Notify($"載入伺服器清單失敗：{ex.Message}", NotificationType.Error);
        }
        finally
        {
            _isLoadingServers = false;
            if (_reloadPending)
            {
                _reloadPending = false;
                await LoadServersInternalAsync();
            }
        }
    }

    /// <summary>挑選線上模組版本並加入安裝清單（未指定時使用線上清單選取項目）</summary>
    [RelayCommand]
    public Task PickOnlineModVersionAsync(OnlineModRowItem? mod) =>
        Queue.PickVersionAndQueueAsync(mod ?? Online.SelectedOnlineMod);

    /// <summary>檢查本地已勾選模組之相容更新</summary>
    [RelayCommand(CanExecute = nameof(CanCheckModUpdates))]
    public Task CheckModUpdatesAsync() => Updates.CheckModUpdatesAsync(Local.GetCheckedMods());

    private bool CanCheckModUpdates() => Local.CanCheckUpdates;

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        Local.PropertyChanged -= OnLocalPropertyChanged;
        Local.Dispose();
        Online.Dispose();
        Queue.Dispose();
    }
}
