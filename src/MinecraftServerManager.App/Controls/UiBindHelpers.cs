using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;
using MinecraftServerManager.Core.Utilities;
using Windows.UI;

namespace MinecraftServerManager.App.Controls;

/// <summary>
/// 提供 WinUI 3 原生 {x:Bind} 專用之高效能靜態資料繫結轉換函式
/// </summary>
public static class UiBindHelpers
{
    private static readonly Color GreenColor = Color.FromArgb(255, 46, 204, 113);
    private static readonly Color GrayColor = Color.FromArgb(255, 149, 165, 166);
    private static readonly Color RedColor = Color.FromArgb(255, 231, 76, 60);

    private static readonly SolidColorBrush GreenBrush = new(GreenColor);
    private static readonly SolidColorBrush GrayBrush = new(GrayColor);
    private static readonly SolidColorBrush RedBrush = new(RedColor);

    /// <summary>
    /// 布林值轉為可見性（true 為 Visible，false 為 Collapsed）
    /// </summary>
    public static Visibility BoolToVis(bool value) =>
        value ? Visibility.Visible : Visibility.Collapsed;

    /// <summary>
    /// 反轉布林值轉為可見性（true 為 Collapsed，false 為 Visible）
    /// </summary>
    public static Visibility InverseBoolToVis(bool value) =>
        value ? Visibility.Collapsed : Visibility.Visible;

    /// <summary>
    /// 字串為空白字元或 null 轉為 Collapsed，有實質內容轉為 Visible
    /// </summary>
    public static Visibility NullOrWhitespaceToVis(string? value) =>
        string.IsNullOrWhiteSpace(value) ? Visibility.Collapsed : Visibility.Visible;

    /// <summary>
    /// 錯誤狀態筆刷
    /// </summary>
    public static SolidColorBrush ErrorBrush(bool hasError) =>
        hasError ? RedBrush : GrayBrush;

    /// <summary>
    /// 格式化檔案大小為使用者友善單位（B / KiB / MiB / GiB / TiB）
    /// </summary>
    public static string FormatBytes(long bytes) => UnitFormatter.FormatBytes(bytes);

    /// <summary>
    /// 相容狀態字型粗細
    /// </summary>
    public static Windows.UI.Text.FontWeight FormatStatusWeight(bool isRecommended) =>
        isRecommended ? Microsoft.UI.Text.FontWeights.SemiBold : Microsoft.UI.Text.FontWeights.Normal;

    /// <summary>
    /// 相容狀態前景色
    /// </summary>
    public static SolidColorBrush FormatStatusBrush(bool isRecommended) =>
        isRecommended ? GreenBrush : GrayBrush;
}
