using MinecraftServerManager.Core.Utilities;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.Infrastructure.Servers;

public sealed partial class ServerInspector
{
    private static readonly string[] MemoryCandidateScriptNames =
    [
        ServerDefaults.UserJvmArgsFileName,
        ServerDefaults.StartServerBatFileName,
        "start.bat",
        ServerDefaults.RunBatFileName,
        "launch.bat",
        "start.cmd",
        "run.cmd",
        "start.sh",
        "run.sh",
        "launch.sh",
    ];

    private static (int? MaxMb, int? MinMb) TryExtractMemoryFromFile(string filePath)
    {
        try
        {
            int? foundMax = null;
            int? foundMin = null;

            // 單次開啟並以串流長度檢查上限，省去額外的存在與大小查詢
            using var stream = SafeFileSystem.OpenRead(filePath);
            if (stream.Length > MaxMetadataBytes)
            {
                return (null, null);
            }

            using var reader = new StreamReader(stream);
            while (reader.ReadLine() is { } line)
            {
                string trimmed = line.Trim();
                if (trimmed.Length == 0 || trimmed.StartsWith('#') || trimmed.StartsWith("rem ", StringComparison.OrdinalIgnoreCase) || trimmed.StartsWith("::", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                int? xmx = MemoryHelpers.ParseMemorySetting(trimmed, "Xmx");
                if (xmx.HasValue)
                {
                    foundMax = xmx.Value;
                }

                int? xms = MemoryHelpers.ParseMemorySetting(trimmed, "Xms");
                if (xms.HasValue)
                {
                    foundMin = xms.Value;
                }
            }

            return (foundMax, foundMin);
        }
        catch (Exception ex) when (ex is FileNotFoundException or DirectoryNotFoundException)
        {
            return (null, null);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Warning(ex, "讀取檔案記憶體設定失敗 ({Path})", filePath);
            return (null, null);
        }
    }

    /// <summary>先根目錄再第一層子目錄；略過不含啟動腳本的資料目錄</summary>
    private static IEnumerable<string> RootThenSubdirectories(string directory)
    {
        yield return directory;
        foreach (string subDirectory in SafeFileSystem.EnumerateDirectories(directory))
        {
            if (!NonScriptDirectories.Contains(Path.GetFileName(subDirectory)))
            {
                yield return subDirectory;
            }
        }
    }

    private static (int MaxMb, int? MinMb) InspectMemory(string directory)
    {
        try
        {
            // 先找根目錄，再找第一層子目錄
            foreach (string folder in RootThenSubdirectories(directory))
            {
                foreach (string candidate in MemoryCandidateScriptNames)
                {
                    string candidatePath = Path.Combine(folder, candidate);
                    var (parsedMax, parsedMin) = TryExtractMemoryFromFile(candidatePath);
                    if (parsedMax.HasValue)
                    {
                        Logger.Information(
                            "從檔案「{File}」解析到記憶體設定: Max={Max}MB, Min={Min}MB",
                            Path.GetRelativePath(directory, candidatePath),
                            parsedMax.Value,
                            parsedMin);
                        return (parsedMax.Value, parsedMin);
                    }
                }
            }
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            Logger.Warning(ex, "掃描子目錄記憶體設定失敗");
        }

        return (ServerDefaults.DefaultMemoryMaxMb, null);
    }
}
