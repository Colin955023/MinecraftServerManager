using MinecraftServerManager.Core.Mods;
using MinecraftServerManager.Core.Ports;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;

namespace MinecraftServerManager.Infrastructure.Servers;

/// <summary>伺服器 latest.log 尾端讀取服務（限制讀取位元組與行數，去除 ANSI 色碼與 BOM）</summary>
public sealed class ServerLogReader(int maxBytesToRead = ServerLogReader.DefaultMaxBytes, int maxLines = ServerLogReader.DefaultMaxLines) : IServerLogReader
{
    /// <summary>預設讀取尾端位元組上限（2 MB）</summary>
    public const int DefaultMaxBytes = 2 * 1024 * 1024;

    /// <summary>預設讀取行數上限</summary>
    private const int DefaultMaxLines = 2500;

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(ServerLogReader));
    private readonly int _maxBytesToRead = Math.Max(1, maxBytesToRead);
    private readonly int _maxLines = Math.Max(1, maxLines);

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
        string logFile = Path.Combine(serverPath, "logs", "latest.log");
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

    /// <summary>切割尾端文字為行；截斷讀取時捨棄第一行（可能為不完整行），並僅保留最後 maxLines 行</summary>
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
                result.Add(ModHelpers.StripColorAndFormattingCodes(lineSpan.ToString()).TrimStart('﻿'));
            }

            index++;
        }

        return result;
    }
}
