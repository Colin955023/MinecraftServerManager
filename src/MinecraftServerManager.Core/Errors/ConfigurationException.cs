namespace MinecraftServerManager.Core.Errors;

/// <summary>應用程式設定無效或無法套用</summary>
public sealed class ConfigurationException : InvalidOperationException
{
    public ConfigurationException()
    {
    }

    public ConfigurationException(string? message)
        : base(message)
    {
    }

    public ConfigurationException(string? message, Exception? innerException)
        : base(message, innerException)
    {
    }
}
