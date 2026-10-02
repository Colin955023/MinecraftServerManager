using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.Domain.Servers;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 伺服器記憶體設定對話框 ViewModel
/// </summary>
public sealed partial class ServerMemoryViewModel(
    ServerConfig config,
    Func<int, int?, Task<bool>> saveCallback,
    long? systemMemoryMb = null) : ObservableObject
{
    private readonly ServerConfig _config = config;
    private readonly Func<int, int?, Task<bool>> _saveCallback = saveCallback;
    private readonly long _systemMemoryMb = systemMemoryMb ?? GetSystemMemoryMb();

    [ObservableProperty]
    private string _maxMemoryMb = config.MemoryMaxMb.ToString(System.Globalization.CultureInfo.InvariantCulture);

    [ObservableProperty]
    private string _minMemoryMb = config.MemoryMinMb.HasValue ? config.MemoryMinMb.Value.ToString(System.Globalization.CultureInfo.InvariantCulture) : string.Empty;

    [ObservableProperty]
    private string _errorMessage = string.Empty;

    [ObservableProperty]
    private bool _hasError;

    [ObservableProperty]
    private bool _isBusy;

    public string ServerName => _config.Name.Value;

    public string ServerDetails => $"伺服器：{_config.Name.Value} ({_config.MinecraftVersion.Value} / {_config.LoaderType})";

    public string SystemMemoryText => _systemMemoryMb > 0
        ? $"💻 系統實體記憶體總量：約 {_systemMemoryMb} MB ({_systemMemoryMb / 1024} GB)"
        : string.Empty;

    public event Action<bool>? RequestClose;

    partial void OnMaxMemoryMbChanged(string value) => Validate();

    partial void OnMinMemoryMbChanged(string value) => Validate();

    private bool Validate()
    {
        ErrorMessage = string.Empty;
        HasError = false;

        if (!int.TryParse(MaxMemoryMb.Trim(), out int max) || max <= 0)
        {
            ErrorMessage = "最大記憶體必須為大於 0 的整數 (MB)";
            HasError = true;
            return false;
        }

        if (!string.IsNullOrWhiteSpace(MinMemoryMb))
        {
            if (!int.TryParse(MinMemoryMb.Trim(), out int min) || min <= 0)
            {
                ErrorMessage = "最小記憶體必須為大於 0 的整數 (MB)";
                HasError = true;
                return false;
            }

            if (min > max)
            {
                ErrorMessage = "最小記憶體不可大於最大記憶體";
                HasError = true;
                return false;
            }
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
        if (!int.TryParse(MaxMemoryMb.Trim(), out int max) || max <= 0)
        {
            ErrorMessage = "最大記憶體必須為大於 0 的整數 (MB)";
            HasError = true;
            return;
        }

        int? min = null;
        if (!string.IsNullOrWhiteSpace(MinMemoryMb))
        {
            if (!int.TryParse(MinMemoryMb.Trim(), out int parsedMin) || parsedMin <= 0)
            {
                ErrorMessage = "最小記憶體必須為大於 0 的整數 (MB)";
                HasError = true;
                return;
            }

            if (parsedMin > max)
            {
                ErrorMessage = "最小記憶體不可大於最大記憶體";
                HasError = true;
                return;
            }

            min = parsedMin;
        }

        IsBusy = true;
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
                HasError = true;
            }
        }
        catch (Exception ex)
        {
            ErrorMessage = $"儲存出錯：{ex.Message}";
            HasError = true;
        }
        finally
        {
            IsBusy = false;
        }
    }

    [RelayCommand]
    public void Cancel() => RequestClose?.Invoke(false);

    private static long GetSystemMemoryMb()
    {
        try
        {
            var memoryStatus = GC.GetGCMemoryInfo();
            long totalBytes = memoryStatus.TotalAvailableMemoryBytes;
            return totalBytes > 0 ? totalBytes / (1024 * 1024) : 16384;
        }
        catch
        {
            return 16384;
        }
    }
}
