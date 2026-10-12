namespace MinecraftServerManager.Core.Errors;

public sealed class ConfigurationException : InvalidOperationException
{
    public ConfigurationException(string message)
        : base(message)
    {
    }

    public ConfigurationException(string message, Exception innerException)
        : base(message, innerException)
    {
    }
}
