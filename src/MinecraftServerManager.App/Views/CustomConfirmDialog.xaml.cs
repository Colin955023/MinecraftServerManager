using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;

namespace MinecraftServerManager.App.Views;

/// <summary>標準確認操作之對話方塊</summary>
public sealed partial class CustomConfirmDialog : ContentDialog
{
    public string DialogTitle { get; }
    public string Message { get; }
    /// <summary>Segoe Fluent Icons 字碼（取自 Glyphs.xaml）</summary>
    public string IconGlyph { get; }

    /// <summary>圖示前景主題資源鍵</summary>
    public string IconBrushKey { get; }

    public CustomConfirmDialog(
        string message,
        string title,
        UiMessageLevel level = UiMessageLevel.Question,
        string primaryButtonText = "確定",
        string? secondaryButtonText = null,
        string closeButtonText = "取消")
    {
        InitializeComponent();

        Message = message;
        DialogTitle = title;
        PrimaryButtonText = primaryButtonText;
        SecondaryButtonText = secondaryButtonText ?? string.Empty;
        CloseButtonText = closeButtonText;

        (string glyphKey, IconBrushKey) = level switch
        {
            UiMessageLevel.Error => ("IconError", UiBindHelpers.DangerTextBrushKey),
            UiMessageLevel.Warning => ("IconWarning", UiBindHelpers.WarningTextBrushKey),
            UiMessageLevel.Information => ("IconInfo", UiBindHelpers.AccentTextBrushKey),
            UiMessageLevel.Question or _ => ("IconQuestion", UiBindHelpers.AccentTextBrushKey),
        };
        IconGlyph = (string)Application.Current.Resources[glyphKey];

        if (level is UiMessageLevel.Error or UiMessageLevel.Warning)
        {
            // DefaultButton=Primary 的視覺狀態會把樣式換回 AccentButtonStyle；危險操作改以取消為預設，Enter 不會直接確認
            DefaultButton = ContentDialogButton.Close;
            if (Application.Current.Resources.TryGetValue("DangerButtonStyle", out object? styleObj) && styleObj is Style dangerStyle)
            {
                PrimaryButtonStyle = dangerStyle;
            }
        }
    }
}
