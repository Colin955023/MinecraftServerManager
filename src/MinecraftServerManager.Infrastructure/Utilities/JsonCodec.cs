using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Serialization.Metadata;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Serialization;

namespace MinecraftServerManager.Infrastructure.Utilities;

/// <summary>JSON 共用入口；無法解析時回傳預設值</summary>
public static class JsonCodec
{
    public const long DefaultMaxBytes = 2L * 1024 * 1024;

    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(JsonCodec));

    private static readonly AppJsonSerializerContext DefaultContext = AppJsonSerializerContext.Default;

    private static readonly JsonSerializerOptions IndentedOptions = new(DefaultContext.Options)
    {
        WriteIndented = true,
    };

    private static readonly AppJsonSerializerContext IndentedContext = new(IndentedOptions);

    private static readonly AppJsonSerializerContext RelaxedContext = new(new JsonSerializerOptions(IndentedOptions)
    {
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    });

    public static JsonDocument ParseDocument(string json, JsonDocumentOptions options = default) =>
        JsonDocument.Parse(json, options);

    public static JsonDocument ParseDocument(ReadOnlyMemory<byte> utf8Json, JsonDocumentOptions options = default) =>
        JsonDocument.Parse(utf8Json, options);

    public static Task<JsonDocument> ParseDocumentAsync(
        Stream utf8Json,
        JsonDocumentOptions options = default,
        CancellationToken cancellationToken = default) =>
        JsonDocument.ParseAsync(utf8Json, options, cancellationToken);

    public static string Serialize<T>(T? value, bool indented = false) =>
        value is null ? "null" : TryJson<T, (T value, bool indented), string>((value, indented), static s => JsonSerializer.Serialize(s.value, GetTypeInfo<T>(s.indented ? IndentedContext : DefaultContext))) ?? string.Empty;

    /// <summary>以寬鬆跳脫（保留中文等非 ASCII 字元）縮排序列化，供匯出檔案使用</summary>
    public static string SerializeRelaxed<T>(T? value) =>
        value is null ? "null" : TryJson<T, T, string>(value, static v => JsonSerializer.Serialize(v, GetTypeInfo<T>(RelaxedContext))) ?? string.Empty;

    public static byte[]? SerializeToUtf8Bytes<T>(T? value, bool indented = false) =>
        value is null ? "null"u8.ToArray() : TryJson<T, (T value, bool indented), byte[]>((value, indented), static s => JsonSerializer.SerializeToUtf8Bytes(s.value, GetTypeInfo<T>(s.indented ? IndentedContext : DefaultContext)));

    public static T? Deserialize<T>(ReadOnlySpan<byte> utf8Json)
    {
        try
        {
            return JsonSerializer.Deserialize(utf8Json, GetTypeInfo<T>(DefaultContext));
        }
        catch (Exception ex) when (ex is JsonException or NotSupportedException)
        {
            Logger.Warning(ex, "JSON 反序列化失敗，型別: {Type}", typeof(T).Name);
            return default;
        }
    }

    public static T? Deserialize<T>(string? json) =>
        string.IsNullOrWhiteSpace(json) ? default : TryJson<T, string, T>(json, static j => JsonSerializer.Deserialize(j, GetTypeInfo<T>(DefaultContext)));

    /// <summary>讀檔並反序列化；超過大小上限或無法解析回傳 null，檔案不存在則擲出</summary>
    public static T? ReadFile<T>(string filePath, long maxBytes = DefaultMaxBytes)
    {
        using var stream = SafeFileSystem.OpenRead(filePath);
        if (!HasReadableLength(stream, maxBytes, filePath))
        {
            return default;
        }

        return TryJson<T, Stream, T>(stream, static s => JsonSerializer.Deserialize(s, GetTypeInfo<T>(DefaultContext)), filePath);
    }

    /// <summary>檔案不存在回傳 null；超過上限、無法解析或讀取失敗回傳 null 並記錄警告</summary>
    public static T? TryReadFile<T>(string filePath, long maxBytes = DefaultMaxBytes)
    {
        try
        {
            return SafeFileSystem.FileExists(filePath) ? ReadFile<T>(filePath, maxBytes) : default;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "讀取 JSON 檔案失敗: {Path}", filePath);
            return default;
        }
    }

    /// <summary>嘗試讀取 JSON 檔案；若檔案存在但內容無法解析或損毀，自動將損毀檔案備份為 .bad 並回傳 default</summary>
    public static T? TryReadOrPreserveCorrupt<T>(string filePath, long maxBytes = DefaultMaxBytes)
    {
        if (string.IsNullOrWhiteSpace(filePath) || !SafeFileSystem.FileExists(filePath))
        {
            return default;
        }

        try
        {
            byte[]? bytes = SafeFileSystem.ReadRegularFile(filePath, maxBytes);
            if (bytes is null)
            {
                Logger.Warning("JSON 檔案無法安全讀取或超過大小限制，嘗試備份損毀檔: {Path}", filePath);
                SafeFileSystem.TryPreserveCorruptFile(filePath, Logger);
                return default;
            }

            var result = Deserialize<T>(bytes);
            if (result is null)
            {
                Logger.Warning("JSON 檔案內容無法解析，已備份為 .bad: {Path}", filePath);
                SafeFileSystem.TryPreserveCorruptFile(filePath, Logger);
                return default;
            }

            return result;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Logger.Warning(ex, "讀取 JSON 檔案失敗，保留損毀檔: {Path}", filePath);
            SafeFileSystem.TryPreserveCorruptFile(filePath, Logger);
            return default;
        }
    }

    /// <summary><see cref="ReadFile{T}"/> 的非同步版本</summary>
    public static Task<T?> ReadFileAsync<T>(string filePath, CancellationToken cancellationToken = default) =>
        ReadFileAsync<T>(filePath, DefaultMaxBytes, cancellationToken);

    /// <summary><see cref="ReadFile{T}"/> 的非同步版本</summary>
    public static async Task<T?> ReadFileAsync<T>(string filePath, long maxBytes, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        using var stream = SafeFileSystem.OpenRead(filePath, options: FileOptions.Asynchronous | FileOptions.SequentialScan);
        if (!HasReadableLength(stream, maxBytes, filePath))
        {
            return default;
        }

        try
        {
            return await JsonSerializer.DeserializeAsync(stream, GetTypeInfo<T>(DefaultContext), cancellationToken).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is JsonException or NotSupportedException)
        {
            Logger.Warning(ex, "JSON 反序列化失敗，型別: {Type}，路徑: {Path}", typeof(T).Name, filePath);
            return default;
        }
    }

    /// <summary>檔案非空且未超過大小上限；超過上限時記錄警告</summary>
    private static bool HasReadableLength(Stream stream, long maxBytes, string filePath)
    {
        if (stream.Length > maxBytes)
        {
            Logger.Warning("JSON 檔案超過大小上限 ({Length} > {MaxBytes}): {Path}", stream.Length, maxBytes, filePath);
            return false;
        }

        return stream.Length > 0;
    }

    /// <summary>執行 JSON 操作；失敗（含型別未登錄）記錄型別與來源後回傳預設值，不得無聲失敗</summary>
    private static TResult? TryJson<T, TState, TResult>(TState state, Func<TState, TResult?> operation, string? source = null)
    {
        try
        {
            return operation(state);
        }
        catch (Exception ex) when (ex is JsonException or NotSupportedException)
        {
            Logger.Warning(ex, "JSON 序列化／反序列化失敗，型別: {Type}，來源: {Source}", typeof(T).Name, source ?? "記憶體");
            return default;
        }
    }

    private static JsonTypeInfo<T> GetTypeInfo<T>(AppJsonSerializerContext context) =>
        context.GetTypeInfo(typeof(T)) as JsonTypeInfo<T>
            ?? throw new JsonException($"型別 '{typeof(T).FullName}' 尚未在 AppJsonSerializerContext 中註冊。");
}
