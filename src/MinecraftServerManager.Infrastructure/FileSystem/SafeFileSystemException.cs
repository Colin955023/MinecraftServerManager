namespace MinecraftServerManager.Infrastructure.FileSystem;

public sealed class SafeFileSystemException : IOException
{
    public SafeFileSystemException(string message)
        : base(message)
    {
    }

    public SafeFileSystemException(string message, Exception innerException)
        : base(message, innerException)
    {
    }
}
