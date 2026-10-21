using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;

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

    partial void OnMaxMemoryMbChanged(string value) => Validate(out _, out _);

    partial void OnMinMemoryMbChanged(string value) => Validate(out _, out _);

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
            }
        }
        catch (Exception ex)
        {
            ErrorMessage = $"儲存出錯：{ex.Message}";
        }
    }

    public bool HasUnsavedChanges =>
        !string.Equals(MaxMemoryMb.Trim(), _config.MemoryMaxMb.ToString(System.Globalization.CultureInfo.InvariantCulture), StringComparison.Ordinal) ||
        !string.Equals(MinMemoryMb.Trim(), _config.MemoryMinMb.HasValue ? _config.MemoryMinMb.Value.ToString(System.Globalization.CultureInfo.InvariantCulture) : string.Empty, StringComparison.Ordinal);

    public bool ConfirmDiscard()
    {
        if (!HasUnsavedChanges)
        {
            return true;
        }

        return _ui.Confirm("有尚未儲存的記憶體設定變更，確定要捨棄變更並關閉嗎？", "捨棄變更", UiMessageLevel.Warning);
    }

    [RelayCommand]
    public void Cancel()
    {
        if (ConfirmDiscard())
        {
            RequestClose?.Invoke(false);
        }
    }
}
