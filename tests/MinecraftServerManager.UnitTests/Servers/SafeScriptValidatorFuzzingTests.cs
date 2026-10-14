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
        string dir = CreateTempDirectory();
        try
        {
            var random = new Random(101);
            int[] commonCodePages = [437, 65001, 936, 950, 1252, 28591];
            string[] atPrefixes = ["", "@", "@ "];
            string[] chcpCasings = ["chcp", "CHCP", "Chcp", "ChCp"];
            string[] nulCasings = ["nul", "NUL", "NuL", "nuL"];

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
                string script = Path.Combine(dir, $"safe_{i}.bat");
                File.WriteAllText(script, $"@echo off\r\n{line}\r\n\"C:\\Java\\bin\\java.exe\" -jar server.jar nogui\r\n", Encoding.UTF8);

                bool valid = SafeScriptValidator.ValidateScriptContent(script, dir);
                Assert.True(valid, $"合法 chcp 命令變異應被放行：{line}");
            }
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public void FuzzChcpMaliciousInjections_AllRejected()
    {
        string dir = CreateTempDirectory();
        try
        {
            var random = new Random(202);

            for (int i = 0; i < 1500; i++)
            {
                string op = DangerousOperators[random.Next(DangerousOperators.Length)];
                string cmd = MaliciousCommands[random.Next(MaliciousCommands.Length)];

                string maliciousLine = (i % 6) switch
                {
                    0 => $"chcp 65001 > nul {op} {cmd}",
                    1 => $"chcp 65001 {op} {cmd} > nul",
                    2 => $"chcp 65001 > {cmd}",
                    3 => $"chcp 65001 >> nul",
                    4 => $"chcp 65001 > nul.txt",
                    _ => $"chcp 65001 > nul 2>&1"
                };

                string script = Path.Combine(dir, $"malicious_{i}.bat");
                File.WriteAllText(script, $"@echo off\r\n{maliciousLine}\r\n\"C:\\Java\\bin\\java.exe\" -jar server.jar\r\n", Encoding.UTF8);

                bool valid = SafeScriptValidator.ValidateScriptContent(script, dir);
                Assert.False(valid, $"惡意注入命令必須被攔截：{maliciousLine}");
            }
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public void FuzzScriptContent_RobustnessAndIntegrity_NeverThrowsUnhandledException()
    {
        string dir = CreateTempDirectory();
        try
        {
            var random = new Random(303);
            byte[] buffer = new byte[256];

            for (int i = 0; i < 300; i++)
            {
                random.NextBytes(buffer);
                string randomText = Encoding.UTF8.GetString(buffer);

                string script = Path.Combine(dir, $"fuzz_{i}.bat");
                File.WriteAllText(script, randomText, Encoding.UTF8);

                // 驗證隨機二進位/畸形字元絕不造成未捕捉異常崩潰
                _ = SafeScriptValidator.ValidateScriptContent(script, dir);
            }
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public void FuzzJavaExecutableValidation_NeverThrowsUnhandledException()
    {
        var random = new Random(404);
        string[] samples =
        [
            "", " ", "\0", "C:\\", "java", "java.exe", "javaw.exe",
            "C:\\Program Files\\Java\\bin\\java.exe",
            "C:\\..\\..\\java.exe", "invalid/path\0test",
            new string('a', 500)
        ];

        foreach (string sample in samples)
        {
            bool result = SafeScriptValidator.IsSafeJavaExecutable(sample);
            // 隨機路徑在未真正存在或不安全時應回傳 false，且不崩潰
            Assert.False(string.IsNullOrWhiteSpace(sample) && result);
        }

        for (int i = 0; i < 200; i++)
        {
            int len = random.Next(1, 100);
            char[] chars = new char[len];
            for (int j = 0; j < len; j++)
            {
                chars[j] = (char)random.Next(0, 128);
            }
            string fakePath = new(chars);
            _ = SafeScriptValidator.IsSafeJavaExecutable(fakePath);
        }
    }

    [Fact]
    public void FuzzAbsoluteVsUnqualifiedJava_StrictPolicyEnforced()
    {
        string dir = CreateTempDirectory();
        try
        {
            var random = new Random(505);
            string[] unqualified = ["java", "java.exe", "\"java\"", "\"java.exe\"", "bin\\java.exe", ".\\java.exe", "..\\java.exe"];
            string[] validRoots = ["C:\\Program Files\\Java\\jdk-21\\bin\\java.exe", "D:\\Minecraft\\Java\\bin\\java.exe", "C:\\Microsoft\\jdk-25\\bin\\javaw.exe"];

            // 1. 任何未限定或相對路徑均應被拒絕
            foreach (string unq in unqualified)
            {
                string script = Path.Combine(dir, $"unq_{Guid.NewGuid():N}.bat");
                File.WriteAllText(script, $"@echo off\r\n{unq} -jar server.jar\r\n", Encoding.UTF8);
                Assert.False(SafeScriptValidator.ValidateScriptContent(script, dir), $"未限定 Java 指令必須被拒絕：{unq}");
            }

            // 2. 根目錄化之合規 Java 絕對路徑應被放行
            foreach (string root in validRoots)
            {
                string script = Path.Combine(dir, $"root_{Guid.NewGuid():N}.bat");
                File.WriteAllText(script, $"@echo off\r\n\"{root}\" -jar server.jar\r\n", Encoding.UTF8);
                Assert.True(SafeScriptValidator.ValidateScriptContent(script, dir), $"合法 Java 絕對路徑指令應被放行：{root}");
            }
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    private static string CreateTempDirectory()
    {
        string path = Path.Combine(Path.GetTempPath(), "msm-fuzz-script-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(path);
        return path;
    }
}
