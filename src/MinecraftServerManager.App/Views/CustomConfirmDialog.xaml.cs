using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.Services;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 提供標準確認操作之 WinUI 3 原生 ContentDialog
/// </summary>
public sealed partial class CustomConfirmDialog : ContentDialog
{
    public string DialogTitle { get; }
    public string Message { get; }
    public string IconGlyph { get; }

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

        IconGlyph = level switch
        {
            UiMessageLevel.Error => "❌",
            UiMessageLevel.Warning => "⚠️",
            UiMessageLevel.Information => "ℹ️",
            UiMessageLevel.Question or _ => "❓",
        };

        if (level is UiMessageLevel.Error or UiMessageLevel.Warning)
        {
            if (Application.Current.Resources.TryGetValue("DangerButtonStyle", out object? styleObj) && styleObj is Style dangerStyle)
            {
                PrimaryButtonStyle = dangerStyle;
            }
        }
    }
}
