using Microsoft.UI.Xaml;

namespace MinecraftServerManager.App.Controls;

/// <summary>
/// 提供 WinUI 3 原生 {x:Bind} 專用之高效能靜態資料繫結轉換函式
/// </summary>
public static class UiBindHelpers
{
    /// <summary>
    /// 成功狀態文字主題資源鍵
    /// </summary>
    public const string SuccessTextBrushKey = "SuccessTextBrush";

    /// <summary>
    /// 錯誤狀態文字主題資源鍵
    /// </summary>
    public const string DangerTextBrushKey = "DangerTextBrush";

    /// <summary>
    /// 警告狀態文字主題資源鍵
    /// </summary>
    public const string WarningTextBrushKey = "WarningBrush";

    /// <summary>
    /// 次要文字主題資源鍵
    /// </summary>
    public const string MutedTextBrushKey = "MutedTextBrush";

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
    /// 錯誤狀態前景主題資源鍵（搭配 <see cref="ThemeBrush"/> 使用）
    /// </summary>
    public static string ErrorBrushKey(bool hasError) =>
        hasError ? DangerTextBrushKey : MutedTextBrushKey;

    /// <summary>
    /// 相容狀態字型粗細
    /// </summary>
    public static Windows.UI.Text.FontWeight FormatStatusWeight(bool isRecommended) =>
        isRecommended ? Microsoft.UI.Text.FontWeights.SemiBold : Microsoft.UI.Text.FontWeights.Normal;

    /// <summary>
    /// 相容狀態前景主題資源鍵（搭配 <see cref="ThemeBrush"/> 使用）
    /// </summary>
    public static string FormatStatusBrushKey(bool isRecommended) =>
        isRecommended ? SuccessTextBrushKey : MutedTextBrushKey;
}
