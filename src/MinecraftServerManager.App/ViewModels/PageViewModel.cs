namespace MinecraftServerManager.App.ViewModels;

/// <summary>
/// 頁面 ViewModel 基礎類別
/// </summary>
public abstract class PageViewModel : ViewModelBase
{
    protected PageViewModel(string key, string title, string subtitle)
    {
        Key = key;
        Title = title;
        Subtitle = subtitle;
    }

    public string Key { get; }

    public string Title { get; }

    public string Subtitle { get; }
}
