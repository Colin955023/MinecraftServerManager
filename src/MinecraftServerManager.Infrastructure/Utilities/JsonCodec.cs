using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Serialization.Metadata;
using MinecraftServerManager.Infrastructure.FileSystem;
using MinecraftServerManager.Infrastructure.Serialization;

namespace MinecraftServerManager.Infrastructure.Utilities;

public sealed record JsonReadResult(JsonDocument Document, byte[] RawBytes) : IDisposable
{
    public void Dispose() => Document.Dispose();
}

public static class JsonCodec
{
    public const long DefaultMaxBytes = 2L * 1024 * 1024;

    public static JsonDocument ParseDocument(string json, JsonDocumentOptions options = default) =>
        JsonDocument.Parse(json, options);

    public static JsonDocument ParseDocument(ReadOnlyMemory<byte> utf8Json, JsonDocumentOptions options = default) =>
        JsonDocument.Parse(utf8Json, options);

    public static JsonDocument ParseDocument(Stream utf8Json, JsonDocumentOptions options = default) =>
        JsonDocument.Parse(utf8Json, options);

    public static Task<JsonDocument> ParseDocumentAsync(
        Stream utf8Json,
        JsonDocumentOptions options = default,
        CancellationToken cancellationToken = default) =>
        JsonDocument.ParseAsync(utf8Json, options, cancellationToken);

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

    private static JsonTypeInfo<T> GetTypeInfo<T>(AppJsonSerializerContext context)
    {
        if (context.GetTypeInfo(typeof(T)) is not JsonTypeInfo<T> typeInfo)
        {
            throw new JsonException($"型別 '{typeof(T).FullName}' 尚未在 AppJsonSerializerContext 中註冊。");
        }

        return typeInfo;
    }

    public static JsonReadResult? ReadJsonWithBytes(string filePath, long maxBytes = DefaultMaxBytes)
    {
        if (string.IsNullOrWhiteSpace(filePath) || maxBytes < 0)
        {
            return null;
        }

        try
        {
            byte[]? bytes = SafeFileSystem.ReadRegularFile(filePath, maxBytes);
            return bytes is null
                ? null
                : new JsonReadResult(ParseDocument(bytes), bytes);
        }
        catch (JsonException)
        {
            return null;
        }
        catch (IOException)
        {
            return null;
        }
        catch (UnauthorizedAccessException)
        {
            return null;
        }
    }

    public static JsonDocument? ReadJson(string filePath, long maxBytes = DefaultMaxBytes)
    {
        if (string.IsNullOrWhiteSpace(filePath) || maxBytes < 0)
        {
            return null;
        }

        try
        {
            byte[]? bytes = SafeFileSystem.ReadRegularFile(filePath, maxBytes);
            return bytes is null ? null : ParseDocument(bytes);
        }
        catch (JsonException)
        {
            return null;
        }
        catch (IOException)
        {
            return null;
        }
        catch (UnauthorizedAccessException)
        {
            return null;
        }
    }

    public static string Serialize<T>(T? value, bool indented = false)
    {
        if (value is null)
        {
            return "null";
        }

        try
        {
            return JsonSerializer.Serialize(value, GetTypeInfo<T>(indented ? IndentedContext : DefaultContext));
        }
        catch (JsonException)
        {
            return string.Empty;
        }
        catch (NotSupportedException)
        {
            return string.Empty;
        }
    }

    public static string Serialize<T>(T? value, JsonTypeInfo<T> jsonTypeInfo)
    {
        if (value is null)
        {
            return "null";
        }

        ArgumentNullException.ThrowIfNull(jsonTypeInfo);
        try
        {
            return JsonSerializer.Serialize(value, jsonTypeInfo);
        }
        catch (JsonException)
        {
            return string.Empty;
        }
        catch (NotSupportedException)
        {
            return string.Empty;
        }
    }

