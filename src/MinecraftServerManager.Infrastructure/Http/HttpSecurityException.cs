namespace MinecraftServerManager.Infrastructure.Http;

public sealed class HttpSecurityException : InvalidOperationException
{
    public HttpSecurityException(string message)
        : base(message)
    {
    }

    public HttpSecurityException(string message, Exception innerException)
        : base(message, innerException)
    {
    }
}
