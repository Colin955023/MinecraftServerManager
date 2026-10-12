using System.IO.Compression;
using System.Security.Cryptography;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using Xunit;

namespace MinecraftServerManager.UnitTests;

/// <summary>
/// 輸入解析、安全邊界與隨機模糊化（Fuzzing）強健性測試
/// </summary>
public sealed class InputFuzzingAndBoundarySecurityTests
{
    private static readonly string[] BoundaryPropertyKeys =
    [
        "server-ip",
        "server-port",
        "query.port",
        "rcon.port",
        "management-server-port",
        "management-server-host",
        "max-players",
        "view-distance",
        "simulation-distance",
        "difficulty",
        "gamemode",
        "white-list",
        "online-mode",
        "custom-unknown-property"
    ];

    private static readonly string[] MaliciousPathTraversalPayloads =
    [
        "../secret.txt",
        "..\\secret.txt",
        "../../../../boot.ini",
        "..\\..\\..\\..\\Windows\\System32\\calc.exe",
        "sub/../../outside.txt",
        "sub\\..\\..\\outside.txt",
        "/etc/passwd",
        "C:\\Windows\\System32\\cmd.exe",
        "\\\\192.168.1.1\\share\\evil.dll",
        "..%2f..%2fsecret.txt",
        "..%5c..%5csecret.txt",
        ".%2e/.%2e/secret.txt"
    ];

    [Fact]
    public void ServerPropertiesValidator_WithRandomFuzzedInputs_NeverThrowsUnhandledException()
    {
        for (int i = 0; i < 200; i++)
        {
            foreach (string key in BoundaryPropertyKeys)
            {
                string fuzzedValue = GenerateRandomFuzzedString(i);
                var (isValid, error) = ServerPropertiesValidator.ValidateProperty(key, fuzzedValue, "default");

                if (!isValid)
                {
                    Assert.NotNull(error);
                    Assert.NotEmpty(error);
                }
            }
        }
    }

    [Fact]
    public void ServerPropertiesValidator_WithExtremeNumberBoundaries_HandlesGracefully()
    {
        string[] extremeValues =
        [
            "-9223372036854775809",
            "-9223372036854775808",
            "-2147483649",
            "-2147483648",
            "-1",
            "0",
            "1",
            "65534",
            "65535",
            "65536",
            "2147483647",
            "2147483648",
            "9223372036854775807",
            "9223372036854775808",
            "9999999999999999999999999999999999999999"
        ];

        foreach (string val in extremeValues)
        {
            var (portValid, _) = ServerPropertiesValidator.ValidateProperty("server-port", val, "25565");
            if (val is "1" or "65534")
            {
                Assert.True(portValid);
            }
            else
            {
                Assert.False(portValid);
            }

            var (playersValid, _) = ServerPropertiesValidator.ValidateProperty("max-players", val, "20");
            if (int.TryParse(val, out int p) && p >= 0)
            {
                Assert.True(playersValid);
            }
            else
            {
                Assert.False(playersValid);
            }
        }
    }

