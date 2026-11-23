using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Domain.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>latest.log 尾端讀取</summary>
public sealed class ServerLogReader : IServerLogReader
{
    /// <summary>預設讀取尾端位元組上限（2 MB）</summary>
    public const int DefaultMaxBytes = 2 * 1024 * 1024;

    private const int DefaultMaxLines = 2500;

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerLogReader));

    private readonly int _maxBytesToRead;
    private readonly int _maxLines;

    public ServerLogReader(int maxBytesToRead = DefaultMaxBytes, int maxLines = DefaultMaxLines)
    {
        _maxBytesToRead = Math.Max(1, maxBytesToRead);
        _maxLines = Math.Max(1, maxLines);
    }

    public Task<IReadOnlyList<string>> ReadLatestLogTailAsync(string serverPath, CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(serverPath))
        {
            return Task.FromResult<IReadOnlyList<string>>([]);
        }

        return Task.Run<IReadOnlyList<string>>(() => ReadTail(serverPath), cancellationToken);
    }

    private List<string> ReadTail(string serverPath)
    {
        string logFile = Path.Combine(serverPath, ServerDefaults.LogsDirectoryName, ServerDefaults.LatestLogFileName);
        if (!SafeFileSystem.FileExists(logFile))
        {
            return [];
        }

        try
        {
            string text = SafeFileSystem.ReadTailText(logFile, _maxBytesToRead, out bool truncated);
            return text.Length == 0 ? [] : SplitTail(text, truncated);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "讀取歷史 latest.log 失敗");
            return [];
        }
    }

    /// <summary>切行；截斷讀取時捨棄第一行，只保留最後 maxLines 行</summary>
    private List<string> SplitTail(string text, bool truncated)
    {
        // 先計數、再只為保留的行配置字串，避免對 2 MB 尾端的每一行都建立字串
        int total = 0;
        bool lastIsEmpty = false;
        foreach (var lineSpan in text.AsSpan().EnumerateLines())
        {
            total++;
            lastIsEmpty = lineSpan.IsEmpty;
        }

        if (total > 0 && lastIsEmpty && (text.EndsWith('\n') || text.EndsWith('\r')))
        {
            total--;
        }

        int startIndex = truncated && total > 1 ? 1 : 0;
        int first = Math.Max(startIndex, total - _maxLines);

        var result = new List<string>(Math.Max(0, total - first));
        int index = 0;
        foreach (var lineSpan in text.AsSpan().EnumerateLines())
        {
            if (index >= total)
            {
                break;
            }

            if (index >= first)
            {
                // BOM 只可能出現在檔案開頭（第 0 行）
                ReadOnlySpan<char> line = index == 0 && lineSpan.StartsWith('\uFEFF') ? lineSpan[1..] : lineSpan;
                result.Add(ModHelpers.StripColorAndFormattingCodes(line.ToString()));
            }

            index++;
        }

        return result;
    }
}
