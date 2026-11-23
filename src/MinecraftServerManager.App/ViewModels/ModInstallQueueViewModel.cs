using System.Globalization;
using System.Text;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Collections;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>待安裝模組佇列項目</summary>
public sealed class ModInstallQueueItem
{
    public string ProjectId { get; set; } = string.Empty;

    public string Title { get; set; } = string.Empty;

    public string VersionNumber { get; set; } = string.Empty;

    public string? CurrentVersion { get; set; }

    public string FileName { get; set; } = string.Empty;

    public string? OldFileName { get; set; }

    public string DownloadUrl { get; set; } = string.Empty;

    public string? ExpectedHash { get; set; }

    public string HashAlgorithm { get; set; } = ModHelpers.PreferredHashAlgorithm;

    public IReadOnlyList<string> Dependencies { get; set; } = (string[])[];

    public ModInstallAction Action { get; set; } = ModInstallAction.Install;

    public string ActionText => Action == ModInstallAction.Update ? "更新" : "安裝";

    public string VersionDisplay => Action == ModInstallAction.Update && !string.IsNullOrWhiteSpace(CurrentVersion)
        ? $"{CurrentVersion} ➔ {VersionNumber}"
        : VersionNumber;

    public string Reason { get; set; } = "全新安裝";

    public bool PreserveDisabledState { get; set; }
}