    [Fact]
    public void SafeFileSystem_PathContainment_RejectsAllTraversalPayloads()
    {
        string baseDir = Path.Combine(Path.GetTempPath(), "mc_fuzz_base_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(baseDir);

        try
        {
            foreach (string payload in MaliciousPathTraversalPayloads)
            {
                string targetPath = Path.Combine(baseDir, payload);
                bool isWithin = SafeFileSystem.IsPathWithin(baseDir, targetPath);

                // 若 payload 嘗試脫離 baseDir，IsPathWithin 必須判定為 false
                string normalizedTarget = Path.GetFullPath(targetPath);
                string normalizedBase = Path.GetFullPath(baseDir);
                bool actuallyWithin = normalizedTarget.StartsWith(normalizedBase, StringComparison.OrdinalIgnoreCase);

                if (!actuallyWithin)
                {
                    Assert.False(isWithin, $"路徑穿越未被攔截：{payload}");
                }
            }
        }
        finally
        {
            if (Directory.Exists(baseDir))
            {
                Directory.Delete(baseDir, recursive: true);
            }
        }
    }

    private static readonly string[] ZipSlipPayloads =
    [
        "../secret.txt",
        "..\\secret.txt",
        "../../../../boot.ini",
        "..\\..\\..\\..\\Windows\\System32\\calc.exe",
        "sub/../../outside.txt",
        "sub\\..\\..\\outside.txt",
        "/outside.txt",
        "\\outside.txt",
        "C:/outside.txt",
        "CON",
        "AUX",
        "NUL",
        "sub/../outside.txt"
    ];

    [Fact]
    public void SafeZipArchive_WithFuzzedZipSlipEntries_RejectsExtraction()
    {
        string tempDir = Path.Combine(Path.GetTempPath(), "mc_fuzz_zip_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(tempDir);

        try
        {
            foreach (string traversalName in ZipSlipPayloads)
            {
                string zipPath = Path.Combine(tempDir, "malicious_" + Guid.NewGuid().ToString("N") + ".zip");
                string extractDest = Path.Combine(tempDir, "extract_" + Guid.NewGuid().ToString("N"));

                using (var archive = ZipFile.Open(zipPath, ZipArchiveMode.Create))
                {
                    var entry = archive.CreateEntry(traversalName);
                    using var writer = new StreamWriter(entry.Open());
                    writer.Write("pwned");
                }

                Assert.Throws<SafeArchiveException>(() => SafeZipArchive.Extract(zipPath, extractDest));
            }
        }
        finally
        {
            if (Directory.Exists(tempDir))
            {
                Directory.Delete(tempDir, recursive: true);
            }
        }
    }

    [Fact]
    public void PropertiesDocumentCodec_MutationFuzzing_DoesNotHangOrCrash()
    {
        string baseTemplate = "server-port=25565\nmotd=A\\ Minecraft\\:\\ Server\\u0021\ndifficulty:normal\nallow-flight=true\n";

        for (int i = 0; i < 100; i++)
        {
            string mutated = MutatePropertiesString(baseTemplate, i);
            var result = PropertiesDocumentCodec.Parse(mutated);
            Assert.NotNull(result);
        }
    }

    [Fact]
    public void SafeZipArchive_CorruptedArchiveFuzzing_GracefullyRejects()
    {
        string tempDir = Path.Combine(Path.GetTempPath(), "mc_corrupt_zip_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(tempDir);

        try
        {
            for (int i = 0; i < 20; i++)
            {
                string corruptPath = Path.Combine(tempDir, $"corrupted_{i}.zip");
                string destDir = Path.Combine(tempDir, $"out_{i}");

                // 產生畸形或截斷的 ZIP 位元組
                byte[] garbage = new byte[64 + (i * 10)];
                RandomNumberGenerator.Fill(garbage);
                // 偶爾寫入合法的 PK 標頭但後面接著垃圾
                if (i % 2 == 0)
                {
                    garbage[0] = 0x50; // 'P'
                    garbage[1] = 0x4B; // 'K'
                    garbage[2] = 0x03;
                    garbage[3] = 0x04;
                }

                File.WriteAllBytes(corruptPath, garbage);

                Assert.ThrowsAny<Exception>(() => SafeZipArchive.Extract(corruptPath, destDir));
            }
        }
        finally
        {
            if (Directory.Exists(tempDir))
            {
                Directory.Delete(tempDir, recursive: true);
            }
        }
    }

    private static string MutatePropertiesString(string baseText, int seed)
    {
        return (seed % 6) switch
        {
            0 => baseText + new string('\\', 500),
            1 => baseText.Replace("=", ":=") + "\0\r\n\\u9999\\uZZZZ",
            2 => new string('A', 2000) + "=" + new string('B', 2000),
            3 => "\\u00" + Convert.ToHexString(RandomNumberGenerator.GetBytes(8)),
            4 => string.Join('\n', Enumerable.Range(0, 50).Select(static n => $"prop_{n}=" + new string('\\', n))),
            _ => baseText + "\n" + Convert.ToHexString(RandomNumberGenerator.GetBytes(32))
        };
    }

    private static string GenerateRandomFuzzedString(int seed)
    {
        return (seed % 10) switch
        {
            0 => string.Empty,
            1 => new string('A', 5000),
            2 => "\0\t\r\n\\/;:'\"<>!@#$%^&*()_+",
            3 => "127.0.0.1:25565",
            4 => "256.256.256.256",
            5 => "-0",
            6 => "NaN",
            7 => "Infinity",
            8 => "'; DROP TABLE servers; --",
            _ => Convert.ToHexString(RandomNumberGenerator.GetBytes(16))
        };
    }
}
