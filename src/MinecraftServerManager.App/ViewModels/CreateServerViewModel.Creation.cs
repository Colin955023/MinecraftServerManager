using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.App.ViewModels;

public sealed partial class CreateServerViewModel
{
    [RelayCommand(CanExecute = nameof(CanCreateServer))]
    public async Task CreateServerAsync()
    {
        if (string.IsNullOrWhiteSpace(ServerName))
        {
            _ui.Notify("伺服器名稱不能為空", NotificationType.Warning);
            return;
        }

        if (IsMemoryError)
        {
            _ui.Notify($"記憶體設定無效：{MemoryWarningText}", NotificationType.Warning);
            return;
        }

        IsCreating = true;
        var token = _lifetimeToken;
        try
        {
            var lk = CurrentLoaderKind;
            string? javaPath = await ResolveJavaPathAsync(token);
            if (javaPath is null)
            {
                return;
            }

            var plan = BuildCreationPlan(lk, javaPath);
            Logger.Information("開始建立伺服器：{Name}，版本：{Version}，載入器：{Loader}，記憶體：{Min}M-{Max}M，Java：{Java}",
                plan.Config.Name.Value, plan.Config.MinecraftVersion.Value, plan.Config.LoaderType, plan.Config.MemoryMinMb, plan.Config.MemoryMaxMb, javaPath);

            ServerCreationResult created;
            using (var progressDialog = _ui.ShowServerCreationProgress(plan.Config.Name.Value))
            {
                created = await _serverManager.CreateServerAsync(plan, progressDialog.Progress, token);
            }

            if (!created.Completed || created.Config is null)
            {
                Logger.Warning("伺服器建立失敗：{Message}", created.Message);
                await _ui.ShowErrorAsync($"建立伺服器失敗：\n{created.Message}", "建立伺服器失敗");
                return;
            }

            await RunInitializationAsync(created.Config, javaPath);
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested)
        {
            Logger.Information("建立伺服器已取消");
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "建立伺服器時發生例外");
            await _ui.ShowErrorAsync($"建立伺服器時發生錯誤：\n{ex.Message}", "建立伺服器失敗");
        }
        finally
        {
            IsCreating = false;
        }
    }

    /// <summary>依官方 Java 需求決定建立用 Java；表單路徑不符時自動改用本機相符版本（不覆寫表單）。找不到時提示並回傳 null</summary>
    private async Task<string?> ResolveJavaPathAsync(CancellationToken cancellationToken)
    {
        string version = SelectedMinecraftVersion;
        int? targetMajor;
        try
        {
            targetMajor = await _javaRequirementService.GetRequiredJavaMajorAsync(version, cancellationToken);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "取得 Minecraft {Version} 的 Java 需求失敗，改用快取", version);
            targetMajor = _javaRequirementService.GetCachedJavaMajor(version);
        }

        string javaPath = JavaPath.Trim();
        if (targetMajor is > 0)
        {
            int major = targetMajor.Value;
            if (!await IsJavaMajorAsync(javaPath, major, cancellationToken))
            {
                var matched = await JavaResolutionHelper.FindMatchingJavaAsync(_javaDetector, major, cancellationToken);
                if (matched is null)
                {
                    Logger.Warning("建立伺服器已終止：本機未安裝符合 Minecraft {Version} 所需之 Java {Major}", version, major);
                    await _ui.ShowErrorAsync($"建立伺服器已終止！\n\nMinecraft {version} 強制需要 Java {major}，但系統偵測不到相容的 Java 執行檔。\n請點選「管理 Java」安裝或設定 Java {major} 後再建立伺服器。",
                        "Java 版本不相符");
                    return null;
                }

                javaPath = matched.ExecutablePath;
                Logger.Information("建立伺服器已自動切換使用符合之 Java {Major}：{Path}（不覆寫表單欄位）", matched.MajorVersion, javaPath);
            }
        }

        if (string.IsNullOrWhiteSpace(javaPath))
        {
            _ui.Notify("未設定合適的 Java 執行檔路徑，請點選「管理 Java」指定或安裝", NotificationType.Warning);
            return null;
        }

        return javaPath;
    }

    private async Task<bool> IsJavaMajorAsync(string javaPath, int major, CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(javaPath))
        {
            return false;
        }

        var detected = await _javaDetector.DetectAsync(forceRefresh: false, cancellationToken);
        return detected.Any(j => j.MajorVersion == major && string.Equals(j.ExecutablePath, javaPath, StringComparison.OrdinalIgnoreCase));
    }

    private ServerCreationPlan BuildCreationPlan(LoaderKind loaderKind, string javaPath)
    {
        // 佔位文字不是實際版本；空字串代表由安裝器取得最新穩定版
        string loaderVersion = SelectedLoaderVersion;
        if (loaderVersion is "無" or NoAvailableVersion || loaderVersion == LatestStableVersionText(SelectedLoader))
        {
            loaderVersion = string.Empty;
        }

        return ServerCreationPlan.Create(
            name: Domain.ValueObjects.ServerName.Parse(ServerName.Trim()),
            minecraftVersion: Domain.ValueObjects.MinecraftVersion.Parse(SelectedMinecraftVersion),
            loaderType: loaderKind,
            loaderVersion: loaderVersion,
            memoryMaxMb: ParsedMaxMemoryMb,
            memoryMinMb: ParsedMinMemoryMb,
            jvmArgs: _customJvmArgs,
            userJavaPath: javaPath);
    }

    /// <summary>執行初次啟動初始化並導向管理頁；未完成時保留檔案並提示可稍後手動啟動</summary>
    private async Task RunInitializationAsync(ServerConfig config, string javaPath)
    {
        string name = config.Name.Value;
        Logger.Information("伺服器檔案與腳本已建立完成：{Name}，路徑：{Path}，即將執行初次啟動初始化", name, config.Path);

        bool initSuccess;
        IServerRuntime runtime = _runtimeHost.GetRuntime(name);
        using (var initVm = new ServerInitializationViewModel(runtime, _createInitializationWorkflow(runtime), config, javaPath, _ui))
        {
            initSuccess = await _ui.ShowServerInitializationAsync(initVm);
        }

        _ui.ActivateMainWindow();

        if (initSuccess)
        {
            Logger.Information("伺服器建立成功：{Name}，路徑：{Path}", name, config.Path);
            _ui.Notify($"伺服器「{name}」已成功建立並完成初始化！", NotificationType.Success);
        }
        else
        {
            Logger.Warning("伺服器「{Name}」初次初始化未完成或已被中斷", name);
            _ui.ShowNotification(
                $"伺服器「{name}」初次啟動初始化已被強制中斷。\n\n伺服器檔案已完整保留，您稍後可於「管理伺服器」頁面手動啟動伺服器繼續完成世界生成與設定。",
                "伺服器初始化已中斷",
                NotificationType.Warning);
        }

        _navigateCallback(PageKeys.Manage, name);
    }
}
