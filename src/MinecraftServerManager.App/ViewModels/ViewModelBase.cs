using CommunityToolkit.Mvvm.ComponentModel;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 全域 ViewModel 基礎類別
/// </summary>
public abstract class ViewModelBase : ObservableObject
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ViewModelBase));

    /// <summary>
    /// 有未儲存變更時詢問使用者是否捨棄；無變更時直接回傳 true
    /// </summary>
    protected static Task<bool> ConfirmDiscardChangesAsync(IUiService ui, bool hasUnsavedChanges, string message)
    {
        ArgumentNullException.ThrowIfNull(ui);
        return hasUnsavedChanges
            ? ui.ConfirmAsync(message, "捨棄變更", UiMessageLevel.Warning)
            : Task.FromResult(true);
    }

    /// <summary>
    /// 安全執行背景非同步工作，統一處理 OperationCanceledException、記錄例外並選擇性提示使用者
    /// </summary>
    /// <param name="work">非同步工作委派</param>
    /// <param name="operationName">操作名稱描述（用於記錄與提示）</param>
    /// <param name="logger">專屬元件記錄器（為空時使用 ViewModelBase 預設 Logger）</param>
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
        logger ??= Logger;

        try
        {
            await work().ConfigureAwait(true);
        }
        catch (OperationCanceledException)
        {
            logger.Information("操作「{Operation}」已被取消", operationName);
        }
        catch (Exception ex)
        {
            logger.Error(ex, "操作「{Operation}」執行時發生例外錯誤: {Message}", operationName, ex.Message);

            try
            {
                onException?.Invoke(ex);
            }
            catch (Exception callbackEx)
            {
                logger.Error(callbackEx, "操作「{Operation}」之例外回呼執行失敗: {Message}", operationName, callbackEx.Message);
            }

            if (notifyUser && uiService is not null)
            {
                try
                {
                    await uiService.ShowErrorAsync($"{operationName} 失敗：\n{ex.Message}", "操作錯誤").ConfigureAwait(true);
                }
                catch (Exception uiEx)
                {
                    logger.Warning("提示錯誤對話方塊失敗: {0}", uiEx.Message);
                }
            }
        }
    }
}
