using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>模組下載與安裝作業工作描述</summary>
public sealed class ModDownloadTask
{
    public required string DisplayName { get; init; }
    public required string DownloadUrl { get; init; }
    public required string FileName { get; init; }
    public string? ExpectedHash { get; init; }
    public string? HashAlgorithm { get; init; }
    public string? OldFileName { get; init; }
    public bool PreserveDisabledState { get; init; }
}

/// <summary>模組安裝佇列與更新流程子 ViewModel 之共用相依基底</summary>
public abstract class ModQueueWorkflowViewModelBase : ViewModelBase
{
    private protected readonly IUiService _ui;
    private protected readonly ModsContext _context;
    private protected readonly IModManager _modManager;
    private protected readonly IModrinthClient _modrinthClient;
    private protected readonly IModDependencyPlanner _dependencyPlanner;
    private protected readonly IModFileService _modFileService;
    private readonly IServerRuntimeHost _runtimeHost;

    private protected ModQueueWorkflowViewModelBase(
        ModsContext context,
        IModDependencyPlanner dependencyPlanner,
        IModFileService modFileService,
        IUiService uiService,
        IModManager modManager,
        IModrinthClient modrinthClient,
        IServerRuntimeHost runtimeHost)
    {
        ArgumentNullException.ThrowIfNull(context);
        ArgumentNullException.ThrowIfNull(dependencyPlanner);
        ArgumentNullException.ThrowIfNull(modFileService);
        ArgumentNullException.ThrowIfNull(uiService);
        ArgumentNullException.ThrowIfNull(modManager);
        ArgumentNullException.ThrowIfNull(modrinthClient);
        ArgumentNullException.ThrowIfNull(runtimeHost);

        _ui = uiService;
        _runtimeHost = runtimeHost;
        _context = context;
        _dependencyPlanner = dependencyPlanner;
        _modFileService = modFileService;
        _modManager = modManager;
        _modrinthClient = modrinthClient;
    }

    /// <summary>伺服器執行中時提示先停止並回傳 false（執行中替換模組檔案會失敗或不生效）</summary>
    private protected bool EnsureServerStopped(ServerConfig server, string action) =>
        _ui.EnsureServerStopped(_runtimeHost, server.Name.Value, $"{action}模組");

    /// <summary>單筆下載、保留停用狀態與舊檔刪除</summary>
    private protected async Task<string?> DownloadAndReplaceSingleModAsync(
        string serverPath,
        ModDownloadTask task,
        IReadOnlySet<string> pendingTargetFileNames,
        ComponentLogger logger,
        CancellationToken cancellationToken)
    {
        var result = await _modManager.InstallOnlineModAsync(
            serverPath,
            task.DownloadUrl,
            task.FileName,
            expectedHash: task.ExpectedHash,
            hashAlgorithm: task.HashAlgorithm,
            cancellationToken: cancellationToken).ConfigureAwait(false);

        if (result?.Completed != true)
        {
            string error = result?.Message ?? (cancellationToken.IsCancellationRequested ? "已取消操作" : "下載工作未回傳結果");
            logger.Warning("模組「{Name}」下載或安裝失敗：{Error}", task.DisplayName, error);
            return error;
        }

        if (task.PreserveDisabledState)
        {
            await _modManager.SetModStateAsync(serverPath, task.FileName, false, cancellationToken).ConfigureAwait(false);
        }

        if (!string.IsNullOrWhiteSpace(task.OldFileName))
        {
            await ModBatchOperations.TryDeleteObsoleteModFileAsync(
                _modFileService,
                serverPath,
                task.OldFileName,
                task.FileName,
                pendingTargetFileNames,
                logger,
                cancellationToken).ConfigureAwait(false);
        }

        logger.Information("模組「{Name}」處理成功（檔名：{FileName}）", task.DisplayName, task.FileName);
        return null;
    }

    /// <summary>共用的分階段下載管線：進度對話方塊、平行下載替換、清理暫存、通知變更與摘要</summary>
    private protected async Task<(List<TItem> Succeeded, List<string> Failures)> ExecuteStagedDownloadsAsync<TItem>(
        string serverPath,
        IReadOnlyList<TItem> items,
        Func<TItem, ModDownloadTask> taskSelector,
        string dialogTitle,
        string verb,
        ComponentLogger logger,
        CancellationToken cancellationToken = default)
    {
        var tasks = items.Select(taskSelector).ToList();
        var pendingTargetFileNames = ModBatchOperations.CollectTargetFileNames(tasks, static t => t.FileName);
        var succeeded = new System.Collections.Concurrent.ConcurrentBag<TItem>();
        var failures = new System.Collections.Concurrent.ConcurrentBag<string>();

        using (IOperationProgress progress = _ui.ShowOperationProgress(dialogTitle, $"準備{verb}模組檔案..."))
        {
            progress.UpdateProgress(0, tasks.Count, $"已排入模組並行下載佇列...");
            await ModBatchOperations.RunWithProgressAsync(
                items,
                3,
                progress,
                $"{verb}模組",
                item => taskSelector(item).DisplayName,
                async (item, token) =>
                {
                    var task = taskSelector(item);
                    try
                    {
                        string? error = await DownloadAndReplaceSingleModAsync(serverPath, task, pendingTargetFileNames, logger, token).ConfigureAwait(false);
                        if (error is not null)
                        {
                            failures.Add($"{task.DisplayName}：{error}");
                        }
                        else
                        {
                            succeeded.Add(item);
                        }
                    }
                    catch (Exception ex) when (ex is not OperationCanceledException)
                    {
                        logger.Error(ex, "{Verb}模組「{Name}」失敗", verb, task.DisplayName);
                        failures.Add($"{task.DisplayName}：{ex.Message}");
                    }
                },
                cancellationToken).ConfigureAwait(false);
        }

        try
        {
            await _modFileService.CleanupStagingDirectoryAsync(serverPath, CancellationToken.None).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            logger.Warning(ex, "清理暫存目錄失敗");
        }

        return (succeeded.ToList(), failures.ToList());
    }
}

