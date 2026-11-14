using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.Domain.Mods;

namespace MinecraftServerManager.App.Views;

/// <summary>模組清單匯出格式選擇對話方塊；後續流程由 <see cref="ViewModels.ExportModListViewModel"/> 執行</summary>
public sealed partial class ExportModListDialog : ContentDialog
{
    public ExportModListDialog()
    {
        InitializeComponent();
    }

    /// <summary>使用者選取的匯出格式</summary>
    public ModListExportFormat SelectedFormat
    {
        get
        {
            if (JsonRadio.IsChecked == true)
            {
                return ModListExportFormat.Json;
            }

            if (HtmlRadio.IsChecked == true)
            {
                return ModListExportFormat.Html;
            }

            return XlsxRadio.IsChecked == true ? ModListExportFormat.Xlsx : ModListExportFormat.Text;
        }
    }
}
