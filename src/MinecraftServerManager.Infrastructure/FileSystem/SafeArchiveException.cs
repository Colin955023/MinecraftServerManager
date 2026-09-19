namespace MinecraftServerManager.Infrastructure.FileSystem;

public sealed class SafeArchiveException : IOException
{
    public SafeArchiveException(string message)
        : base(message)
    {
    }

    public SafeArchiveException(string message, Exception innerException)
        : base(message, innerException)
    {
    }
}
