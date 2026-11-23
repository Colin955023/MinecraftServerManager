using Microsoft.UI.Xaml;
using MinecraftServerManager.App.Controls;
using MinecraftServerManager.App.Services;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>管理 Java 環境視窗</summary>
public sealed partial class ManageJavaWindow : Window
{
    public ManageJavaWindow(ManageJavaViewModel viewModel)
    {
        ArgumentNullException.ThrowIfNull(viewModel);
        ViewModel = viewModel;
        InitializeComponent();
        ModalWindowHost.AttachDialog(this, "管理 Java 環境", 820, 620, Bindings.StopTracking, ViewModel, sortTargets: HeaderSort);
    }

    public ManageJavaViewModel ViewModel { get; }

    public ITableSortTarget HeaderSort => field ??= new TableSortTarget<JavaItemViewModel>(() => ViewModel.InstalledJavas, TableSortKeys.Javas);
}
