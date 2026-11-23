using System.Text.RegularExpressions;

namespace MinecraftServerManager.App.ViewModels;

/// <summary><c>list</c> 指令輸出的線上玩家快照</summary>
internal sealed record PlayerListSnapshot(string OnlineCount, int? MaxPlayers, string[] Players);

/// <summary>解析伺服器日誌中的玩家清單與進出事件；先以字串包含排除無關行再比對正規表示式</summary>
internal static partial class ServerPlayerLogParser
{
    // 日誌前綴僅由方括號群組組成（如 "[12:00:00] [Server thread/INFO]:"），聊天內容無法偽造
    private const string LogPrefixPattern = @"^\s*(?:\[[^\]]*\]\s*)+:\s*";

    [GeneratedRegex(LogPrefixPattern + @"There are\s+(\d+)(?:\s*(?:of a max(?: of)?|/)\s*(\d+))?\s+players online:?\s*(.*)$", RegexOptions.IgnoreCase)]
    private static partial Regex PlayerListRegex();

    [GeneratedRegex(LogPrefixPattern + @"(\S+) joined the game\s*$", RegexOptions.IgnoreCase)]
    private static partial Regex PlayerJoinRegex();

    [GeneratedRegex(LogPrefixPattern + @"(\S+) left the game\s*$", RegexOptions.IgnoreCase)]
    private static partial Regex PlayerLeaveRegex();

    public static PlayerListSnapshot? TryParsePlayerList(string line)
    {
        if (!line.Contains("players online", StringComparison.OrdinalIgnoreCase)
            || PlayerListRegex().Match(line) is not { Success: true } match)
        {
            return null;
        }

        int? max = int.TryParse(match.Groups[2].ValueSpan, out int parsedMax) ? parsedMax : null;
        string[] players = match.Groups[3].Value.Trim().Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        return new PlayerListSnapshot(match.Groups[1].Value, max, players);
    }

    public static string? TryParseJoin(string line) =>
        line.Contains("joined the game", StringComparison.OrdinalIgnoreCase)
        && PlayerJoinRegex().Match(line) is { Success: true } match
            ? match.Groups[1].Value
            : null;

    public static string? TryParseLeave(string line) =>
        line.Contains("left the game", StringComparison.OrdinalIgnoreCase)
        && PlayerLeaveRegex().Match(line) is { Success: true } match
            ? match.Groups[1].Value
            : null;
}
