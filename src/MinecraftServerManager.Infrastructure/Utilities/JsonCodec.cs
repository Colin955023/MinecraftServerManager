using System.Text.Json;
using MinecraftServerManager.Infrastructure.FileSystem;

namespace MinecraftServerManager.Infrastructure.Utilities;

public sealed record JsonReadResult(JsonDocument Document, byte[] RawBytes) : IDisposable
{
    public void Dispose() => Document.Dispose();
}

public static class JsonCodec
{
    public const long DefaultMaxBytes = 2L * 1024 * 1024;

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
                : new JsonReadResult(JsonDocument.Parse(bytes), bytes);
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
            return bytes is null ? null : JsonDocument.Parse(bytes);
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
