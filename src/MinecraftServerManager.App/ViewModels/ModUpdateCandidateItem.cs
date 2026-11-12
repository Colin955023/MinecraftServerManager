using CommunityToolkit.Mvvm.ComponentModel;

namespace MinecraftServerManager.App.ViewModels;

/// <summary>模組更新候選項目檢視模型</summary>
public sealed partial class ModUpdateCandidateItem : ObservableObject
{
    [ObservableProperty]
    public partial bool IsSelected { get; set; } = true;

    public string ModName { get; set; } = string.Empty;
    public string CurrentVersion { get; set; } = string.Empty;
    public string NewVersion { get; set; } = string.Empty;
    public string FileName { get; set; } = string.Empty;
    public string SourcePlatform { get; set; } = "Modrinth";
    public string DownloadUrl { get; set; } = string.Empty;
    public string? ExpectedHash { get; set; }
    public string? HashAlgorithm { get; set; }
    public LocalModRowItem? LocalMod { get; set; }
}
