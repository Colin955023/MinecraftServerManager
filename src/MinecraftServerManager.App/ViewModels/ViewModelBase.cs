using CommunityToolkit.Mvvm.ComponentModel;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>全域 ViewModel 基礎類別</summary>
public abstract class ViewModelBase : ObservableObject
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ViewModelBase));

    /// <summary>有未儲存變更時詢問使用者是否捨棄；無變更時直接回傳 true</summary>
    protected static Task<bool> ConfirmDiscardChangesAsync(IUiService ui, bool hasUnsavedChanges, string message)
    {
        ArgumentNullException.ThrowIfNull(ui);
        return hasUnsavedChanges
            ? ui.ConfirmAsync(message, "捨棄變更", UiMessageLevel.Warning)
            : Task.FromResult(true);
    }

    /// <summary>安全執行背景非同步工作（fire-and-forget 呼叫端使用）：取消記錄為資訊，其餘例外完整記錄為錯誤</summary>
    /// <param name="work">非同步工作委派</param>
    /// <param name="operationName">操作名稱描述（用於記錄）</param>
    /// <param name="logger">專屬元件記錄器（為空時使用 ViewModelBase 預設 Logger）</param>
    public static async Task RunSafeAsync(Func<Task> work, string operationName, ComponentLogger? logger = null)
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
            logger.Error(ex, "操作「{Operation}」執行時發生例外錯誤", operationName);
        }
    }
}
