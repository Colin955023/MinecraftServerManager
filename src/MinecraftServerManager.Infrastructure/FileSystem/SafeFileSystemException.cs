namespace MinecraftServerManager.Infrastructure.FileSystem;

public sealed class SafeFileSystemException : IOException
{
    public SafeFileSystemException()
        : base()
    {
    }

    public SafeFileSystemException(string message)
        : base(message)
    {
    }

    /// <summary><paramref name="isLimitExceeded"/> 表示走訪因超過安全上限而中止</summary>
    public SafeFileSystemException(string message, bool isLimitExceeded)
        : base(message)
    {
        IsLimitExceeded = isLimitExceeded;
    }

    /// <summary>是否因超過項目數或總大小的安全上限而中止</summary>
    public bool IsLimitExceeded { get; }

    public SafeFileSystemException(string message, Exception innerException)
        : base(message, innerException)
    {
    }
}
