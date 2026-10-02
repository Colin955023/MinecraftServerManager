namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 頁面 ViewModel 基礎類別
/// </summary>
public abstract class PageViewModel(string key, string title, string subtitle) : ViewModelBase
{
    public string Key { get; } = key;

    public string Title { get; } = title;

    public string Subtitle { get; } = subtitle;
}
