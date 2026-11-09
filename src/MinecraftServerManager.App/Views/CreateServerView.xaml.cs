using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

/// <summary>
/// 建立新伺服器分頁 View
/// </summary>
public sealed partial class CreateServerView : UserControl
{
    public static readonly DependencyProperty ViewModelProperty =
        DependencyProperty.Register(
            nameof(ViewModel),
            typeof(CreateServerViewModel),
            typeof(CreateServerView),
            new PropertyMetadata(null, OnViewModelChanged));

    public CreateServerViewModel? ViewModel
    {
        get => (CreateServerViewModel?)GetValue(ViewModelProperty);
        set => SetValue(ViewModelProperty, value);
    }

    public CreateServerView()
    {
        InitializeComponent();
        DataContextChanged += CreateServerView_DataContextChanged;
    }

    private void CreateServerView_DataContextChanged(FrameworkElement sender, DataContextChangedEventArgs args)
    {
        if (args.NewValue is CreateServerViewModel vm)
        {
            ViewModel = vm;
        }
    }

    private static void OnViewModelChanged(DependencyObject d, DependencyPropertyChangedEventArgs e)
    {
        if (d is CreateServerView view)
        {
            view.Bindings.Update();
        }
    }
}
