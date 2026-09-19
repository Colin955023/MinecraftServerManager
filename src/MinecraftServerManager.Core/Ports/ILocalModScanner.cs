using MinecraftServerManager.Domain.Mods;

namespace MinecraftServerManager.Core.Ports;

/// <summary>
/// 本地模組目錄掃描與 JAR 詮釋資料抽取抽象介面
/// </summary>
public interface ILocalModScanner
{
    /// <summary>
    /// 掃描指定目錄下之所有 .jar 與 .jar.disabled 檔案
    /// </summary>
    public Task<IReadOnlyList<LocalModInfo>> ScanModsAsync(string modsDirectory, CancellationToken cancellationToken = default);

    /// <summary>
    /// 掃描並解析單一模組 JAR 檔案
    /// </summary>
    public Task<LocalModInfo?> ScanSingleModAsync(string filePath, CancellationToken cancellationToken = default);
}
