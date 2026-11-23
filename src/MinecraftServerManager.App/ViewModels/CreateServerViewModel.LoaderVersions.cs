using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Loaders;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.App.ViewModels;

public sealed partial class CreateServerViewModel
{
    /// <summary>載入新載入器的 Minecraft 版本；選取版本未變時才於此重新整理相依項目，否則交由版本變更處理</summary>
    private async Task HandleLoaderChangedAsync(string loaderName)
    {
        string previousVersion = SelectedMinecraftVersion;
        if (LoaderKinds.TryParse(loaderName, out var lk))
        {
            await LoadMinecraftVersionsAsync(lk);
        }

        if (string.Equals(previousVersion, SelectedMinecraftVersion, StringComparison.Ordinal))
        {
            await RefreshSelectionDependentsAsync();
        }
    }

    /// <summary>自快取載入指定載入器的 Minecraft 版本；已被較新請求取代則捨棄</summary>
    private async Task LoadMinecraftVersionsAsync(LoaderKind loaderKind)
    {
        var token = _versionFetch.Next();
        try
        {
            var versions = await _loaderCatalog.GetMinecraftVersionsForLoaderAsync(loaderKind, cancellationToken: token);
            if (!token.IsCancellationRequested)
            {
                ApplyMinecraftVersions(versions, keepUserSelection: true);
            }
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested)
        {
            Logger.Information(VersionOperationCancelled);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "載入可用 Minecraft 版本失敗");
        }
    }

    private void ApplyMinecraftVersions(IReadOnlyList<LoaderVersion> versions, bool keepUserSelection)
    {
        if (versions.Count == 0)
        {
            return;
        }

        AvailableMinecraftVersions.ReplaceAll(versions.Select(static v => v.Version));
        if (AvailableMinecraftVersions.Contains(SelectedMinecraftVersion) && (!keepUserSelection || _isUserManuallySelectedVersion))
        {
            return;
        }

        if (keepUserSelection)
        {
            SetMinecraftVersionProgrammatically(AvailableMinecraftVersions[0]);
        }
        else
        {
            SelectedMinecraftVersion = AvailableMinecraftVersions[0];
        }
    }

    /// <summary>依目前載入器與 Minecraft 版本重新整理載入器版本與建議 JVM 摘要；新請求取消舊請求</summary>
    private async Task RefreshSelectionDependentsAsync()
    {
        var token = _selectionFetch.Next();
        try
        {
            await Task.WhenAll(RefreshLoaderVersionsAsync(token), UpdateJvmArgsSummaryAsync(token));
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested)
        {
            Logger.Information(VersionOperationCancelled);
        }
    }

    private async Task RefreshLoaderVersionsAsync(CancellationToken token)
    {
        string minecraftVersion = SelectedMinecraftVersion;
        if (!LoaderKinds.TryParse(SelectedLoader, out var loaderKind) || string.IsNullOrWhiteSpace(minecraftVersion))
        {
            UpdateLoaderStateSync();
            return;
        }

        try
        {
            var versions = await _loaderCatalog.GetLoaderVersionsAsync(loaderKind, minecraftVersion, token);
            if (token.IsCancellationRequested)
            {
                return;
            }

            if (versions.Count > 0)
            {
                LoaderVersions.ReplaceAll(versions.Select(static v => v.Version));
                SelectedLoaderVersion = LoaderVersions[0];
                IsLoaderVersionEnabled = loaderKind is LoaderKind.Forge or LoaderKind.NeoForge;
            }
            else
            {
                LoaderVersions.ReplaceAll(NoAvailableVersions);
                SelectedLoaderVersion = NoAvailableVersion;
                IsLoaderVersionEnabled = false;
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "重新整理模組載入器版本失敗");
            UpdateLoaderStateSync();
        }
    }

    [RelayCommand(CanExecute = nameof(CanReloadMinecraftVersions))]
    public Task ReloadMinecraftVersionsAsync()
    {
        var lk = CurrentLoaderKind;
        return RunReloadAsync(
            "正在向網路重新整理 Minecraft 版本清單...",
            "重新整理 Minecraft 版本清單失敗",
            () => ReloadMinecraftVersionListAsync(token => _loaderCatalog.GetMinecraftVersionsForLoaderAsync(lk, forceReload: true, cancellationToken: token), lk.ToString()));
    }

    /// <summary>Paper 無獨立載入器版本，改為重新整理 PaperMC 版本清單；其餘載入器強制重新載入全部載入器版本</summary>
    [RelayCommand(CanExecute = nameof(CanReloadLoaderVersions))]
    public Task ReloadLoaderVersionsAsync() => RunReloadAsync(
        "正在向網路重新整理載入器版本清單...",
        "重新整理載入器版本清單失敗",
        IsPaperSelected
            ? () => ReloadMinecraftVersionListAsync(token => _loaderCatalog.GetPaperMinecraftVersionsAsync(forceReload: true, token), "PaperMC")
            : ReloadAllLoadersAsync);

    private async Task RunReloadAsync(string statusText, string failureText, Func<Task> reload)
    {
        string previousVersion = SelectedMinecraftVersion;
        BeginLoading(statusText);
        try
        {
            await reload();
            if (string.Equals(previousVersion, SelectedMinecraftVersion, StringComparison.Ordinal))
            {
                await RefreshSelectionDependentsAsync();
            }
        }
        catch (OperationCanceledException)
        {
            Logger.Information(VersionOperationCancelled);
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "{Operation}", failureText);
            _ui.Notify($"{failureText}：{ex.Message}", NotificationType.Warning);
        }
        finally
        {
            EndLoading();
        }
    }

    private async Task ReloadMinecraftVersionListAsync(Func<CancellationToken, Task<IReadOnlyList<LoaderVersion>>> fetch, string sourceName)
    {
        var token = _versionFetch.Next();
        var versions = await fetch(token);
        token.ThrowIfCancellationRequested();
        ApplyMinecraftVersions(versions, keepUserSelection: false);
        await Task.Run(_javaRequirementService.ReloadCache, token);
        Logger.Information("已手動向網路重新整理 {Source} 的 Minecraft 版本清單，共 {Count} 個版本", sourceName, versions.Count);
    }

    private async Task ReloadAllLoadersAsync()
    {
        await _loaderCatalog.ForceReloadAllLoadersAsync(_lifetimeToken);
        Logger.Information("已強制向網路重新載入所有載入器版本清單");
    }
}
