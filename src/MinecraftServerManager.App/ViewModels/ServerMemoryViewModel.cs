using System.Globalization;
using CommunityToolkit.Mvvm.ComponentModel;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>伺服器記憶體設定對話方塊 ViewModel</summary>
public sealed partial class ServerMemoryViewModel : ViewModelBase
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerMemoryViewModel));

    private readonly ServerConfig _config;
    private readonly Func<int, int?, Task<bool>> _saveCallback;
    private readonly IUiService _ui;
    private readonly long _systemMemoryMb;

    public ServerMemoryViewModel(
        ServerConfig config,
        Func<int, int?, Task<bool>> saveCallback,
        IUiService uiService,
        long systemMemoryMb)
    {
        ArgumentNullException.ThrowIfNull(config);
        ArgumentNullException.ThrowIfNull(saveCallback);
        ArgumentNullException.ThrowIfNull(uiService);

        _config = config;
        _saveCallback = saveCallback;
        _ui = uiService;
        _systemMemoryMb = systemMemoryMb;

        MaxMemoryMb = config.MemoryMaxMb.ToString(CultureInfo.InvariantCulture);
        MinMemoryMb = config.MemoryMinMb.HasValue
            ? config.MemoryMinMb.Value.ToString(CultureInfo.InvariantCulture)
            : string.Empty;
    }

    [ObservableProperty]
    public partial string MaxMemoryMb { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string MinMemoryMb { get; set; } = string.Empty;

    [ObservableProperty]
    public partial string ErrorMessage { get; set; } = string.Empty;

    public string ServerDetails => $"伺服器：{_config.Name.Value} ({_config.MinecraftVersion.Value} / {_config.LoaderType})";

    public string SystemMemoryText => _systemMemoryMb > 0
        ? $"系統實體記憶體總量：約 {_systemMemoryMb} MB（{Math.Round(_systemMemoryMb / 1024d, MidpointRounding.AwayFromZero)} GB）"
        : string.Empty;

    /// <summary>驗證並儲存；回傳 true 時對話框才關閉，失敗原因以對話框內資訊列顯示（不得另開對話框，以免與開啟中的對話框互相等待）</summary>
    public async Task<bool> SaveAsync()
    {
        if (!Validate(out int max, out int? min, out bool adjusted))
        {
            return false;
        }

        if (adjusted)
        {
            _ui.ShowNotification(ErrorMessage, "記憶體已自動調整", NotificationType.Warning);
        }

        try
        {
            if (await _saveCallback(max, min))
            {
                return true;
            }

            ErrorMessage = "儲存記憶體設定失敗，請確認伺服器檔案是否具備寫入權限";
        }
        catch (OperationCanceledException)
        {
            Logger.Information("記憶體設定操作已取消");
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "儲存記憶體設定出錯");
            ErrorMessage = $"儲存記憶體設定時發生錯誤：{ex.Message}";
        }

        return false;
    }

    private bool Validate(out int max, out int? min, out bool adjusted)
    {
        var check = MemoryHelpers.CheckServerMemory(MaxMemoryMb, MinMemoryMb, _systemMemoryMb, clampToSystem: true);
        ErrorMessage = check.Level == MemoryCheckLevel.Ok ? string.Empty : check.Message;
        max = check.MaxMb;
        min = check.MinMb;
        adjusted = false;
        if (check.Level == MemoryCheckLevel.Error)
        {
            return false;
        }

        // 同步顯示自動調降後之數值
        adjusted = !int.TryParse(MaxMemoryMb.Trim(), CultureInfo.InvariantCulture, out int inputMax) || inputMax != max
                   || (min is { } clampedMin && (!int.TryParse(MinMemoryMb.Trim(), CultureInfo.InvariantCulture, out int inputMin) || inputMin != clampedMin));
        MaxMemoryMb = max.ToString(CultureInfo.InvariantCulture);
        if (min is { } minValue)
        {
            MinMemoryMb = minValue.ToString(CultureInfo.InvariantCulture);
        }

        return true;
    }
}
