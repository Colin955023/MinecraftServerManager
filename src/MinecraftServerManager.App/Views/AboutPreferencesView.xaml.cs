using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

public sealed partial class AboutPreferencesView : UserControl
{
    public AboutPreferencesView(AboutPreferencesViewModel viewModel)
    {
        ArgumentNullException.ThrowIfNull(viewModel);
        ViewModel = viewModel;
        InitializeComponent();
    }

    public AboutPreferencesViewModel ViewModel { get; }

    public static string FormatVersion(string version) => $"版本 {version}";

    public static string FormatAuthor(string author) => $"• 開發者：{author}";

    public static string FormatFramework(string framework) => $"• 技術堆疊：{framework}、C# 14";

    private void OnApplyAccentColorClicked(object sender, RoutedEventArgs e)
    {
        ViewModel.SelectAccentColor(AccentPicker.Color);
        AccentColorFlyout.Hide();
    }

    /// <summary>每次開啟重設為目前色彩，捨棄上次未套用的調整</summary>
    private void OnAccentColorFlyoutOpening(object sender, object e) => AccentPicker.Color = ViewModel.CurrentAccentColor;

    private void OnCancelAccentColorClicked(object sender, RoutedEventArgs e) => AccentColorFlyout.Hide();
}
