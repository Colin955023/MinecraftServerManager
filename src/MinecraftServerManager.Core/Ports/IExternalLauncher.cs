namespace MinecraftServerManager.Core.Ports;

/// <summary>以系統殼層開啟資料夾、檔案與網址</summary>
public interface IExternalLauncher
{
    /// <summary>以檔案總管開啟資料夾；失敗回傳 false</summary>
    public bool OpenFolder(string folderPath);

    /// <summary>以檔案總管開啟並選取檔案；失敗回傳 false</summary>
    public bool ShowInFolder(string filePath);

    /// <summary>以預設程式開啟檔案；<paramref name="isTrusted"/> 為 false 時僅允許副檔名白名單內之檔案</summary>
    public bool OpenFile(string filePath, bool isTrusted = false);

    /// <summary>以預設瀏覽器開啟網址；一律只允許 HTTP/HTTPS 協定</summary>
    public bool OpenUrl(string url);
}
