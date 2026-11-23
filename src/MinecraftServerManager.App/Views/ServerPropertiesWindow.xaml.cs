using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.App.Views;

/// <summary>伺服器屬性設定視窗</summary>
public sealed partial class ServerPropertiesWindow : Window
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerPropertiesWindow));

    public ServerPropertiesWindow(ServerPropertiesViewModel viewModel)
    {
        ArgumentNullException.ThrowIfNull(viewModel);
        ViewModel = viewModel;
        InitializeComponent();
        ModalWindowHost.AttachDialog(
            this,
            "編輯伺服器屬性",
            760,
            680,
            Bindings.StopTracking,
            ViewModel,
            Logger,
            beforeClose: UnbindBeforeClose);
    }

    public ServerPropertiesViewModel ViewModel { get; }

    private void OnResetItemClicked(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { DataContext: PropertyEditItem item })
        {
            ServerPropertiesViewModel.ResetItem(item);
        }
    }

    /// <summary>關閉前先解除繫結與清單資料來源，避免命令結束時更新已關閉視窗而閃退</summary>
    private void UnbindBeforeClose()
    {
        try
        {
            Bindings.StopTracking();
            PropertiesListView.ItemsSource = null;
        }
        catch (Exception ex)
        {
            Logger.Warning(ex, "關閉伺服器屬性視窗前解除繫結失敗");
        }
    }
}

/// <summary>依伺服器屬性型別選擇對應的編輯控制項範本</summary>
public sealed partial class PropertyEditorTemplateSelector : DataTemplateSelector
{
    public DataTemplate? TextTemplate { get; set; }

    public DataTemplate? BoolTemplate { get; set; }

    public DataTemplate? OptionsTemplate { get; set; }

    protected override DataTemplate? SelectTemplateCore(object item, DependencyObject container)
    {
        if (item is PropertyEditItem prop)
        {
            if (prop.IsOptions)
            {
                return OptionsTemplate;
            }

            if (prop.IsBoolean)
            {
                return BoolTemplate;
            }
        }

        return TextTemplate;
    }
}
