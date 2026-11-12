using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>模組安裝佇列與更新流程子 ViewModel 之共用相依基底</summary>
public abstract class ModQueueWorkflowViewModelBase : ViewModelBase
{
    private protected readonly IUiService _ui;
    private protected readonly ModsContext _context;
    private protected readonly IModManager _modManager;
    private protected readonly IModrinthClient _modrinthClient;
    private protected readonly IModDependencyPlanner _dependencyPlanner;
    private protected readonly IModFileService _modFileService;

    private protected ModQueueWorkflowViewModelBase(
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
}

/// <summary>模組批次作業共用流程：非官方下載來源確認與有限平行度進度回報</summary>
internal static class ModBatchOperations
{
    /// <summary>下載來源含非官方 Modrinth CDN 時要求使用者確認；全部為官方來源或使用者同意時回傳 true</summary>
    public static Task<bool> ConfirmUnofficialSourcesAsync<T>(
        IUiService ui,
        IModFileService modFileService,
        IEnumerable<T> items,
        Func<T, string> name,
        Func<T, string> downloadUrl,
        string subject,
        string action)
    {
        var unofficial = items.Where(item => !modFileService.IsOfficialModrinthSource(downloadUrl(item))).ToList();
        if (unofficial.Count == 0)
        {
            return Task.FromResult(true);
        }

        string message = $"下列{subject}下載來源非官方 Modrinth CDN：\n" +
                         string.Join("\n", unofficial.Select(item => $"• {name(item)}: {downloadUrl(item)}")) +
                         $"\n\n非官方來源可能存在安全風險，是否仍要繼續下載並{action}？";
        return ui.ConfirmAsync(message, "非官方下載來源警告", UiMessageLevel.Warning);
    }

    /// <summary>以有限平行度執行批次工作並逐項回報進度；單項例外由 <paramref name="body"/> 自行處理，不中斷其餘項目</summary>
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
                progress.UpdateProgress(done, items.Count, $"正在{verb} ({done}/{items.Count}): {name(item)}...");
            }
        });
    }
}
