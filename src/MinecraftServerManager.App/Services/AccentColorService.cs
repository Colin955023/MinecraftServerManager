using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;
using MinecraftServerManager.Infrastructure.Logging;
using Windows.UI;
using Windows.UI.ViewManagement;

namespace MinecraftServerManager.App.Services;

/// <summary>
/// 應用程式強調色彩管理服務：支援 Windows 系統強調色與自訂色彩動態覆蓋
/// </summary>
public static class AccentColorService
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(AccentColorService));
    private static readonly UISettings UiSettings = new();
    private static string? s_currentCustomHex;
    private static Action<Action>? s_postToUi;

    static AccentColorService()
    {
        try
        {
            UiSettings.ColorValuesChanged += (sender, args) =>
            {
                // UISettings 事件於背景執行緒觸發，資源字典僅能於 UI 執行緒更新
                if (string.IsNullOrEmpty(s_currentCustomHex) && s_postToUi is { } postToUi)
                {
                    postToUi(() => ApplyAccentColor(null));
                }
            };
        }
        catch (Exception ex)
        {
            Logger.Warning("註冊系統色彩變更事件失敗: {Message}", ex.Message);
        }
    }

    /// <summary>
    /// 設定 UI 執行緒派送委派（由 WinUiService 提供），供系統強調色變更時回到 UI 執行緒套用
    /// </summary>
    public static void SetUiDispatcher(Action<Action> postToUi) =>
        s_postToUi = postToUi ?? throw new ArgumentNullException(nameof(postToUi));

    /// <summary>
    /// 當強調色彩變更時觸發
    /// </summary>
    public static event Action? AccentColorChanged;

    /// <summary>
    /// 取得目前 Windows 系統的強調色彩
    /// </summary>
    public static Color GetSystemAccentColor()
    {
        try
        {
            return UiSettings.GetColorValue(UIColorType.Accent);
        }
        catch (Exception ex)
        {
            Logger.Warning("取得 Windows 系統強調色失敗，使用預設值: {Message}", ex.Message);
            return Color.FromArgb(255, 79, 111, 216);
        }
    }

    /// <summary>
    /// 套用強調色彩（若 customHex 為空則使用系統色彩）
    /// </summary>
    public static void ApplyAccentColor(string? customHex)
    {
        try
        {
            s_currentCustomHex = customHex;
            Color color = ParseColor(customHex) ?? GetSystemAccentColor();
            Color hoverColor = CalculateHoverColor(color);
            Color pressedColor = CalculatePressedColor(color);
            Color disabledColor = CalculateDisabledColor(color);

            if (Application.Current?.Resources is ResourceDictionary appResources)
            {
                UpdateAccentResources(appResources, color, hoverColor, pressedColor, disabledColor);

                if (appResources.ThemeDictionaries != null)
                {
                    foreach (object? key in appResources.ThemeDictionaries.Keys)
                    {
                        if (appResources.ThemeDictionaries[key] is ResourceDictionary themeDict)
                        {
                            UpdateAccentResources(themeDict, color, hoverColor, pressedColor, disabledColor);
                        }
                    }
                }
            }

            Logger.Information("套用強調色彩: {Hex} (RGB: {R},{G},{B})", customHex ?? "系統預設", color.R, color.G, color.B);
            AccentColorChanged?.Invoke();
        }
        catch (System.Runtime.InteropServices.COMException ex)
        {
            // 單元測試或無 WinUI 3 Application 執行個體環境下略過
            Logger.Warning("套用強調色彩略過（WinUI 資源不可用）: {Message}", ex.Message);
        }
        catch (Exception ex)
        {
            Logger.Warning("套用強調色彩失敗: {Message}", ex.Message);
        }
    }

    private static void UpdateAccentResources(
        ResourceDictionary dict,
        Color color,
        Color hoverColor,
        Color pressedColor,
        Color disabledColor)
    {
        dict["SystemAccentColor"] = color;
        UpdateBrush(dict, "AccentBrush", color);
        UpdateBrush(dict, "AccentHoverBrush", hoverColor);
        UpdateBrush(dict, "AccentFillColorDefaultBrush", color);
        UpdateBrush(dict, "AccentFillColorSecondaryBrush", hoverColor);
        UpdateBrush(dict, "AccentFillColorTertiaryBrush", pressedColor);
        UpdateBrush(dict, "AccentFillColorDisabledBrush", disabledColor);
    }

    private static void UpdateBrush(ResourceDictionary dict, string key, Color color)
    {
        if (dict.TryGetValue(key, out object? resource) && resource is SolidColorBrush brush)
        {
            brush.Color = color;
        }
        else
        {
            dict[key] = new SolidColorBrush(color);
        }
    }

    private static Color CalculateHoverColor(Color baseColor) =>
        Color.FromArgb(
            baseColor.A,
            (byte)Math.Min(255, baseColor.R + 25),
            (byte)Math.Min(255, baseColor.G + 25),
            (byte)Math.Min(255, baseColor.B + 25));

    private static Color CalculatePressedColor(Color baseColor) =>
        Color.FromArgb(
            baseColor.A,
            (byte)Math.Max(0, baseColor.R - 25),
            (byte)Math.Max(0, baseColor.G - 25),
            (byte)Math.Max(0, baseColor.B - 25));

    private static Color CalculateDisabledColor(Color baseColor) =>
        Color.FromArgb(
            100,
            baseColor.R,
            baseColor.G,
            baseColor.B);

    public static string ToHex(Color color) =>
            $"#{color.R:X2}{color.G:X2}{color.B:X2}";

    public static Color? ParseColor(string? hex)
    {
        if (string.IsNullOrWhiteSpace(hex))
        {
            return null;
        }

        ReadOnlySpan<char> span = hex.AsSpan().Trim().TrimStart('#');
        if (span.Length == 6 && uint.TryParse(span, System.Globalization.NumberStyles.HexNumber, System.Globalization.CultureInfo.InvariantCulture, out uint rgb))
        {
            return Color.FromArgb(255, (byte)(rgb >> 16), (byte)(rgb >> 8), (byte)rgb);
        }

        return null;
    }
}
