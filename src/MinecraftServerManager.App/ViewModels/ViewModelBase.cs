using CommunityToolkit.Mvvm.ComponentModel;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 全域 ViewModel 基礎類別
/// </summary>
public abstract class ViewModelBase : ObservableObject
{
    private static readonly ComponentLogger FallbackLogger = AppLogging.CreateComponentLogger("ViewModelBase");

    /// <summary>
    /// 安全執行背景非同步工作，統一處理 OperationCanceledException、記錄例外並選擇性提示使用者
    /// </summary>
    /// <param name="work">非同步工作委派</param>
    /// <param name="operationName">操作名稱描述（用於記錄與提示）</param>
    /// <param name="logger">專屬元件記錄器（為空時使用預設記錄器）</param>
    /// <param name="uiService">UI 服務（用於錯誤提示與 UI 派送）</param>
    /// <param name="onException">例外回呼處理（可為 null）</param>
    /// <param name="notifyUser">發生例外時是否提示使用者</param>
    /// <returns>代表安全執行的 Task</returns>
    public static async Task RunSafeAsync(
        Func<Task> work,
        string operationName,
        ComponentLogger? logger = null,
        IUiService? uiService = null,
        Action<Exception>? onException = null,
        bool notifyUser = false)
    {
        ArgumentNullException.ThrowIfNull(work);
        var log = logger ?? FallbackLogger;

        try
        {
            await work().ConfigureAwait(true);
        }
        catch (OperationCanceledException)
        {
            log.Information("操作「{Operation}」已被取消", operationName);
        }
        catch (Exception ex)
        {
            log.Error(ex, "操作「{Operation}」執行時發生例外錯誤: {Message}", operationName, ex.Message);

            try
            {
                onException?.Invoke(ex);
            }
            catch (Exception callbackEx)
            {
                log.Error(callbackEx, "操作「{Operation}」之例外回呼執行失敗: {Message}", operationName, callbackEx.Message);
            }

            if (notifyUser && uiService is not null)
            {
                try
                {
                    uiService.PostToUi(() =>
                    {
                        uiService.ShowError($"{operationName} 失敗：\n{ex.Message}", "操作錯誤");
                    });
                }
                catch
                {
                    // 避免提示過程二度拋出異常
                }
            }
        }
    }
}
