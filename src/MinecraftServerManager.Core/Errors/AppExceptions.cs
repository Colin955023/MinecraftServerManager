namespace MinecraftServerManager.Core.Errors;

/// <summary>Java 安裝失敗例外</summary>
public sealed class JavaInstallException : Exception
{
    public JavaInstallException()
        : base()
    {
    }

    public JavaInstallException(string message)
        : base(message)
    {
    }

    public JavaInstallException(string message, Exception innerException)
        : base(message, innerException)
    {
    }
}
