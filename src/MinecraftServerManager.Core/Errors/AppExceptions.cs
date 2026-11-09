namespace MinecraftServerManager.Core.Errors;

/// <summary>
/// 應用程式核心基底例外類別
/// </summary>
public class AppException : Exception
{
    public AppException()
        : base()
    {
    }

    public AppException(string message)
        : base(message)
    {
    }

    public AppException(string message, Exception innerException)
        : base(message, innerException)
    {
    }
}

/// <summary>
/// Java 安裝失敗例外
/// </summary>
public sealed class JavaInstallException : AppException
{
    public int? ExitCode { get; }

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

    public JavaInstallException(string message, int? exitCode)
        : base(message)
    {
        ExitCode = exitCode;
    }

    public JavaInstallException(string message, Exception innerException, int? exitCode)
        : base(message, innerException)
    {
        ExitCode = exitCode;
    }
}
