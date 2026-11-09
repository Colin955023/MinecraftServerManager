using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using MinecraftServerManager.App.ViewModels;

namespace MinecraftServerManager.App.Views;

public sealed partial class AboutPreferencesView : UserControl
{
    public AboutPreferencesViewModel? ViewModel
    {
        get => DataContext as AboutPreferencesViewModel;
        set => DataContext = value;
    }

    public AboutPreferencesView()
    {
        InitializeComponent();
        DataContextChanged += (_, _) => Bindings.Update();
    }

    public static string FormatVersion(string version) => $"版本 {version}";

    public static string FormatAuthor(string author) => $"• 開發者：{author}";

    public static string FormatFramework(string framework) => $"• 技術堆疊：{framework}、C# 14";

    private void OnApplyAccentColorClicked(object sender, RoutedEventArgs e)
    {
        ViewModel?.SelectAccentColor(AccentPicker.Color);
        AccentColorFlyout.Hide();
    }

    private void OnCancelAccentColorClicked(object sender, RoutedEventArgs e) => AccentColorFlyout.Hide();
}
