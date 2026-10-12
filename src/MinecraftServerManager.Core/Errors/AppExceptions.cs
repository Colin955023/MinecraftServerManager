namespace MinecraftServerManager.Core.Errors;

/// <summary>
/// 應用程式核心基底例外類別
/// </summary>
public class AppException : Exception
{
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
/// 資料或參數驗證失敗例外
/// </summary>
public sealed class ValidationException : AppException
{
    public ValidationException(string message)
        : base(message)
    {
    }

    public ValidationException(string message, Exception innerException)
        : base(message, innerException)
    {
    }
}

/// <summary>
/// 交易或工作流程執行失敗例外
/// </summary>
public sealed class WorkflowException : AppException
{
    public string? DiagnosticId { get; }

    public WorkflowException(string message, string? diagnosticId = null)
        : base(message)
    {
        DiagnosticId = diagnosticId;
    }

    public WorkflowException(string message, Exception innerException, string? diagnosticId = null)
        : base(message, innerException)
    {
        DiagnosticId = diagnosticId;
    }
}

/// <summary>
/// Java 安裝失敗例外
/// </summary>
public sealed class JavaInstallException : AppException
{
    public int? ExitCode { get; }

    public JavaInstallException(string message, int? exitCode = null)
        : base(message)
    {
        ExitCode = exitCode;
    }

    public JavaInstallException(string message, Exception innerException, int? exitCode = null)
        : base(message, innerException)
    {
        ExitCode = exitCode;
    }
}

