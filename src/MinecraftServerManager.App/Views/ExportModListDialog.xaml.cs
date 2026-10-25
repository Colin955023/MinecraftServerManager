using System.Windows;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Domain.Mods;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 模組列表匯出對話方塊（Code-behind 僅負責讀取所選格式與視窗生命週期，匯出流程位於 <see cref="ExportModListViewModel"/>）
/// </summary>
public partial class ExportModListDialog : Window
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger("ExportModListDialog");
    private readonly ExportModListViewModel _viewModel;
    private bool _isExporting;

    public ExportModListDialog(ExportModListViewModel viewModel)
    {
        InitializeComponent();
        _viewModel = viewModel;
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        DialogResult = false;
        Close();
    }

    private async void Export_Click(object sender, RoutedEventArgs e)
    {
        if (_isExporting)
        {
            return;
        }

        _isExporting = true;
        try
        {
            if (await _viewModel.ExportAsync(GetSelectedFormat()).ConfigureAwait(true) && IsLoaded)
            {
                DialogResult = true;
                Close();
            }
        }
        catch (Exception ex)
        {
            Logger.Error(ex, "匯出模組清單失敗: {Message}", ex.Message);
        }
        finally
        {
            _isExporting = false;
        }
    }

    private ModListExportFormat GetSelectedFormat()
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
