namespace MinecraftServerManager.App.ViewModels;

/// <summary>頁面 ViewModel 基礎類別</summary>
public abstract class PageViewModel(string title) : ViewModelBase
{
    public string Title { get; } = title;
}
