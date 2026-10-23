using System.Text.Json;
using System.Text.Encodings.Web;
using MinecraftServerManager.Infrastructure.FileSystem;

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
        TypeInfoResolver = Serialization.AppJsonSerializerContext.Default,
    };

    private static readonly JsonSerializerOptions IndentedOptions = new(CompactOptions)
    {
        WriteIndented = true,
    };

    private static readonly JsonSerializerOptions RelaxedIndentedOptions = new(IndentedOptions)
    {
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };

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
        try
        {
            return JsonSerializer.Serialize(value, indented ? IndentedOptions : CompactOptions);
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
        try
        {
            return JsonSerializer.Serialize(value, RelaxedIndentedOptions);
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
        try
        {
            return JsonSerializer.SerializeToUtf8Bytes(value, indented ? IndentedOptions : CompactOptions);
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

    public static T? Deserialize<T>(ReadOnlySpan<byte> utf8Json, JsonSerializerOptions? options = null)
    {
        try
        {
            return JsonSerializer.Deserialize<T>(utf8Json, options ?? CompactOptions);
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

    public static T? Deserialize<T>(byte[] utf8Json, JsonSerializerOptions? options = null)
    {
        ArgumentNullException.ThrowIfNull(utf8Json);
        return Deserialize<T>(utf8Json.AsSpan(), options);
    }

    public static T? Deserialize<T>(string? json)
    {
        if (string.IsNullOrWhiteSpace(json))
        {
            return default;
        }

        try
        {
            return JsonSerializer.Deserialize<T>(json, CompactOptions);
        }
        catch
        {
            return default;
        }
    }
}