    public static string SerializeRelaxed<T>(T? value)
    {
        if (value is null)
        {
            return "null";
        }

        try
        {
            return JsonSerializer.Serialize(value, GetTypeInfo<T>(RelaxedContext));
        }
        catch (JsonException)
        {
            return string.Empty;
        }
        catch (NotSupportedException)
        {
            return string.Empty;
        }
    }

    public static string SerializeRelaxed<T>(T? value, JsonTypeInfo<T> jsonTypeInfo)
    {
        if (value is null)
        {
            return "null";
        }

        ArgumentNullException.ThrowIfNull(jsonTypeInfo);
        try
        {
            return JsonSerializer.Serialize(value, jsonTypeInfo);
        }
        catch (JsonException)
        {
            return string.Empty;
        }
        catch (NotSupportedException)
        {
            return string.Empty;
        }
    }

    public static byte[]? SerializeToUtf8Bytes<T>(T? value, bool indented = false)
    {
        if (value is null)
        {
            return "null"u8.ToArray();
        }

        try
        {
            return JsonSerializer.SerializeToUtf8Bytes(value, GetTypeInfo<T>(indented ? IndentedContext : DefaultContext));
        }
        catch (JsonException)
        {
            return null;
        }
        catch (NotSupportedException)
        {
            return null;
        }
    }

    public static byte[]? SerializeToUtf8Bytes<T>(T? value, JsonTypeInfo<T> jsonTypeInfo)
    {
        if (value is null)
        {
            return "null"u8.ToArray();
        }

        ArgumentNullException.ThrowIfNull(jsonTypeInfo);
        try
        {
            return JsonSerializer.SerializeToUtf8Bytes(value, jsonTypeInfo);
        }
        catch (JsonException)
        {
            return null;
        }
        catch (NotSupportedException)
        {
            return null;
        }
    }

    public static T? Deserialize<T>(ReadOnlySpan<byte> utf8Json)
    {
        try
        {
            return JsonSerializer.Deserialize(utf8Json, GetTypeInfo<T>(DefaultContext));
        }
        catch (JsonException)
        {
            return default;
        }
        catch (NotSupportedException)
        {
            return default;
        }
    }

    public static T? Deserialize<T>(ReadOnlySpan<byte> utf8Json, JsonTypeInfo<T> jsonTypeInfo)
    {
        ArgumentNullException.ThrowIfNull(jsonTypeInfo);
        try
        {
            return JsonSerializer.Deserialize(utf8Json, jsonTypeInfo);
        }
        catch (JsonException)
        {
            return default;
        }
        catch (NotSupportedException)
        {
            return default;
        }
    }

    public static T? Deserialize<T>(byte[] utf8Json)
    {
        ArgumentNullException.ThrowIfNull(utf8Json);
        return Deserialize<T>(utf8Json.AsSpan());
    }

    public static T? Deserialize<T>(byte[] utf8Json, JsonTypeInfo<T> jsonTypeInfo)
    {
        ArgumentNullException.ThrowIfNull(utf8Json);
        return Deserialize(utf8Json.AsSpan(), jsonTypeInfo);
    }

    public static T? Deserialize<T>(string? json)
    {
        if (string.IsNullOrWhiteSpace(json))
        {
            return default;
        }

        try
        {
            return JsonSerializer.Deserialize(json, GetTypeInfo<T>(DefaultContext));
        }
        catch (JsonException)
        {
            return default;
        }
        catch (NotSupportedException)
        {
            return default;
        }
    }

    public static T? Deserialize<T>(string? json, JsonTypeInfo<T> jsonTypeInfo)
    {
        if (string.IsNullOrWhiteSpace(json))
        {
            return default;
        }

        ArgumentNullException.ThrowIfNull(jsonTypeInfo);
        try
        {
            return JsonSerializer.Deserialize(json, jsonTypeInfo);
        }
        catch (JsonException)
        {
            return default;
        }
        catch (NotSupportedException)
        {
            return default;
        }
    }
}