/// <summary>模組批次作業共用流程：非官方來源過濾、有限平行度進度回報與結果摘要</summary>
internal static class ModBatchOperations
{
    /// <summary>擷取線上模組版本的必要相依識別碼（排除選用、內嵌與不相容項目）</summary>
    public static string[] GetRequiredDependencyIds(OnlineModVersion version)
    {
        ArgumentNullException.ThrowIfNull(version);
        return [.. version.Dependencies
            .Where(static d => d.DependencyType == ModDependencyType.Required)
            .Select(static d => d.ProjectId ?? string.Empty)
            .Where(static id => id.Length > 0)];
    }

    /// <summary>排除非官方 Modrinth CDN 來源（與底層安裝器策略一致）並警告；回傳可下載項目</summary>
    public static List<T> ExcludeUnofficialSources<T>(
        IUiService ui,
        IModFileService modFileService,
        IEnumerable<T> items,
        Func<T, string> name,
        Func<T, string> downloadUrl,
        string subject)
    {
        List<T> allowed = [];
        List<T> blocked = [];
        foreach (var item in items)
        {
            (modFileService.IsOfficialModrinthSource(downloadUrl(item)) ? allowed : blocked).Add(item);
        }

        if (blocked.Count > 0)
        {
            ui.Notify(
                $"下列{subject}下載來源非官方 Modrinth CDN，基於安全考量已略過：\n" +
                string.Join("\n", blocked.Select(item => $"• {name(item)}：{downloadUrl(item)}")),
                NotificationType.Warning);
        }

        return allowed;
    }

    /// <summary>以單一通知彙整批次結果；有失敗時列出各項原因</summary>
    public static void NotifySummary(IUiService ui, string verb, int succeeded, IReadOnlyCollection<string> failures)
    {
        if (failures.Count == 0)
        {
            ui.Notify($"已成功{verb} {succeeded} 個模組！", NotificationType.Success);
            return;
        }

        if (succeeded == 0)
        {
            ui.Notify(
                $"{verb}模組失敗（共 {failures.Count} 個）：\n" + string.Join("\n", failures.Select(static f => $"• {f}")),
                NotificationType.Error);
            return;
        }

        ui.Notify(
            $"已成功{verb} {succeeded} 個模組，{failures.Count} 個失敗：\n" + string.Join("\n", failures.Select(static f => $"• {f}")),
            NotificationType.Warning);
    }

    /// <summary>收集批次目標檔名（僅檔名、不分大小寫），供刪除舊檔前防呆比對</summary>
    public static HashSet<string> CollectTargetFileNames<T>(IEnumerable<T> items, Func<T, string> fileNameSelector) =>
        items.Select(item => Path.GetFileName(fileNameSelector(item)))
            .Where(static name => !string.IsNullOrWhiteSpace(name))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);

    /// <summary>安全刪除已由新檔取代的舊版本模組檔案；同批目標檔名衝突時略過，失敗僅記錄警告</summary>
    public static async Task TryDeleteObsoleteModFileAsync(
        IModFileService modFileService,
        string serverPath,
        string? oldFileName,
        string newFileName,
        IReadOnlySet<string> pendingTargetFileNames,
        ComponentLogger logger,
        CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(oldFileName) ||
            string.Equals(oldFileName, newFileName, StringComparison.OrdinalIgnoreCase) ||
            pendingTargetFileNames.Contains(Path.GetFileName(oldFileName)))
        {
            return;
        }

        try
        {
            await modFileService.DeleteModFileVariantsAsync(serverPath, oldFileName, cancellationToken).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            logger.Warning(ex, "刪除舊版本模組檔案「{Old}」失敗", oldFileName);
        }
    }

    /// <summary>以有限平行度執行批次工作並回報進度</summary>
    public static Task RunWithProgressAsync<T>(
        IReadOnlyList<T> items,
        int maxParallelism,
        IOperationProgress progress,
        string verb,
        Func<T, string> name,
        Func<T, CancellationToken, ValueTask> body,
        CancellationToken cancellationToken = default)
    {
        int completed = 0;
        return Parallel.ForEachAsync(items, new ParallelOptions { MaxDegreeOfParallelism = maxParallelism, CancellationToken = cancellationToken }, async (item, token) =>
        {
            try
            {
                await body(item, token).ConfigureAwait(false);
            }
            finally
            {
                int done = Interlocked.Increment(ref completed);
                progress.UpdateProgress(done, items.Count, $"正在{verb}（{done}/{items.Count}）：{name(item)}...");
            }
        });
    }
}
