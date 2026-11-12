using System.Collections.ObjectModel;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>模組管理頁面 ViewModel：負責伺服器選取與分頁導覽，並組合本地、線上、安裝佇列與更新子 ViewModel</summary>
public sealed partial class ModsViewModel : PageViewModel, IDisposable
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ModsViewModel));
    private const string NoServerPlaceholder = "請選擇伺服器";

    private readonly IServerManager _serverManager;
    private readonly IUiService _ui;
    private bool _isLoadingServers;

    [ObservableProperty]
    public partial string SelectedServer { get; set; } = NoServerPlaceholder;

    [ObservableProperty]
    public partial bool HasSelectedServer { get; set; }

    [ObservableProperty]
    public partial int SelectedTabIndex { get; set; }

    public ObservableCollection<string> Servers { get; } = [];

    /// <summary>子 ViewModel 共用之伺服器狀態</summary>
    public ModsContext Context { get; } = new();

    /// <summary>本地模組清單</summary>
    public LocalModsViewModel Local { get; }

    /// <summary>線上模組搜尋</summary>
    public OnlineModSearchViewModel Online { get; }

    /// <summary>安裝佇列</summary>
    public ModInstallQueueViewModel Queue { get; }

    /// <summary>更新檢查</summary>
    public ModUpdateViewModel Updates { get; }

    public ModsViewModel(
        IModDependencyPlanner dependencyPlanner,
        IModListExporter modListExporter,
        IModFileService modFileService,
        IUiService uiService,
        IServerManager serverManager,
        IModManager modManager,
        IModrinthClient modrinthClient,
        IExternalLauncher launcher)
        : base("🧩 模組管理")
    {
        ArgumentNullException.ThrowIfNull(dependencyPlanner);
        ArgumentNullException.ThrowIfNull(modListExporter);
        ArgumentNullException.ThrowIfNull(modFileService);
        ArgumentNullException.ThrowIfNull(uiService);
        ArgumentNullException.ThrowIfNull(serverManager);
        ArgumentNullException.ThrowIfNull(modManager);
        ArgumentNullException.ThrowIfNull(modrinthClient);
        ArgumentNullException.ThrowIfNull(launcher);

        _serverManager = serverManager;
        _ui = uiService;

        Local = new LocalModsViewModel(Context, modFileService, modListExporter, uiService, modManager, launcher);
        Online = new OnlineModSearchViewModel(Context, uiService, modrinthClient, launcher);
        Queue = new ModInstallQueueViewModel(Context, dependencyPlanner, modFileService, uiService, modManager, modrinthClient);
        Updates = new ModUpdateViewModel(Context, dependencyPlanner, modFileService, uiService, modManager, modrinthClient);
    }

    partial void OnSelectedTabIndexChanged(int value) => Online.SetActiveTab(value == 1);

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
            return;
        }

        _isLoadingServers = true;
        try
        {
            string previous = SelectedServer;
            Servers.Clear();

            var allServers = await _serverManager.GetAllServersAsync();
            var serverNames = allServers
                .Where(static s => s.LoaderType is LoaderKind.Fabric or LoaderKind.Forge or LoaderKind.NeoForge or LoaderKind.Quilt)
                .Select(static s => s.Name.Value)
                .ToList();
            if (serverNames.Count > 0)
            {
                foreach (string name in serverNames)
                {
                    Servers.Add(name);
                }

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

            Servers.Add(NoServerPlaceholder);
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
        }
    }

    /// <summary>挑選線上模組版本並加入安裝清單（未指定時使用線上清單選取項目）</summary>
    [RelayCommand]
    public Task PickOnlineModVersionAsync(OnlineModRowItem? mod) =>
        Queue.PickVersionAndQueueAsync(mod ?? Online.SelectedOnlineMod);

    /// <summary>檢查本地已勾選模組之相容更新</summary>
    [RelayCommand]
    public Task CheckModUpdatesAsync() => Updates.CheckModUpdatesAsync(Local.GetCheckedMods());

    public void Dispose() => Online.Dispose();
}
