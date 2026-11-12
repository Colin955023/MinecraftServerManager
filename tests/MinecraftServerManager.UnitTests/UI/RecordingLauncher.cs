using MinecraftServerManager.Core.Ports;

namespace MinecraftServerManager.UnitTests.UI;

/// <summary>測試用外部啟動器：所有操作皆視為成功，並記錄開啟的資料夾、檔案與網址</summary>
internal sealed class RecordingLauncher : IExternalLauncher
{
    public List<string> OpenedFolders { get; } = [];

    public List<string> OpenedFiles { get; } = [];

    public List<string> OpenedUrls { get; } = [];

    public bool OpenFolder(string folderPath)
    {
        OpenedFolders.Add(folderPath);
        return true;
    }

    public bool ShowInFolder(string filePath) => true;

    public bool OpenFile(string filePath, bool isTrusted = false)
    {
        OpenedFiles.Add(filePath);
        return true;
    }

    public bool OpenUrl(string url, bool isTrusted = false)
    {
        OpenedUrls.Add(url);
        return true;
    }
}
