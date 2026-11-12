using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Serialization.Metadata;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Logging;
using MinecraftServerManager.Infrastructure.Serialization;

namespace MinecraftServerManager.Infrastructure.Utilities;

/// <summary>
/// JSON 共用入口：一律經 <see cref="AppJsonSerializerContext"/> 來源產生器序列化；內容無法解析時回傳預設值而不擲出
/// （<see cref="ReadFile{T}"/> 系列於檔案不存在或無法開啟時仍會擲出 I/O 例外）
/// </summary>
public static class JsonCodec
{
    private static readonly ComponentLogger Logger = AppLogging.CreateComponentLogger(nameof(JsonCodec));

    public const long DefaultMaxBytes = 2L * 1024 * 1024;

    private static readonly JsonSerializerOptions CompactOptions = new()
    {
        PropertyNamingPolicy = null,
        PropertyNameCaseInsensitive = true,
    };

    private static readonly JsonSerializerOptions IndentedOptions = new(CompactOptions)
    {
        WriteIndented = true,
    };

    private static readonly JsonSerializerOptions RelaxedIndentedOptions = new(IndentedOptions)
    {
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };

    private static readonly AppJsonSerializerContext DefaultContext = new(CompactOptions);
    private static readonly AppJsonSerializerContext IndentedContext = new(IndentedOptions);
    private static readonly AppJsonSerializerContext RelaxedContext = new(RelaxedIndentedOptions);

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
        value is null ? "null" : TrySerialize((value, indented), static s => JsonSerializer.Serialize(s.value, GetTypeInfo<T>(s.indented ? IndentedContext : DefaultContext))) ?? string.Empty;

    /// <summary>以寬鬆跳脫（保留中文等非 ASCII 字元）縮排序列化，供匯出檔案使用</summary>
    public static string SerializeRelaxed<T>(T? value) =>
        value is null ? "null" : TrySerialize(value, static v => JsonSerializer.Serialize(v, GetTypeInfo<T>(RelaxedContext))) ?? string.Empty;

    public static byte[]? SerializeToUtf8Bytes<T>(T? value, bool indented = false) =>
        value is null ? "null"u8.ToArray() : TrySerialize((value, indented), static s => JsonSerializer.SerializeToUtf8Bytes(s.value, GetTypeInfo<T>(s.indented ? IndentedContext : DefaultContext)));

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
        string.IsNullOrWhiteSpace(json) ? default : TrySerialize(json, static j => JsonSerializer.Deserialize(j, GetTypeInfo<T>(DefaultContext)));

    /// <summary>經 SafeFileSystem 安全以串流讀取檔案並反序列化（超過預設大小上限或無法解析時回傳 null）</summary>
    public static T? ReadFile<T>(string filePath, long maxBytes = DefaultMaxBytes)
    {
        using var stream = SafeFileSystem.OpenRead(filePath);
        if (!HasReadableLength(stream, maxBytes, filePath))
        {
            return default;
        }

        return TrySerialize(stream, static s => JsonSerializer.Deserialize(s, GetTypeInfo<T>(DefaultContext)));
    }

    /// <summary><see cref="ReadFile{T}"/> 的非同步版本</summary>
    public static Task<T?> ReadFileAsync<T>(string filePath, CancellationToken cancellationToken = default) =>
        ReadFileAsync<T>(filePath, DefaultMaxBytes, cancellationToken);

    /// <summary><see cref="ReadFile{T}"/> 的非同步版本（可指定檔案大小上限）</summary>
    public static async Task<T?> ReadFileAsync<T>(string filePath, long maxBytes, CancellationToken cancellationToken = default)
    {
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
            Logger.Warning(ex, "JSON 串流反序列化失敗");
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

    private static TResult? TrySerialize<TState, TResult>(TState state, Func<TState, TResult?> operation)
    {
        try
        {
            return operation(state);
        }
        catch (Exception ex) when (ex is JsonException or NotSupportedException)
        {
            // 含型別未登錄於 AppJsonSerializerContext 的情形，不得無聲失敗
            Logger.Warning(ex, "JSON 序列化／反序列化失敗");
            return default;
        }
    }

    private static JsonTypeInfo<T> GetTypeInfo<T>(AppJsonSerializerContext context) =>
        context.GetTypeInfo(typeof(T)) as JsonTypeInfo<T>
            ?? throw new JsonException($"型別 '{typeof(T).FullName}' 尚未在 AppJsonSerializerContext 中註冊。");
}
