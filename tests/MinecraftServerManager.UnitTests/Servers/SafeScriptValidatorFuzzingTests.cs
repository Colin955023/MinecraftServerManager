using System.Text;
using MinecraftServerManager.Infrastructure.Servers;
using Xunit;

namespace MinecraftServerManager.UnitTests.Servers;

public sealed class SafeScriptValidatorFuzzingTests
{
    private static readonly string[] DangerousOperators =
    [
        "&", "&&", "|", "||", ">", ">>", "<", "^", "!", "%TEMP%", "%COMSPEC%", "%~f1", "\0", "\r\n", "\""
    ];

    private static readonly string[] MaliciousCommands =
    [
        "calc", "calc.exe", "notepad", "cmd /c whoami", "powershell -c ls", "format C:", "del /f /q *"
    ];

    [Fact]
    public void FuzzChcpValidVariations_AllAccepted()
    {
        using var dirTemp = new TempDirectory("msm-fuzz-script-");
        string dir = dirTemp.FullName;
        var random = new Random(101);
        int[] commonCodePages = [437, 65001, 936, 950, 1252, 28591];
        string[] atPrefixes = ["", "@", "@ "];
        string[] chcpCasings = ["chcp", "CHCP", "Chcp", "ChCp"];
        string[] nulCasings = ["nul", "NUL", "NuL", "nuL"];

        string script = Path.Combine(dir, "safe.bat");
        for (int i = 0; i < 500; i++)
        {
            string at = atPrefixes[random.Next(atPrefixes.Length)];
            string chcp = chcpCasings[random.Next(chcpCasings.Length)];
            string nul = nulCasings[random.Next(nulCasings.Length)];
            int cp = commonCodePages[random.Next(commonCodePages.Length)];

            string spacesBeforeCp = new(' ', random.Next(1, 4));
            string spacesBeforeGt = new(' ', random.Next(0, 4));
            string spacesAfterGt = new(' ', random.Next(0, 4));

            string line = $"{at}{chcp}{spacesBeforeCp}{cp}{spacesBeforeGt}>{spacesAfterGt}{nul}";
            File.WriteAllText(script, $"@echo off\r\n{line}\r\n\"C:\\Java\\bin\\java.exe\" -jar server.jar nogui\r\n", Encoding.UTF8);

            bool valid = SafeScriptValidator.ValidateScriptContent(script, dir);
            Assert.True(valid, $"合法 chcp 命令變異應被放行：{line}");
        }
    }

    [Fact]
    public void FuzzChcpMaliciousInjections_AllRejected()
    {
        using var dirTemp = new TempDirectory("msm-fuzz-script-");
        string dir = dirTemp.FullName;
        List<string> maliciousLines =
        [
            "chcp 65001 >> nul",
            "chcp 65001 > nul.txt",
            "chcp 65001 > nul 2>&1",
            .. MaliciousCommands.Select(static cmd => $"chcp 65001 > {cmd}"),
            .. DangerousOperators.SelectMany(static op => MaliciousCommands.SelectMany(cmd => new[]
            {
                $"chcp 65001 > nul {op} {cmd}",
                $"chcp 65001 {op} {cmd} > nul",
            })),
        ];

        string script = Path.Combine(dir, "malicious.bat");
        for (int i = 0; i < maliciousLines.Count; i++)
        {
            string maliciousLine = maliciousLines[i];
            File.WriteAllText(script, $"@echo off\r\n{maliciousLine}\r\n\"C:\\Java\\bin\\java.exe\" -jar server.jar\r\n", Encoding.UTF8);

            bool valid = SafeScriptValidator.ValidateScriptContent(script, dir);
            Assert.False(valid, $"惡意注入命令必須被攔截：{maliciousLine}");
        }
    }

    [Fact]
    public void FuzzScriptContent_RobustnessAndIntegrity_RejectsRandomGarbageWithoutThrowing()
    {
        using var dirTemp = new TempDirectory("msm-fuzz-script-");
        string dir = dirTemp.FullName;
        var random = new Random(303);
        byte[] buffer = new byte[256];

        string script = Path.Combine(dir, "fuzz.bat");
        for (int i = 0; i < 300; i++)
        {
            random.NextBytes(buffer);
            string randomText = Encoding.UTF8.GetString(buffer);

            File.WriteAllText(script, randomText, Encoding.UTF8);

            bool valid = SafeScriptValidator.ValidateScriptContent(script, dir);
            Assert.False(valid);
        }
    }

    [Theory]
    [InlineData("")]
    [InlineData(" ")]
    [InlineData("\0")]
    [InlineData("C:\\")]
    [InlineData("java")]
    [InlineData("java.exe")]
    [InlineData("javaw.exe")]
    [InlineData("C:\\Program Files\\NonExistentJavaTestDir\\bin\\java.exe")]
    [InlineData("C:\\..\\..\\java.exe")]
    [InlineData("invalid/path\0test")]
    public void IsSafeJavaExecutable_InvalidOrMissingSample_ReturnsFalse(string sample) =>
        Assert.False(SafeScriptValidator.IsSafeJavaExecutable(sample));

    [Fact]
    public void FuzzJavaExecutableValidation_NeverThrowsUnhandledException()
    {
        Assert.False(SafeScriptValidator.IsSafeJavaExecutable(new string('a', 500)));

        var random = new Random(404);
        for (int i = 0; i < 200; i++)
        {
            int len = random.Next(1, 100);
            char[] chars = new char[len];
            for (int j = 0; j < len; j++)
            {
                chars[j] = (char)random.Next(0, 128);
            }
            string fakePath = new(chars);
            Assert.False(SafeScriptValidator.IsSafeJavaExecutable(fakePath));
        }
    }

    [Theory]
    [InlineData("java", false)]
    [InlineData("java.exe", false)]
    [InlineData("\"java\"", false)]
    [InlineData("\"java.exe\"", false)]
    [InlineData("bin\\java.exe", false)]
    [InlineData(".\\java.exe", false)]
    [InlineData("..\\java.exe", false)]
    [InlineData("\"C:\\Program Files\\Java\\jdk-21\\bin\\java.exe\"", true)]
    [InlineData("\"D:\\Minecraft\\Java\\bin\\java.exe\"", true)]
    [InlineData("\"C:\\Microsoft\\jdk-25\\bin\\javaw.exe\"", true)]
    public void ValidateScriptContent_AbsoluteVsUnqualifiedJava_EnforcesStrictPolicy(string javaCommand, bool expectedValid)
    {
        using var dirTemp = new TempDirectory("msm-fuzz-script-");
        string dir = dirTemp.FullName;
        string script = Path.Combine(dir, "run.bat");
        File.WriteAllText(script, $"@echo off\r\n{javaCommand} -jar server.jar\r\n", Encoding.UTF8);

        Assert.Equal(expectedValid, SafeScriptValidator.ValidateScriptContent(script, dir));
    }
}
