using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.Domain.Mods;

namespace MinecraftServerManager.App.Views;

/// <summary>模組清單匯出格式選擇對話框；後續流程由 <see cref="ViewModels.ExportModListViewModel"/> 執行</summary>
public sealed partial class ExportModListDialog : ContentDialog
{
    public ExportModListDialog()
    {
        InitializeComponent();
    }

    /// <summary>使用者選取的匯出格式</summary>
    public ModListExportFormat SelectedFormat => FormatButtons.SelectedIndex switch
    {
        1 => ModListExportFormat.Json,
        2 => ModListExportFormat.Html,
        3 => ModListExportFormat.Xlsx,
        _ => ModListExportFormat.Text,
    };
}
