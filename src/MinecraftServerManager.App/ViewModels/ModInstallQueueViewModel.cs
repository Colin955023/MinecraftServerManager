using System.Collections.Concurrent;
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

/// <summary>
/// 待安裝模組佇列項目
/// </summary>
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

    public string HashAlgorithm { get; set; } = "sha512";

    public IReadOnlyList<string> Dependencies { get; set; } = (string[])[];

    public ModInstallAction Action { get; set; } = ModInstallAction.Install;

    public string ActionText => Action == ModInstallAction.Update ? "更新" : "安裝";

    public string VersionDisplay => Action == ModInstallAction.Update && !string.IsNullOrWhiteSpace(CurrentVersion)
        ? $"{CurrentVersion} ➔ {VersionNumber}"
        : VersionNumber;

    public string Reason { get; set; } = "全新安裝";
}

/// <summary>
/// 模組頁：版本挑選、安裝佇列、相依解析與批次安裝
/// </summary>
public sealed partial class ModInstallQueueViewModel : ViewModelBase
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ModInstallQueueViewModel));

    private readonly IUiService _ui;
    private readonly ModsContext _context;
    private readonly IModManager _modManager;
    private readonly IModrinthClient _modrinthClient;
    private readonly IModDependencyPlanner _dependencyPlanner;
    private readonly IModFileService _modFileService;

    [ObservableProperty]
    public partial string InstallQueueHint { get; set; } = "安裝清單：0 個項目";

    /// <summary>
    /// 待安裝模組佇列。
    /// </summary>
    public BulkObservableCollection<ModInstallQueueItem> InstallQueue { get; } = [];

    public ModInstallQueueViewModel(
        ModsContext context,
        IModDependencyPlanner dependencyPlanner,
        IModFileService modFileService,
        IUiService uiService,
        IModManager modManager,
        IModrinthClient modrinthClient)
    {
        ArgumentNullException.ThrowIfNull(context);
        ArgumentNullException.ThrowIfNull(dependencyPlanner);
        ArgumentNullException.ThrowIfNull(modFileService);
        ArgumentNullException.ThrowIfNull(uiService);
        ArgumentNullException.ThrowIfNull(modManager);
        ArgumentNullException.ThrowIfNull(modrinthClient);

        _ui = uiService;
        _context = context;
        _dependencyPlanner = dependencyPlanner;
        _modFileService = modFileService;
        _modManager = modManager;
        _modrinthClient = modrinthClient;
    }

    /// <summary>
    /// 彈出版本選擇對話方塊，將選定版本與必要相依模組加入安裝清單
    /// </summary>
    public async Task PickVersionAndQueueAsync(OnlineModRowItem? mod)
    {
        if (mod is null)
        {
            return;
        }

        // 偵測伺服器端環境相容性，防範純用戶端模組造成伺服器當機
        if (string.Equals(mod.ServerSide, "unsupported", StringComparison.OrdinalIgnoreCase)
            && !await _ui.ConfirmAsync(
                $"模組「{mod.Title}」在 Modrinth 標記為純用戶端模組 (server_side: unsupported)，在伺服器端執行可能引發當機！\n\n是否仍要強行挑選版本並加入安裝清單？",
                "伺服器端環境不相容警告",
                UiMessageLevel.Warning).ConfigureAwait(true))
        {
            return;
        }

        ServerConfig? server = _context.Server;
        var pickerVm = new ModVersionPickerViewModel(
            _modrinthClient,
            mod.Id,
            mod.Title,
            _context.LoaderId,
            _context.MinecraftVersion);

        if (await _ui.ShowModVersionPickerAsync(pickerVm).ConfigureAwait(true) != true || pickerVm.QueuedVersion is not { } chosen)
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
            await QueueMissingDependenciesAsync(mod.Title, chosen.Dependencies, server).ConfigureAwait(true);
        }

        UpdateInstallQueueHint();

        if (pickerVm.InstallImmediately)
        {
            await InstallQueuedModsAsync().ConfigureAwait(true);
        }
    }

    private bool ContainsFile(string? fileName) =>
        InstallQueue.Any(q => string.Equals(q.FileName, fileName, StringComparison.OrdinalIgnoreCase));

    private async Task QueueMissingDependenciesAsync(string modTitle, IReadOnlyList<string> dependencyIds, ServerConfig server)
    {
        try
        {
            var installed = await _modManager.GetModsAsync(server.Path).ConfigureAwait(true);
            var rawDeps = dependencyIds
                .Select(static d => new OnlineModDependency(d, ModDependencyType.Required))
                .ToList();

            var plans = await _dependencyPlanner.ResolveDependenciesRecursivelyAsync(
                _modrinthClient,
                rawDeps,
                server.MinecraftVersion.Value,
                server.LoaderType.ToString(),
                installed).ConfigureAwait(true);

            var toAdd = plans
                .Where(plan => plan.TargetVersion.PrimaryFile is { } pf && !ContainsFile(pf.Filename))
                .ToList();

            if (toAdd.Count == 0)
            {
                return;
            }

            if (!await _ui.ConfirmAsync(BuildDependencyPrompt(modTitle, toAdd), "發現必要相依模組").ConfigureAwait(true))
            {
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
                    FileName = pf.Filename,
                    OldFileName = plan.ExistingLocalMod?.Filename,
                    DownloadUrl = pf.Url,
                    ExpectedHash = ModHelpers.ResolveHash(pf, out string algo),
                    HashAlgorithm = algo,
                    Dependencies = (string[])[.. depVer.Dependencies
                        .Where(static d => d.DependencyType == ModDependencyType.Required)
                        .Select(static d => d.ProjectId ?? string.Empty)
                        .Where(static id => id.Length > 0)],
                    Action = plan.Action,
                    Reason = plan.Reason
                });
            }

            _ui.Notify($"已將 {toAdd.Count} 個相依模組加入安裝清單", NotificationType.Success);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "檢查相依模組時發生異常: {Message}", ex.Message);
        }
    }

    /// <summary>
    /// 組合相依模組規劃確認訊息（依全新安裝與更新升級分段）
    /// </summary>
    public static string BuildDependencyPrompt(string modTitle, IReadOnlyList<ModDependencyPlanItem> plans)
    {
        ArgumentNullException.ThrowIfNull(plans);
        var sb = new StringBuilder();
        sb.AppendLine(CultureInfo.InvariantCulture, $"模組「{modTitle}」偵測到 {plans.Count} 個必要相依模組規劃：");

        AppendPlanSection(sb, "【全新安裝】", plans.Where(static p => p.Action == ModInstallAction.Install),
            static p => $"• {p.TargetVersion.DisplayName} ({p.TargetVersion.PrimaryFile?.Filename})");
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

    [RelayCommand]
    public async Task InstallQueuedModsAsync(CancellationToken cancellationToken = default)
    {
        if (InstallQueue.Count == 0)
        {
            _ui.Notify("安裝清單目前沒有項目", NotificationType.Warning);
            return;
        }

        if (_context.Server is not { } server)
        {
            _ui.Notify("請先選擇伺服器", NotificationType.Warning);
            return;
        }

        var pending = InstallQueue.ToList();
        if (!await ModBatchOperations.ConfirmUnofficialSourcesAsync(_ui, _modFileService, pending, static u => u.Title, static u => u.DownloadUrl, "待安裝模組", "安裝"))
        {
            return;
        }

        using IOperationProgress installProgressDialog = _ui.ShowModOperationProgress("正在安裝模組", "準備下載模組檔案...");
        try
        {
            var succeededItems = await InstallItemsAsync(server.Path, pending, installProgressDialog, cancellationToken).ConfigureAwait(true);
            foreach (var item in succeededItems)
            {
                InstallQueue.Remove(item);
            }

            int success = succeededItems.Count;
            Logger.Information("批次安裝完成，成功 {Success} / {Total}", success, pending.Count);
            await _context.NotifyModsChangedAsync().ConfigureAwait(true);

            int failed = pending.Count - success;
            string summaryMsg = $"已成功安裝 {success} 個模組！" + (failed > 0 ? $"\n其中 {failed} 個模組安裝失敗，請檢查網路連線或記錄檔。" : string.Empty);
            _ui.Notify(summaryMsg, failed > 0 ? NotificationType.Warning : NotificationType.Success);
        }
        finally
        {
            UpdateInstallQueueHint();
            _modFileService.CleanupStagingDirectory(server.Path);
        }
    }

    private async Task<List<ModInstallQueueItem>> InstallItemsAsync(
        string serverPath,
        List<ModInstallQueueItem> pending,
        IOperationProgress progressDialog,
        CancellationToken cancellationToken)
    {
        IModManager modManager = _modManager;
        progressDialog.UpdateProgress(0, pending.Count, "已排入模組並行下載佇列...");

        var pendingTargetFileNames = pending
            .Select(static item => Path.GetFileName(item.FileName))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        var succeededItems = new ConcurrentBag<ModInstallQueueItem>();

        await ModBatchOperations.RunWithProgressAsync(pending, 3, progressDialog, "安裝模組", static item => item.Title, async (item, token) =>
        {
            try
            {
                var result = await modManager.InstallOnlineModAsync(
                    serverPath,
                    item.DownloadUrl,
                    item.FileName,
                    expectedHash: item.ExpectedHash,
                    hashAlgorithm: item.HashAlgorithm,
                    cancellationToken: token).ConfigureAwait(false);

                if (result?.Completed != true)
                {
                    string message = result?.Message ?? (token.IsCancellationRequested ? "已取消安裝" : "下載工作未回傳結果");
                    Logger.Warning("模組「{Title}」安裝失敗: {Message}", item.Title, message);
                    _ui.Notify($"模組「{item.Title}」安裝失敗：{message}", NotificationType.Error);
                    return;
                }

                if (item.Action == ModInstallAction.Update && !string.IsNullOrWhiteSpace(item.OldFileName) &&
                    !string.Equals(item.OldFileName, item.FileName, StringComparison.OrdinalIgnoreCase) &&
                    !pendingTargetFileNames.Contains(Path.GetFileName(item.OldFileName)))
                {
                    try
                    {
                        _modFileService.DeleteModFileVariants(serverPath, item.OldFileName);
                    }
                    catch (Exception ex) when (ex is not OperationCanceledException)
                    {
                        Logger.Warning("刪除舊版本模組檔案「{Old}」失敗: {Message}", item.OldFileName, ex.Message);
                    }
                }

                succeededItems.Add(item);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Error(ex, "安裝模組「{Title}」異常: {Message}", item.Title, ex.Message);
                _ui.Notify($"安裝「{item.Title}」異常：{ex.Message}", NotificationType.Error);
            }
        }, cancellationToken).ConfigureAwait(true);

        return [.. succeededItems];
    }

    /// <summary>
    /// 檢視待安裝佇列清單視窗
    /// </summary>
    [RelayCommand]
    public async Task ViewInstallQueueAsync()
    {
        bool? confirmed = await _ui.ShowModInstallQueueAsync(InstallQueue);
        UpdateInstallQueueHint();

        if (confirmed == true && InstallQueue.Count > 0)
        {
            _ = RunSafeAsync(() => InstallQueuedModsAsync(), "安裝佇列模組", Logger);
        }
    }

    /// <summary>
    /// 清空安裝清單。
    /// </summary>
    [RelayCommand]
    public void ClearInstallQueue()
    {
        InstallQueue.Clear();
        UpdateInstallQueueHint();
    }

    /// <summary>
    /// 依佇列內容更新提示文字
    /// </summary>
    public void UpdateInstallQueueHint()
    {
        if (InstallQueue.Count == 0)
        {
            InstallQueueHint = "安裝佇列為空";
            return;
        }

        int installs = InstallQueue.Count(static i => i.Action == ModInstallAction.Install);
        int updates = InstallQueue.Count(static i => i.Action == ModInstallAction.Update);

        InstallQueueHint = updates > 0
            ? $"安裝清單：{installs} 個新增，{updates} 個更新"
            : $"安裝清單：{installs} 個項目待安裝";
    }
}
