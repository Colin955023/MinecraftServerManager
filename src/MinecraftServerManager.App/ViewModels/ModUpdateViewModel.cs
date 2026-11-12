using System.Collections.Concurrent;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>模組頁：雜湊比對、更新候選篩選與批次更新</summary>
public sealed partial class ModUpdateViewModel(
    ModsContext context,
    IModDependencyPlanner dependencyPlanner,
    IModFileService modFileService,
    IUiService uiService,
    IModManager modManager,
    IModrinthClient modrinthClient)
    : ModQueueWorkflowViewModelBase(context, dependencyPlanner, modFileService, uiService, modManager, modrinthClient)
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ModUpdateViewModel));
    private static readonly string[] HashAlgorithms = ["sha512", "sha1"];

    /// <summary>檢查指定本地模組之相容更新，經使用者確認後批次更新</summary>
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
        List<string> blocked = [];
        string? failure = null;
        try
        {
            progressDialog.UpdateProgress(0, targets.Count, $"正在向 Modrinth 批次查詢 {targets.Count} 個模組雜湊資訊...");
            // 本機掃描不含平台專案識別碼，而相依資訊以 Modrinth 專案識別碼表示；
            // 先以雜湊反查所有已安裝模組的專案識別碼，才能正確判定相依是否已安裝（同 Prism Launcher）
            List<(string Hash, string Algorithm)> hashedFiles =
            [
                .. installedMods.Select(static m => (m.CurrentHash, m.HashAlgorithm)),
                .. targets.Select(static m => (m.CurrentHash, m.HashAlgorithm)),
            ];
            var projectMapByHash = await LookupProjectIdsByHashAsync(_modrinthClient, hashedFiles).ConfigureAwait(true);
            installedMods = installedMods.Select(m =>
                string.IsNullOrWhiteSpace(m.PlatformId) && !string.IsNullOrWhiteSpace(m.CurrentHash) && projectMapByHash.TryGetValue(m.CurrentHash, out string? projectId)
                    ? m.WithPlatformId(projectId)
                    : m).ToList();

            var proposals = new ConcurrentBag<UpdateProposal>();
            progressDialog.UpdateProgress(0, targets.Count, "正在平行查詢相容版本清單...");

            IModrinthClient modrinthClient = _modrinthClient;
            await ModBatchOperations.RunWithProgressAsync(targets, 4, progressDialog, "檢查", static mod => mod.Name, async (mod, token) =>
            {
                try
                {
                    var versions = await FindProjectVersionsAsync(modrinthClient, mod, projectMapByHash, loader, mcVer, token).ConfigureAwait(false);
                    if (BuildProposal(mod, versions, mcVer, loader, installedMods) is { } proposal)
                    {
                        proposals.Add(proposal);
                    }
                }
                catch (Exception ex) when (ex is not OperationCanceledException)
                {
                    Logger.Warning(ex, "檢查模組「{Name}」更新失敗", mod.Name);
                }
            }).ConfigureAwait(true);

            var ordered = proposals.OrderBy(static p => p.Candidate.ModName, StringComparer.Ordinal).ToList();
            sortedCandidates = await ResolveProposalsAsync(ordered, mcVer, loader, installedMods, blocked, progressDialog).ConfigureAwait(true);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            // 雜湊批次查詢等網路失敗須告知使用者，不可落入全域未處理例外
            Logger.Error(ex, "檢查模組更新失敗");
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

        if (blocked.Count > 0)
        {
            _ui.Notify($"以下模組因相容性或相依性問題無法更新：\n{string.Join('\n', blocked.Select(static b => $"．{b}"))}", NotificationType.Warning);
        }

        if (sortedCandidates.Count == 0)
        {
            if (blocked.Count == 0)
            {
                _ui.Notify($"檢查完成，選取的 {targets.Count} 個模組皆為相容最新版本", NotificationType.Info);
            }

            return;
        }

        if (await _ui.ShowModUpdatesAsync(sortedCandidates) is { Count: > 0 } toUpdate)
        {
            await PerformModUpdatesAsync(server.Path, toUpdate).ConfigureAwait(true);
            await _context.NotifyModsChangedAsync().ConfigureAwait(true);
            _ui.Notify($"已成功更新 {toUpdate.Count} 個模組！", NotificationType.Success);
        }
    }

    /// <summary>階段 1：以批次雜湊請求反查官方 ProjectId</summary>
    private static async Task<Dictionary<string, string>> LookupProjectIdsByHashAsync(IModrinthClient client, IReadOnlyList<(string Hash, string Algorithm)> files)
    {
        var projectMapByHash = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (string algorithm in HashAlgorithms)
        {
            var hashes = files
                .Where(f => !string.IsNullOrWhiteSpace(f.Hash) && string.Equals(f.Algorithm, algorithm, StringComparison.OrdinalIgnoreCase))
                .Select(static f => f.Hash)
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
                Logger.Warning(ex, "批次查詢 {Algorithm} 雜湊失敗", algorithm);
            }
        }

        return projectMapByHash;
    }

    /// <summary>階段 2：依雜湊反查 ProjectId、模組 Id、名稱搜尋的順序取得相容版本清單</summary>
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

    /// <summary>篩選相容且版本較新、雜湊不同之最新版本，建立更新候選；無可用更新時回傳 null</summary>
    private UpdateProposal? BuildProposal(
        LocalModRowItem mod,
        IReadOnlyList<OnlineModVersion> versions,
        string mcVer,
        string loader,
        IReadOnlyList<LocalModInfo> installedMods)
    {
        OnlineModVersion? compatibleLatest = null;
        OnlineModCompatibilityReport? latestReport = null;
        foreach (var ver in versions)
        {
            if (string.IsNullOrWhiteSpace(ver.VersionNumber) || string.IsNullOrWhiteSpace(ver.PrimaryFile?.Url))
            {
                continue;
            }

            // 僅排除環境不相容版本（伺服器端、載入器、Minecraft 版本）；缺少相依與衝突交由後續解析與回報
            var report = _dependencyPlanner.EvaluateCompatibility(ver, mcVer, loader, installedMods);
            if (!report.HasEnvironmentErrors &&
                (compatibleLatest is null || FlexVersion.Compare(ver.VersionNumber, compatibleLatest.VersionNumber) > 0))
            {
                compatibleLatest = ver;
                latestReport = report;
            }
        }

        if (compatibleLatest?.PrimaryFile is not { } primaryFile)
        {
            return null;
        }

        // 雜湊相符代表已是同一檔案；僅在版本較新且雜湊不同時判定有更新，杜絕降級與虛假更新
        if (ModHelpers.HashMatches(primaryFile, mod.CurrentHash) || FlexVersion.Compare(compatibleLatest.VersionNumber, mod.Version) <= 0)
        {
            return null;
        }

        string? expectedHash = ModHelpers.ResolveHash(primaryFile, out string resolvedAlgo);
        var candidate = new ModUpdateCandidateItem
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
        return new UpdateProposal(candidate, compatibleLatest, latestReport!);
    }

    /// <summary>
    /// 新版本與已安裝模組衝突者標記為無法更新；
    /// 缺少的必要相依模組（不論是否為遞迴相依）補入同一次更新清單，已安裝的相依一律視為已滿足而不升級；
    /// 找不到相容版本的必要相依則封鎖該候選並回報原因。
    /// </summary>
    private async Task<List<ModUpdateCandidateItem>> ResolveProposalsAsync(
        List<UpdateProposal> proposals,
        string mcVer,
        string loader,
        IReadOnlyList<LocalModInfo> installedMods,
        List<string> blocked,
        IOperationProgress progress)
    {
        List<ModUpdateCandidateItem> accepted = [];
        Dictionary<string, (ModDependencyPlanItem Plan, List<string> RequiredBy)> dependencies = new(StringComparer.OrdinalIgnoreCase);

        for (int i = 0; i < proposals.Count; i++)
        {
            var proposal = proposals[i];
            string name = proposal.Candidate.ModName;
            var report = proposal.Report;
            if (report.IncompatibleInstalled.Count > 0)
            {
                blocked.Add($"{name}：新版本與已安裝模組衝突（{string.Join("、", report.IncompatibleInstalled)}）");
                continue;
            }

            if (report.MissingRequiredDependencies.Count > 0)
            {
                progress.UpdateProgress(i, proposals.Count, $"正在解析「{name}」新版本所需的相依模組...");
                var plans = await _dependencyPlanner.ResolveDependenciesRecursivelyAsync(
                    _modrinthClient,
                    proposal.Version.Dependencies,
                    mcVer,
                    loader,
                    installedMods,
                    upgradeInstalled: false).ConfigureAwait(true);

                List<string> unresolved = [.. report.MissingRequiredDependencies.Where(missing => !plans.Any(plan => Covers(plan.TargetVersion, missing)))];
                if (unresolved.Count > 0)
                {
                    blocked.Add($"{name}：新版本需要的相依模組找不到相容版本（{string.Join("、", unresolved)}）");
                    continue;
                }

                foreach (var plan in plans.Where(static p => p.Action == ModInstallAction.Install && p.TargetVersion.PrimaryFile is not null))
                {
                    string key = plan.TargetVersion.PrimaryFile!.Filename;
                    if (!dependencies.TryGetValue(key, out var entry))
                    {
                        entry = (plan, []);
                        dependencies[key] = entry;
                    }

                    entry.RequiredBy.Add(name);
                }
            }

            accepted.Add(proposal.Candidate);
        }

        if (dependencies.Count > 0)
        {
            accepted.AddRange(await BuildDependencyItemsAsync(dependencies.Values).ConfigureAwait(true));
        }

        return accepted;
    }

    private static bool Covers(OnlineModVersion version, string dependencyKey) =>
        string.Equals(version.ProjectId, dependencyKey, StringComparison.OrdinalIgnoreCase) ||
        string.Equals(version.VersionId, dependencyKey, StringComparison.OrdinalIgnoreCase) ||
        version.Files.Any(file => string.Equals(file.Filename, dependencyKey, StringComparison.OrdinalIgnoreCase));

    private async Task<List<ModUpdateCandidateItem>> BuildDependencyItemsAsync(IEnumerable<(ModDependencyPlanItem Plan, List<string> RequiredBy)> dependencies)
    {
        List<(ModDependencyPlanItem Plan, List<string> RequiredBy)> list = [.. dependencies];
        IReadOnlyDictionary<string, string> titles = new Dictionary<string, string>();
        try
        {
            titles = await _modrinthClient.GetProjectTitlesAsync(
                list.Select(static d => d.Plan.TargetVersion.ProjectId).Where(static id => !string.IsNullOrWhiteSpace(id)).Distinct(StringComparer.OrdinalIgnoreCase).ToList(),
                CancellationToken.None).ConfigureAwait(true);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "取得相依模組名稱失敗，改用檔名顯示");
        }

        List<ModUpdateCandidateItem> items = [];
        foreach (var (plan, requiredBy) in list)
        {
            var version = plan.TargetVersion;
            var file = version.PrimaryFile!;
            string title = titles.TryGetValue(version.ProjectId, out string? found) && !string.IsNullOrWhiteSpace(found)
                ? found
                : ModHelpers.ModFilenameStem(file.Filename);
            string? expectedHash = ModHelpers.ResolveHash(file, out string algorithm);
            items.Add(new ModUpdateCandidateItem
            {
                ModName = $"{title}（{string.Join("、", requiredBy.Distinct(StringComparer.Ordinal))} 需要）",
                CurrentVersion = "未安裝",
                NewVersion = version.VersionNumber,
                FileName = file.Filename,
                DownloadUrl = file.Url,
                ExpectedHash = expectedHash,
                HashAlgorithm = expectedHash is not null ? algorithm : null,
                LocalMod = null,
            });
        }

        return [.. items.OrderBy(static i => i.ModName, StringComparer.Ordinal)];
    }

    private sealed record UpdateProposal(ModUpdateCandidateItem Candidate, OnlineModVersion Version, OnlineModCompatibilityReport Report);

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
                    Logger.Error(ex, "更新模組「{Name}」失敗", item.ModName);
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

        if (installResult?.Completed != true)
        {
            Logger.Warning("更新模組「{Name}」失敗: {Error}", item.ModName, installResult?.Message ?? "未知錯誤");
            return;
        }

        if (item.LocalMod is null)
        {
            Logger.Information("已安裝更新所需的相依模組「{Name}」({Version})", item.ModName, item.NewVersion);
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
