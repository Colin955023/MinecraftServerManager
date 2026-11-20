using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;
using MinecraftServerManager.Infrastructure.Logging;
using Windows.UI;
using Windows.UI.ViewManagement;

namespace MinecraftServerManager.App.Services;

/// <summary>應用程式強調色彩管理服務：支援 Windows 系統強調色與自訂色彩動態覆蓋</summary>
public static class AccentColorService
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(AccentColorService));
    private static readonly UISettings UiSettings = new();
    private static string? s_currentCustomHex;

    private static readonly string[] SelectionAccentKeys =
    [
        "CheckBoxCheckBackgroundFillChecked", "CheckBoxCheckBackgroundStrokeChecked", "CheckBoxCheckBackgroundFillIndeterminate",
        "RadioButtonOuterEllipseCheckedFill", "RadioButtonOuterEllipseCheckedStroke",
        "ToggleSwitchFillOn", "ToggleSwitchStrokeOn",
    ];

    private static readonly string[] SelectionAccentPointerOverKeys =
    [
        "CheckBoxCheckBackgroundFillCheckedPointerOver", "CheckBoxCheckBackgroundStrokeCheckedPointerOver", "CheckBoxCheckBackgroundFillIndeterminatePointerOver",
        "RadioButtonOuterEllipseCheckedFillPointerOver", "RadioButtonOuterEllipseCheckedStrokePointerOver",
        "ToggleSwitchFillOnPointerOver", "ToggleSwitchStrokeOnPointerOver",
    ];

    private static readonly string[] SelectionAccentPressedKeys =
    [
        "CheckBoxCheckBackgroundFillCheckedPressed", "CheckBoxCheckBackgroundStrokeCheckedPressed", "CheckBoxCheckBackgroundFillIndeterminatePressed",
        "RadioButtonOuterEllipseCheckedFillPressed", "RadioButtonOuterEllipseCheckedStrokePressed",
        "ToggleSwitchFillOnPressed", "ToggleSwitchStrokeOnPressed",
    ];

    private static readonly string[] SelectionGlyphKeys =
    [
        "CheckBoxCheckGlyphForegroundChecked", "CheckBoxCheckGlyphForegroundCheckedPointerOver", "CheckBoxCheckGlyphForegroundCheckedPressed",
        "CheckBoxCheckGlyphForegroundIndeterminate", "CheckBoxCheckGlyphForegroundIndeterminatePointerOver", "CheckBoxCheckGlyphForegroundIndeterminatePressed",
        "RadioButtonCheckGlyphFill", "RadioButtonCheckGlyphFillPointerOver", "RadioButtonCheckGlyphFillPressed",
        "ToggleSwitchKnobFillOn", "ToggleSwitchKnobFillOnPointerOver", "ToggleSwitchKnobFillOnPressed",
    ];
    // 文字對比基準：取各主題卡片與頁面中對比最差的底色
    private static readonly Color LightTextBackground = Color.FromArgb(255, 0xF3, 0xF3, 0xF3);
    private static readonly Color DarkTextBackground = Color.FromArgb(255, 0x2C, 0x2C, 0x2C);
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
            Logger.Warning(ex, "註冊系統色彩變更事件失敗");
        }
    }

    /// <summary>設定 UI 執行緒派送委派</summary>
    public static void SetUiDispatcher(Action<Action> postToUi) =>
        s_postToUi = postToUi ?? throw new ArgumentNullException(nameof(postToUi));

    /// <summary>當強調色彩變更時觸發</summary>
    public static event Action? AccentColorChanged;

    /// <summary>取得目前 Windows 系統的強調色彩</summary>
    public static Color GetSystemAccentColor()
    {
        try
        {
            return UiSettings.GetColorValue(UIColorType.Accent);
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "取得 Windows 系統強調色失敗，使用預設值");
            return Color.FromArgb(255, 79, 111, 216);
        }
    }

    /// <summary>取得系統強調色及其明暗色階，失敗時改用計算值</summary>
    private static (Color Accent, Color Hover, Color Pressed) GetSystemAccentShades()
    {
        Color accent = GetSystemAccentColor();
        try
        {
            return (accent, UiSettings.GetColorValue(UIColorType.AccentLight1), UiSettings.GetColorValue(UIColorType.AccentDark1));
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "取得 Windows 系統強調色階失敗，改用計算值");
            return (accent, CalculateHoverColor(accent), CalculatePressedColor(accent));
        }
    }

    /// <summary>套用強調色彩（若 customHex 為空則使用系統色彩與系統原生色階）</summary>
    public static void ApplyAccentColor(string? customHex)
    {
        try
        {
            s_currentCustomHex = customHex;
            (Color color, Color hoverColor, Color pressedColor) = ParseColor(customHex) is { } custom
                ? (custom, CalculateHoverColor(custom), CalculatePressedColor(custom))
                : GetSystemAccentShades();
            Color disabledColor = CalculateDisabledColor(color);

            if (Application.Current?.Resources is ResourceDictionary appResources)
            {
                UpdateAccentResources(appResources, color, hoverColor, pressedColor, disabledColor);

                if (appResources.ThemeDictionaries != null)
                {
                    // Light 字典查無鍵時會回退取得 Default 的筆刷；先處理 Light 使其建立自有筆刷，避免改到深色主題
                    foreach (object? key in appResources.ThemeDictionaries.Keys.OrderBy(static k => Equals(k, "Light") ? 0 : 1))
                    {
                        if (appResources.ThemeDictionaries[key] is ResourceDictionary themeDict)
                        {
                            UpdateAccentResources(themeDict, color, hoverColor, pressedColor, disabledColor);

                            // 強調色文字：深色主題取亮色階、淺色主題取暗色階，並確保與背景對比達 4.5:1
                            bool light = Equals(key, "Light");
                            Color background = light ? LightTextBackground : DarkTextBackground;
                            Color text = EnsureTextContrast(light ? pressedColor : hoverColor, background);
                            UpdateBrush(themeDict, "AccentTextFillColorPrimaryBrush", text);
                            UpdateBrush(themeDict, "AccentTextBrush", text);
                            UpdateBrush(themeDict, "HyperlinkButtonForeground", text);
                            UpdateBrush(themeDict, "HyperlinkButtonForegroundPointerOver", Blend(text, background, 0.15));
                            UpdateBrush(themeDict, "HyperlinkButtonForegroundPressed", Blend(text, background, 0.3));
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
            Logger.Warning(ex, "套用強調色彩略過（WinUI 資源不可用）");
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "套用強調色彩失敗");
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
        UpdateBrush(dict, "AccentForegroundBrush", GetReadableForeground(color));
        UpdateBrush(dict, "AccentFillColorDefaultBrush", color);
        UpdateBrush(dict, "AccentFillColorSecondaryBrush", hoverColor);
        UpdateBrush(dict, "AccentFillColorTertiaryBrush", pressedColor);
        UpdateBrush(dict, "AccentFillColorDisabledBrush", disabledColor);
        UpdateBrush(dict, "AccentButtonForeground", GetReadableForeground(color));
        UpdateBrush(dict, "AccentButtonForegroundPointerOver", GetReadableForeground(hoverColor));
        UpdateBrush(dict, "AccentButtonForegroundPressed", GetReadableForeground(pressedColor));

        // 輕量樣式鍵：核取方塊、選項按鈕與切換開關的選取狀態跟隨強調色
        foreach (string key in SelectionAccentKeys)
        {
            UpdateBrush(dict, key, color);
        }

        foreach (string key in SelectionAccentPointerOverKeys)
        {
            UpdateBrush(dict, key, hoverColor);
        }

        foreach (string key in SelectionAccentPressedKeys)
        {
            UpdateBrush(dict, key, pressedColor);
        }

        foreach (string key in SelectionGlyphKeys)
        {
            UpdateBrush(dict, key, GetReadableForeground(color));
        }
    }

    /// <summary>依 WCAG 相對亮度取得對比較高的前景色（黑或白）</summary>
    public static Color GetReadableForeground(Color background)
    {
        double luminance = RelativeLuminance(background);
        return (luminance + 0.05) / 0.05 >= 1.05 / (luminance + 0.05)
            ? Color.FromArgb(255, 0, 0, 0)
            : Color.FromArgb(255, 255, 255, 255);
    }

    /// <summary>將文字色逐步混向白或黑，直到與背景對比達 4.5:1</summary>
    public static Color EnsureTextContrast(Color text, Color background)
    {
        Color target = RelativeLuminance(background) < 0.5 ? Color.FromArgb(255, 255, 255, 255) : Color.FromArgb(255, 0, 0, 0);
        Color result = text;
        for (int step = 1; step <= 20 && ContrastRatio(result, background) < 4.5; step++)
        {
            result = Blend(text, target, step / 20d);
        }

        return result;
    }

    private static Color Blend(Color from, Color to, double amount) =>
        Color.FromArgb(
            255,
            (byte)Math.Round(from.R + ((to.R - from.R) * amount)),
            (byte)Math.Round(from.G + ((to.G - from.G) * amount)),
            (byte)Math.Round(from.B + ((to.B - from.B) * amount)));

    private static double ContrastRatio(Color a, Color b)
    {
        double la = RelativeLuminance(a);
        double lb = RelativeLuminance(b);
        return (Math.Max(la, lb) + 0.05) / (Math.Min(la, lb) + 0.05);
    }

    private static double RelativeLuminance(Color color) =>
        (0.2126 * ToLinear(color.R)) + (0.7152 * ToLinear(color.G)) + (0.0722 * ToLinear(color.B));

    private static double ToLinear(byte channel)
    {
        double value = channel / 255d;
        return value <= 0.03928 ? value / 12.92 : Math.Pow((value + 0.055) / 1.055, 2.4);
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
