using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>伺服器記憶體設定對話方塊 ViewModel</summary>
public sealed partial class ServerMemoryViewModel(
    ServerConfig config,
    Func<int, int?, Task<bool>> saveCallback,
    IUiService uiService,
    long systemMemoryMb) : ObservableObject
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerMemoryViewModel));
    private readonly ServerConfig _config = config;
    private readonly Func<int, int?, Task<bool>> _saveCallback = saveCallback;
    private readonly long _systemMemoryMb = systemMemoryMb;
    private readonly IUiService _ui = uiService;

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

    private bool Validate(out int max, out int? min, out bool adjusted)
    {
        var check = MemoryUtils.CheckServerMemory(MaxMemoryMb, MinMemoryMb, _systemMemoryMb, clampToSystem: true);
        ErrorMessage = check.Level == MemoryCheckLevel.Ok ? string.Empty : check.Message;
        max = check.MaxMb;
        min = check.MinMb;
        adjusted = false;
        if (check.Level == MemoryCheckLevel.Error)
        {
            return false;
        }

        // 同步顯示自動調降後之數值
        adjusted = !int.TryParse(MaxMemoryMb.Trim(), System.Globalization.CultureInfo.InvariantCulture, out int inputMax) || inputMax != max
                   || (min is { } clampedMin && (!int.TryParse(MinMemoryMb.Trim(), System.Globalization.CultureInfo.InvariantCulture, out int inputMin) || inputMin != clampedMin));
        MaxMemoryMb = max.ToString(System.Globalization.CultureInfo.InvariantCulture);
        if (min is { } minValue)
        {
            MinMemoryMb = minValue.ToString(System.Globalization.CultureInfo.InvariantCulture);
        }

        return true;
    }

    [RelayCommand]
    public async Task SaveAsync()
    {
        if (!Validate(out int max, out int? min, out bool adjusted))
        {
            if (!string.IsNullOrWhiteSpace(ErrorMessage))
            {
                _ui.ShowNotification(ErrorMessage, "記憶體數值無效", NotificationType.Warning);
            }
            return;
        }

        if (adjusted)
        {
            _ui.ShowNotification(ErrorMessage, "記憶體已自動調整", NotificationType.Warning);
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
                await _ui.ShowErrorAsync("儲存記憶體設定失敗，請確認伺服器檔案是否具備寫入權限。", "儲存失敗").ConfigureAwait(true);
            }
        }
        catch (OperationCanceledException)
        {
            Logger.Information("記憶體設定操作已取消");
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "儲存記憶體設定出錯");
            ErrorMessage = $"儲存出錯：{ex.Message}";
            await _ui.ShowErrorAsync($"儲存記憶體設定時發生錯誤：\n{ex.Message}", "儲存錯誤").ConfigureAwait(true);
        }
    }
}
