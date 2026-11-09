using System.Collections.Concurrent;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 模組頁：雜湊比對、更新候選篩選與批次更新
/// </summary>
public sealed partial class ModUpdateViewModel : ViewModelBase
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ModUpdateViewModel));
    private static readonly string[] HashAlgorithms = ["sha512", "sha1"];

    private readonly IUiService _ui;
    private readonly ModsContext _context;
    private readonly IModManager _modManager;
    private readonly IModrinthClient _modrinthClient;
    private readonly IModDependencyPlanner _dependencyPlanner;
    private readonly IModFileService _modFileService;

    public ModUpdateViewModel(
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
    /// 檢查指定本地模組之相容更新，經使用者確認後批次更新
    /// </summary>
    public async Task CheckModUpdatesAsync(IReadOnlyList<LocalModRowItem> targets)
    {
        ArgumentNullException.ThrowIfNull(targets);
        if (targets.Count == 0)
        {
            _ui.Notify("請先選取要檢查更新的模組", NotificationType.Warning);
            return;
        }

        if (_context.Server is not { } server)
        {
            _ui.Notify("請先選擇伺服器以檢查更新", NotificationType.Warning);
            return;
        }

        Logger.Information("開始檢查已選取模組更新，共 {Count} 個模組（預設優先使用 Modrinth）", targets.Count);

        string loader = _context.LoaderId ?? string.Empty;
        string mcVer = server.MinecraftVersion.Value;
        IReadOnlyList<LocalModInfo> installedMods = await _modManager.GetModsAsync(server.Path).ConfigureAwait(true);

        IOperationProgress progressDialog = _ui.ShowModOperationProgress("檢查模組更新中", "正在大量比對檔案雜湊...");
        List<ModUpdateCandidateItem> sortedCandidates = [];
        string? failure = null;
        try
        {
            progressDialog.UpdateProgress(0, targets.Count, $"正在向 Modrinth 批次查詢 {targets.Count} 個模組雜湊資訊...");
            var projectMapByHash = await LookupProjectIdsByHashAsync(_modrinthClient, targets).ConfigureAwait(true);

            var candidates = new ConcurrentBag<ModUpdateCandidateItem>();
            progressDialog.UpdateProgress(0, targets.Count, "正在平行查詢相容版本清單...");

            IModrinthClient modrinthClient = _modrinthClient;
            await ModBatchOperations.RunWithProgressAsync(targets, 4, progressDialog, "檢查", static mod => mod.Name, async (mod, token) =>
            {
                try
                {
                    var versions = await FindProjectVersionsAsync(modrinthClient, mod, projectMapByHash, loader, mcVer, token).ConfigureAwait(false);
                    if (BuildCandidate(mod, versions, mcVer, loader, installedMods) is { } candidate)
                    {
                        candidates.Add(candidate);
                    }
                }
                catch (Exception ex) when (ex is not OperationCanceledException)
                {
                    Logger.Warning("檢查模組「{Name}」更新失敗: {Error}", mod.Name, ex.Message);
                }
            }).ConfigureAwait(true);

            sortedCandidates = [.. candidates.OrderBy(static c => c.ModName, StringComparer.Ordinal)];
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            // 雜湊批次查詢等網路失敗須告知使用者，不可落入全域未處理例外
            Logger.Error(ex, "檢查模組更新失敗: {Message}", ex.Message);
            failure = ex.Message;
        }
        finally
        {
            progressDialog.Dispose();
        }

        if (failure is not null)
        {
            await _ui.ShowErrorAsync($"檢查模組更新失敗：\n{failure}", "檢查更新失敗");
            return;
        }

        if (sortedCandidates.Count == 0)
        {
            _ui.Notify($"檢查完成，選取的 {targets.Count} 個模組皆為相容最新版本", NotificationType.Info);
            return;
        }

        if (await _ui.ShowModUpdatesAsync(sortedCandidates) is { Count: > 0 } toUpdate)
        {
            await PerformModUpdatesAsync(server.Path, toUpdate).ConfigureAwait(true);
            await _context.NotifyModsChangedAsync().ConfigureAwait(true);
            _ui.Notify($"已成功更新 {toUpdate.Count} 個模組！", NotificationType.Success);
        }
    }

    /// <summary>
    /// 階段 1：以批量雜湊請求反查官方 ProjectId
    /// </summary>
    private static async Task<Dictionary<string, string>> LookupProjectIdsByHashAsync(IModrinthClient client, IReadOnlyList<LocalModRowItem> targets)
    {
        var projectMapByHash = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (string algorithm in HashAlgorithms)
        {
            var hashes = targets
                .Where(m => !string.IsNullOrWhiteSpace(m.CurrentHash) && string.Equals(m.HashAlgorithm, algorithm, StringComparison.OrdinalIgnoreCase))
                .Select(static m => m.CurrentHash)
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToList();
            if (hashes.Count == 0)
            {
                continue;
            }

            try
            {
                var lookupResults = await client.LookupVersionsByHashesAsync(hashes, algorithm).ConfigureAwait(true);
                foreach (var (hash, result) in lookupResults)
                {
                    if (!string.IsNullOrWhiteSpace(result?.ProjectId))
                    {
                        projectMapByHash[hash] = result.ProjectId;
                    }
                }
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                Logger.Warning("批次查詢 {Algorithm} 雜湊失敗: {Error}", algorithm, ex.Message);
            }
        }

        return projectMapByHash;
    }

    /// <summary>
    /// 階段 2：依雜湊反查 ProjectId、模組 Id、名稱搜尋的順序取得相容版本清單
    /// </summary>
    private static async Task<IReadOnlyList<OnlineModVersion>> FindProjectVersionsAsync(
        IModrinthClient client,
        LocalModRowItem mod,
        Dictionary<string, string> projectMapByHash,
        string loader,
        string mcVer,
        CancellationToken token)
    {
        IReadOnlyList<OnlineModVersion> versions = [];
        if (!string.IsNullOrWhiteSpace(mod.CurrentHash) && projectMapByHash.TryGetValue(mod.CurrentHash, out string? projectId))
        {
            versions = await client.GetProjectVersionsAsync(projectId, loader: loader, minecraftVersion: mcVer, cancellationToken: token).ConfigureAwait(false);
        }

        if (versions.Count == 0 && !string.IsNullOrWhiteSpace(mod.Id))
        {
            versions = await client.GetProjectVersionsAsync(mod.Id, loader: loader, minecraftVersion: mcVer, cancellationToken: token).ConfigureAwait(false);
        }

        if (versions.Count == 0 && !string.IsNullOrWhiteSpace(mod.Name))
        {
            var search = await client.SearchModsAsync(mod.Name, loader: loader, minecraftVersion: mcVer, cancellationToken: token).ConfigureAwait(false);
            var matched = search.FirstOrDefault(p => string.Equals(p.Name, mod.Name, StringComparison.OrdinalIgnoreCase) || string.Equals(p.Slug, mod.Id, StringComparison.OrdinalIgnoreCase));
            if (matched is not null)
            {
                versions = await client.GetProjectVersionsAsync(matched.ProjectId, loader: loader, minecraftVersion: mcVer, cancellationToken: token).ConfigureAwait(false);
            }
        }

        return versions;
    }

    /// <summary>
    /// 篩選相容且版本較新、雜湊不同之最新版本，建立更新候選；無可用更新時回傳 null
    /// </summary>
    private ModUpdateCandidateItem? BuildCandidate(
        LocalModRowItem mod,
        IReadOnlyList<OnlineModVersion> versions,
        string mcVer,
        string loader,
        IReadOnlyList<LocalModInfo> installedMods)
    {
        OnlineModVersion? compatibleLatest = null;
        foreach (var ver in versions)
        {
            if (string.IsNullOrWhiteSpace(ver.VersionNumber) || string.IsNullOrWhiteSpace(ver.PrimaryFile?.Url))
            {
                continue;
            }

            // 排除硬性不相容與衝突版本
            var report = _dependencyPlanner.EvaluateCompatibility(ver, mcVer, loader, installedMods);
            if (report.IsCompatible &&
                (compatibleLatest is null || FlexVersion.Compare(ver.VersionNumber, compatibleLatest.VersionNumber) > 0))
            {
                compatibleLatest = ver;
            }
        }

        if (compatibleLatest?.PrimaryFile is not { } primaryFile)
        {
            return null;
        }

        // 雜湊相符代表已是同一檔案；僅在版本較新且雜湊不同時判定有更新，杜絕降級與虛假更新
        bool hashMatches = !string.IsNullOrWhiteSpace(mod.CurrentHash) &&
            primaryFile.Hashes is not null &&
            ((primaryFile.Hashes.TryGetValue("sha512", out string? sha512) && string.Equals(mod.CurrentHash, sha512, StringComparison.OrdinalIgnoreCase)) ||
             (primaryFile.Hashes.TryGetValue("sha1", out string? sha1) && string.Equals(mod.CurrentHash, sha1, StringComparison.OrdinalIgnoreCase)));
        if (hashMatches || FlexVersion.Compare(compatibleLatest.VersionNumber, mod.Version) <= 0)
        {
            return null;
        }

        string? expectedHash = ModHelpers.ResolveHash(primaryFile, out string resolvedAlgo);
        return new ModUpdateCandidateItem
        {
            ModName = mod.Name,
            CurrentVersion = mod.Version,
            NewVersion = compatibleLatest.VersionNumber,
            FileName = !string.IsNullOrWhiteSpace(primaryFile.Filename) ? primaryFile.Filename : $"{mod.Name}-{compatibleLatest.VersionNumber}.jar",
            DownloadUrl = primaryFile.Url,
            ExpectedHash = expectedHash,
            HashAlgorithm = expectedHash is not null ? resolvedAlgo : null,
            LocalMod = mod,
        };
    }

    private async Task PerformModUpdatesAsync(string serverPath, IReadOnlyList<ModUpdateCandidateItem> items)
    {
        if (items.Count == 0)
        {
            return;
        }

        if (!await ModBatchOperations.ConfirmUnofficialSourcesAsync(_ui, _modFileService, items, static u => u.ModName, static u => u.DownloadUrl, "模組更新", "更新"))
        {
            return;
        }

        using IOperationProgress updateProgressDialog = _ui.ShowModOperationProgress("正在更新模組", "準備下載新版本...");
        try
        {
            IModManager modManager = _modManager;
            updateProgressDialog.UpdateProgress(0, items.Count, "已啟動模組並行下載更新佇列...");

            await ModBatchOperations.RunWithProgressAsync(items, 3, updateProgressDialog, "更新模組", static item => item.ModName, async (item, token) =>
            {
                try
                {
                    await UpdateSingleModAsync(modManager, serverPath, item, token).ConfigureAwait(false);
                }
                catch (Exception ex) when (ex is not OperationCanceledException)
                {
                    Logger.Error(ex, "更新模組「{Name}」異常: {Message}", item.ModName, ex.Message);
                }
            }).ConfigureAwait(true);
        }
        finally
        {
            _modFileService.CleanupStagingDirectory(serverPath);
        }
    }

    private static async Task UpdateSingleModAsync(IModManager modManager, string serverPath, ModUpdateCandidateItem item, CancellationToken token)
    {
        var installResult = await modManager.InstallOnlineModAsync(
            serverPath,
            item.DownloadUrl,
            item.FileName,
            item.ExpectedHash,
            item.HashAlgorithm,
            cancellationToken: token).ConfigureAwait(false);

        if (installResult?.Completed != true || item.LocalMod is null)
        {
            Logger.Warning("更新模組「{Name}」失敗: {Error}", item.ModName, installResult?.Message ?? "未知錯誤");
            return;
        }

        if (!item.LocalMod.IsEnabled)
        {
            await modManager.SetModStateAsync(serverPath, item.FileName, false, token).ConfigureAwait(false);
        }

        if (!string.Equals(item.LocalMod.FileName, item.FileName, StringComparison.OrdinalIgnoreCase))
        {
            string oldTarget = !string.IsNullOrEmpty(item.LocalMod.FileName) ? item.LocalMod.FileName : item.LocalMod.Id;
            await modManager.DeleteModsAsync(serverPath, (string[])[oldTarget], cancellationToken: token).ConfigureAwait(false);
        }

        Logger.Information("成功更新模組「{Name}」至版本 {Version}", item.ModName, item.NewVersion);
    }
}