/// <summary>模組頁：版本挑選、安裝佇列、相依解析與批次安裝</summary>
public sealed partial class ModInstallQueueViewModel : ModQueueWorkflowViewModelBase, IDisposable
{
    private const string EmptyQueueHint = "安裝清單為空";

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ModInstallQueueViewModel));
    private bool _disposed;

    public ModInstallQueueViewModel(
        ModsContext context,
        IModDependencyPlanner dependencyPlanner,
        IModFileService modFileService,
        IUiService uiService,
        IModManager modManager,
        IModrinthClient modrinthClient,
        IServerRuntimeHost runtimeHost)
        : base(context, dependencyPlanner, modFileService, uiService, modManager, modrinthClient, runtimeHost)
    {
        _context.ServerChanged += OnServerChanged;
    }

    [ObservableProperty]
    public partial string InstallQueueHint { get; set; } = EmptyQueueHint;

    [ObservableProperty]
    [NotifyCanExecuteChangedFor(nameof(InstallQueuedModsCommand), nameof(ClearInstallQueueCommand))]
    public partial bool IsInstalling { get; private set; }

    /// <summary>待安裝模組佇列（切換伺服器時清空）</summary>
    public BulkObservableCollection<ModInstallQueueItem> InstallQueue { get; } = [];

    private bool CanModifyQueue => !IsInstalling;

    /// <summary>彈出版本選擇對話方塊，將選定版本與必要相依模組加入安裝清單</summary>
    public async Task PickVersionAndQueueAsync(OnlineModRowItem? mod)
    {
        if (mod is null)
        {
            return;
        }

        // 偵測伺服器端環境相容性，防範純用戶端模組造成伺服器當機
        if (string.Equals(mod.ServerSide, "unsupported", StringComparison.OrdinalIgnoreCase)
            && !await _ui.ConfirmAsync(
                $"模組「{mod.Title}」在 Modrinth 標記為純用戶端模組（server_side: unsupported），在伺服器端執行可能引發當機！\n\n是否仍要強行挑選版本並加入安裝清單？",
                "伺服器端環境不相容警告",
                UiMessageLevel.Warning))
        {
            return;
        }

        ServerConfig? server = _context.Server;
        using var pickerVm = new ModVersionPickerViewModel(
            _modrinthClient,
            mod.Id,
            mod.Title,
            _context.LoaderType,
            _context.MinecraftVersion);

        if (await _ui.ShowModVersionPickerAsync(pickerVm) != true || pickerVm.QueuedVersion is not { } chosen)
        {
            return;
        }

        if (!ContainsFile(chosen.FileName))
        {
            InstallQueue.Add(new ModInstallQueueItem
            {
                ProjectId = mod.Id,
                Title = mod.Title,
                VersionNumber = chosen.VersionNumber,
                FileName = chosen.FileName,
                DownloadUrl = chosen.DownloadUrl,
                ExpectedHash = chosen.ExpectedHash,
                HashAlgorithm = chosen.HashAlgorithm,
                Dependencies = chosen.Dependencies
            });
        }

        if (server is not null && chosen.Dependencies.Count > 0)
        {
            await QueueMissingDependenciesAsync(mod.Title, mod.Id, chosen.Dependencies, server);
        }

        UpdateInstallQueueHint();

        if (pickerVm.InstallImmediately)
        {
            await InstallQueuedModsAsync();
        }
    }

    private bool ContainsFile(string? fileName) =>
        InstallQueue.Any(q => string.Equals(q.FileName, fileName, StringComparison.OrdinalIgnoreCase));

    private async Task QueueMissingDependenciesAsync(string modTitle, string rootProjectId, IReadOnlyList<string> dependencyIds, ServerConfig server)
    {
        try
        {
            var installed = await _modManager.GetModsAsync(server.Path);
            var rawDeps = dependencyIds
                .Select(static d => new OnlineModDependency(d, ModDependencyType.Required))
                .ToList();

            var plans = await _dependencyPlanner.ResolveDependenciesRecursivelyAsync(
                rawDeps,
                server.MinecraftVersion.Value,
                server.LoaderType,
                installed,
                rootProjectId);

            var toAdd = plans
                .Where(plan => plan.TargetVersion.PrimaryFile is { } pf && !ContainsFile(pf.FileName))
                .ToList();

            if (toAdd.Count == 0)
            {
                return;
            }

            if (!await _ui.ConfirmAsync(BuildDependencyPrompt(modTitle, toAdd), "發現必要相依模組"))
            {
                return;
            }

            if (!string.Equals(_context.Server?.Name.Value, server.Name.Value, StringComparison.OrdinalIgnoreCase))
            {
                Logger.Information("伺服器已切換，放棄將「{Mod}」的相依模組加入清單", modTitle);
                return;
            }

            foreach (var plan in toAdd)
            {
                var depVer = plan.TargetVersion;
                var pf = depVer.PrimaryFile!;
                InstallQueue.Add(new ModInstallQueueItem
                {
                    ProjectId = !string.IsNullOrWhiteSpace(depVer.ProjectId) ? depVer.ProjectId : depVer.VersionId,
                    Title = depVer.DisplayName,
                    VersionNumber = depVer.VersionNumber,
                    CurrentVersion = plan.ExistingLocalMod?.Version,
                    FileName = pf.FileName,
                    OldFileName = plan.ExistingLocalMod?.FileName,
                    DownloadUrl = pf.Url,
                    ExpectedHash = ModHelpers.ResolveHash(pf, out string algo),
                    HashAlgorithm = algo,
                    Dependencies = ModBatchOperations.GetRequiredDependencyIds(depVer),
                    Action = plan.Action,
                    Reason = plan.Reason,
                    PreserveDisabledState = plan.ExistingLocalMod is { Status: ModStatus.Disabled }
                });
            }

            _ui.Notify($"已將 {toAdd.Count} 個相依模組加入安裝清單", NotificationType.Success);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "檢查相依模組時發生例外");
        }
    }

    /// <summary>組合相依模組規劃確認訊息（依全新安裝與更新升級分段）</summary>
    public static string BuildDependencyPrompt(string modTitle, IReadOnlyList<ModDependencyPlanItem> plans)
    {
        ArgumentNullException.ThrowIfNull(plans);
        var sb = new StringBuilder();
        sb.AppendLine(CultureInfo.InvariantCulture, $"模組「{modTitle}」偵測到 {plans.Count} 個必要相依模組規劃：");

        AppendPlanSection(sb, "【全新安裝】", plans.Where(static p => p.Action == ModInstallAction.Install),
            static p => $"• {p.TargetVersion.DisplayName} ({p.TargetVersion.PrimaryFile?.FileName})");
        AppendPlanSection(sb, "【更新升級】", plans.Where(static p => p.Action == ModInstallAction.Update),
            static p => $"• {p.TargetVersion.DisplayName} ({p.ExistingLocalMod?.Version} ➔ {p.TargetVersion.VersionNumber})");

        sb.AppendLine("\n是否將這些相依模組一併加入安裝清單？");
        return sb.ToString();
    }

    private static void AppendPlanSection(
        StringBuilder sb,
        string header,
        IEnumerable<ModDependencyPlanItem> items,
        Func<ModDependencyPlanItem, string> format)
    {
        bool first = true;
        foreach (var item in items)
        {
            if (first)
            {
                sb.AppendLine().AppendLine(header);
                first = false;
            }

            sb.AppendLine(format(item));
        }
    }

    [RelayCommand(CanExecute = nameof(CanModifyQueue))]
    public async Task InstallQueuedModsAsync(CancellationToken cancellationToken = default)
    {
        if (IsInstalling)
        {
            return;
        }

        if (InstallQueue.Count == 0)
        {
            _ui.Notify("安裝清單目前沒有項目", NotificationType.Warning);
            return;
        }

        if (!_context.TryRequireServer(_ui, out var server))
        {
            return;
        }

        if (!EnsureServerStopped(server, "安裝"))
        {
            return;
        }

        var pending = ModBatchOperations.ExcludeUnofficialSources(_ui, _modFileService, InstallQueue, static u => u.Title, static u => u.DownloadUrl, "待安裝模組");
        if (pending.Count == 0)
        {
            return;
        }

        IsInstalling = true;
        try
        {
            var (succeededItems, failures) = await ExecuteStagedDownloadsAsync(
                server.Path,
                pending,
                static item => new ModDownloadTask
                {
                    DisplayName = item.Title,
                    DownloadUrl = item.DownloadUrl,
                    FileName = item.FileName,
                    ExpectedHash = item.ExpectedHash,
                    HashAlgorithm = item.HashAlgorithm,
                    OldFileName = item.Action == ModInstallAction.Update ? item.OldFileName : null,
                    PreserveDisabledState = item.PreserveDisabledState || (item.OldFileName is { } oldFileName && ModHelpers.IsDisabledModFileName(oldFileName))
                },
                "正在安裝模組",
                "安裝",
                Logger,
                cancellationToken);

            InstallQueue.RemoveRange(succeededItems);

            Logger.Information("批次安裝完成，成功 {Success} / {Total}", succeededItems.Count, pending.Count);
            await _context.NotifyModsChangedAsync();
            ModBatchOperations.NotifySummary(_ui, "安裝", succeededItems.Count, failures);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Error(ex, "批次安裝模組發生例外");
            _ui.Notify($"安裝模組失敗：{ex.Message}", NotificationType.Error);
        }
        finally
        {
            IsInstalling = false;
            UpdateInstallQueueHint();
        }
    }

    /// <summary>檢視待安裝佇列清單視窗</summary>
    [RelayCommand]
    public async Task ViewInstallQueueAsync()
    {
        using var reviewVm = new ModInstallQueueReviewViewModel(InstallQueue);
        bool? confirmed = await _ui.ShowModInstallQueueAsync(reviewVm);
        UpdateInstallQueueHint();

        if (confirmed == true && InstallQueue.Count > 0 && !IsInstalling)
        {
            _ = RunSafeAsync(() => InstallQueuedModsAsync(), "安裝佇列模組", Logger);
        }
    }

    /// <summary>清空安裝清單</summary>
    [RelayCommand(CanExecute = nameof(CanModifyQueue))]
    public void ClearInstallQueue()
    {
        InstallQueue.Clear();
        UpdateInstallQueueHint();
    }

    /// <summary>依佇列內容更新提示文字</summary>
    public void UpdateInstallQueueHint()
    {
        if (InstallQueue.Count == 0)
        {
            InstallQueueHint = EmptyQueueHint;
            return;
        }

        int installs = InstallQueue.Count(static i => i.Action == ModInstallAction.Install);
        int updates = InstallQueue.Count(static i => i.Action == ModInstallAction.Update);

        InstallQueueHint = updates > 0
            ? $"安裝清單：{installs} 個新增，{updates} 個更新"
            : $"安裝清單：{installs} 個項目待安裝";
    }

    private void OnServerChanged()
    {
        if (IsInstalling)
        {
            return;
        }

        ClearInstallQueue();
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        _context.ServerChanged -= OnServerChanged;
    }
}
