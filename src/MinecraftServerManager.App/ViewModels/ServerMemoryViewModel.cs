using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 伺服器記憶體設定對話方塊 ViewModel
/// </summary>
public sealed partial class ServerMemoryViewModel(
    ServerConfig config,
    Func<int, int?, Task<bool>> saveCallback,
    long? systemMemoryMb = null,
    IUiService? uiService = null) : ObservableObject
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerMemoryViewModel));
    private readonly ServerConfig _config = config;
    private readonly Func<int, int?, Task<bool>> _saveCallback = saveCallback;
    private readonly long _systemMemoryMb = systemMemoryMb ?? MemoryUtils.GetTotalSystemMemoryMb();
    private readonly IUiService _ui = uiService ?? NoOpUiService.Instance;

    [ObservableProperty]
    public partial string MaxMemoryMb { get; set; } = config.MemoryMaxMb.ToString(System.Globalization.CultureInfo.InvariantCulture);

    [ObservableProperty]
    public partial string MinMemoryMb { get; set; } = config.MemoryMinMb.HasValue ? config.MemoryMinMb.Value.ToString(System.Globalization.CultureInfo.InvariantCulture) : string.Empty;

    [ObservableProperty]
    public partial string ErrorMessage { get; set; } = string.Empty;

    public string ServerDetails => $"伺服器：{_config.Name.Value} ({_config.MinecraftVersion.Value} / {_config.LoaderType})";

    public string SystemMemoryText => _systemMemoryMb > 0
        ? $"💻 系統實體記憶體總量：約 {_systemMemoryMb} MB ({_systemMemoryMb / 1024} GB)"
        : string.Empty;

    public event Action<bool>? RequestClose;

    private bool Validate(out int max, out int? min)
    {
        max = 0;
        min = null;
        ErrorMessage = string.Empty;

        if (!int.TryParse(MaxMemoryMb.Trim(), out max) || max <= 0)
        {
            ErrorMessage = "最大記憶體必須為大於 0 的整數 (MB)";
            return false;
        }

        if (!string.IsNullOrWhiteSpace(MinMemoryMb))
        {
            if (!int.TryParse(MinMemoryMb.Trim(), out int parsedMin) || parsedMin <= 0)
            {
                ErrorMessage = "最小記憶體必須為大於 0 的整數 (MB)";
                return false;
            }

            if (parsedMin > max)
            {
                ErrorMessage = "最小記憶體不可大於最大記憶體";
                return false;
            }

            min = parsedMin;
        }

        if (_systemMemoryMb > 0 && max > _systemMemoryMb)
        {
            ErrorMessage = $"⚠️ 最大記憶體超過系統實體記憶體 ({_systemMemoryMb} MB)，可能會導致系統不穩定";
        }

        return true;
    }

    [RelayCommand]
    public async Task SaveAsync()
    {
        if (!Validate(out int max, out int? min))
        {
            if (!string.IsNullOrWhiteSpace(ErrorMessage))
            {
                await _ui.ShowWarningAsync(ErrorMessage, "記憶體數值無效").ConfigureAwait(true);
            }
            return;
        }

        try
        {
            bool ok = await _saveCallback(max, min).ConfigureAwait(true);
            if (ok)
            {
                RequestClose?.Invoke(true);
            }
            else
            {
                ErrorMessage = "儲存記憶體設定失敗";
                await _ui.ShowWarningAsync("儲存記憶體設定失敗，請確認伺服器檔案是否具備寫入權限。", "儲存失敗").ConfigureAwait(true);
            }
        }
        catch (OperationCanceledException)
        {
            Logger.Information("記憶體設定操作已取消");
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "儲存記憶體設定出錯：{Message}", ex.Message);
            ErrorMessage = $"儲存出錯：{ex.Message}";
            await _ui.ShowErrorAsync($"儲存記憶體設定時發生錯誤：\n{ex.Message}", "儲存錯誤").ConfigureAwait(true);
        }
    }

    public bool HasUnsavedChanges =>
        !string.Equals(MaxMemoryMb.Trim(), _config.MemoryMaxMb.ToString(System.Globalization.CultureInfo.InvariantCulture), StringComparison.Ordinal) ||
        !string.Equals(MinMemoryMb.Trim(), _config.MemoryMinMb.HasValue ? _config.MemoryMinMb.Value.ToString(System.Globalization.CultureInfo.InvariantCulture) : string.Empty, StringComparison.Ordinal);

    public async Task<bool> ConfirmDiscardAsync()
    {
        if (!HasUnsavedChanges)
        {
            return true;
        }

        return await _ui.ConfirmAsync("有尚未儲存的記憶體設定變更，確定要捨棄變更並關閉嗎？", "捨棄變更", UiMessageLevel.Warning).ConfigureAwait(true);
    }

    [RelayCommand]
    public async Task CancelAsync()
    {
        if (await ConfirmDiscardAsync().ConfigureAwait(true))
        {
            RequestClose?.Invoke(false);
        }
    }
}
