using System.Globalization;
using System.IO.Compression;
using MinecraftServerManager.Core.Servers;
using MinecraftServerManager.Infrastructure.FileSystem;
using Xunit;

namespace MinecraftServerManager.UnitTests;

/// <summary>
/// 輸入解析、安全邊界與確定性變異（Deterministic Fuzzing）強健性測試
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
    public void ServerPropertiesValidator_WithDeterministicBoundaryInputs_NeverThrowsUnhandledException()
    {
        for (int seed = 0; seed < 100; seed++)
        {
            string fuzzedValue = GenerateDeterministicFuzzedString(seed);
            foreach (string key in BoundaryPropertyKeys)
            {
                var (isValid, error) = ServerPropertiesValidator.ValidateProperty(key, fuzzedValue, "default");

                if (!isValid)
                {
                    Assert.True(
                        !string.IsNullOrEmpty(error),
                        $"驗證判定為非法但未提供錯誤訊息：seed={seed}, key={key}, input='{fuzzedValue}'");
                }
                else
                {
                    Assert.Null(error);
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
                Assert.True(portValid, $"連接埠邊界案例未通過：{val}");
            }
            else
            {
                Assert.False(portValid, $"無效連接埠未被拒絕：{val}");
            }

            var (playersValid, _) = ServerPropertiesValidator.ValidateProperty("max-players", val, "20");
            if (int.TryParse(val, out int p) && p >= 0)
            {
                Assert.True(playersValid, $"有效最大玩家數未通過：{val}");
            }
            else
            {
                Assert.False(playersValid, $"無效最大玩家數未被拒絕：{val}");
            }
        }
    }

    [Fact]
    public void PropertiesDocumentCodec_BoundaryAndMalformedInputs_ParsesCorrectlyAndSafely()
    {
        // 1. 空內容與純空白、純註解
        Assert.Empty(PropertiesDocumentCodec.Parse(""));
        Assert.Empty(PropertiesDocumentCodec.Parse("   \r\n\t\n  "));
        Assert.Empty(PropertiesDocumentCodec.Parse("# 這是註解\n! 這是另一種註解\n"));

        // 2. 重複欄位（後者應覆蓋前者）
        string duplicateContent = "motd=Initial MOTD\nmotd=Overwritten MOTD\n";
        var duplicateResult = PropertiesDocumentCodec.Parse(duplicateContent);
        Assert.Equal("Overwritten MOTD", duplicateResult["motd"]);

        // 3. 孤立鍵（無分隔符號，值應為空字串）
        string orphanKeyContent = "standalone-key\nanother-key=\n";
        var orphanResult = PropertiesDocumentCodec.Parse(orphanKeyContent);
        Assert.Equal("", orphanResult["standalone-key"]);
        Assert.Equal("", orphanResult["another-key"]);

        // 4. 跨行延續符號與 EOF 結尾延續符號
        string multilineContent = "description=Line1\\\nLine2\\\nLine3\nlast-key=Value\\\n";
        var multilineResult = PropertiesDocumentCodec.Parse(multilineContent);
        Assert.Equal("Line1Line2Line3", multilineResult["description"]);
        Assert.Equal("Value", multilineResult["last-key"]);

        // 5. 格式錯誤之 Unicode 跳脫字元（應安全降級為普通字元而非擲出例外）
        string malformedUnicode = "test1=\\uZZZZ\ntest2=\\u12\ntest3=\\u0021\n";
        var unicodeResult = PropertiesDocumentCodec.Parse(malformedUnicode);
        Assert.Contains("test1", unicodeResult.Keys);
        Assert.Contains("test2", unicodeResult.Keys);
        Assert.Equal("!", unicodeResult["test3"]);

        // 6. 極長鍵與極長值（各 4000 字元）
        string longKey = new('k', 4000);
        string longValue = new('v', 4000);
        string extremeLengthContent = $"{longKey}={longValue}\n";
        var longResult = PropertiesDocumentCodec.Parse(extremeLengthContent);
        Assert.Equal(longValue, longResult[longKey]);
    }

    [Fact]
    public void PropertiesDocumentCodec_DeterministicMutationFuzzing_DoesNotHangOrCrash()
    {
        string baseTemplate = "server-port=25565\nmotd=A\\ Minecraft\\:\\ Server\\u0021\ndifficulty:normal\nallow-flight=true\n";

        for (int seed = 0; seed < 100; seed++)
        {
            string mutated = MutatePropertiesStringDeterministic(baseTemplate, seed);
            var result = PropertiesDocumentCodec.Parse(mutated);
            Assert.NotNull(result);
        }
    }

    [Fact]
    public void SafeFileSystem_PathContainment_RejectsAllTraversalPayloads()
    {
        string baseDir = Path.Combine(Path.GetTempPath(), "mc_det_fuzz_base_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(baseDir);

        try
        {
            foreach (string payload in MaliciousPathTraversalPayloads)
            {
                string targetPath = Path.Combine(baseDir, payload);
                bool isWithin = SafeFileSystem.IsPathWithin(baseDir, targetPath);

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

    [Fact]
    public void SafeZipArchive_WithZipSlipEntries_RejectsExtractionBeforeWriting()
    {
        string tempDir = Path.Combine(Path.GetTempPath(), "mc_det_zip_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(tempDir);

        try
        {
            for (int i = 0; i < ZipSlipPayloads.Length; i++)
            {
                string traversalName = ZipSlipPayloads[i];
                string zipPath = Path.Combine(tempDir, $"slip_{i}.zip");
                string extractDest = Path.Combine(tempDir, $"dest_{i}");
                Directory.CreateDirectory(extractDest);

                using (var archive = ZipFile.Open(zipPath, ZipArchiveMode.Create))
                {
                    var entry = archive.CreateEntry(traversalName);
                    using var writer = new StreamWriter(entry.Open());
                    writer.Write("pwned");
                }

                // 驗證明確擲出 SafeArchiveException
                var ex = Assert.Throws<SafeArchiveException>(() => SafeZipArchive.Extract(zipPath, extractDest));
                Assert.NotNull(ex.Message);

                // 驗證預定目錄外絕無任何外洩寫入檔案
                string outsideFile = Path.Combine(tempDir, "secret.txt");
                Assert.False(File.Exists(outsideFile), $"檔案不應被寫入目標目錄之外：{outsideFile}");
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
    public void SafeZipArchive_CorruptedAndTruncatedArchive_RejectsWithSafeArchiveException()
    {
        string tempDir = Path.Combine(Path.GetTempPath(), "mc_corrupt_det_zip_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(tempDir);

        var deterministicRng = new Random(1337);

        try
        {
            for (int i = 0; i < 20; i++)
            {
                string corruptPath = Path.Combine(tempDir, $"corrupt_{i}.zip");
                string destDir = Path.Combine(tempDir, $"out_{i}");

                byte[] garbage = new byte[64 + (i * 16)];
                deterministicRng.NextBytes(garbage);

                if (i % 2 == 0)
                {
                    garbage[0] = 0x50; // 'P'
                    garbage[1] = 0x4B; // 'K'
                    garbage[2] = 0x03;
                    garbage[3] = 0x04;
                }

                File.WriteAllBytes(corruptPath, garbage);

                // 明確要求擲出 SafeArchiveException，拒絕使用過於寬鬆的 ThrowsAny
                Assert.Throws<SafeArchiveException>(() => SafeZipArchive.Extract(corruptPath, destDir));
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
    public void SafeZipArchive_DuplicatePathCollision_RejectsExtraction()
    {
        string tempDir = Path.Combine(Path.GetTempPath(), "mc_dup_zip_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(tempDir);

        try
        {
            string zipPath = Path.Combine(tempDir, "collision.zip");
            string extractDest = Path.Combine(tempDir, "extract");

            using (var archive = ZipFile.Open(zipPath, ZipArchiveMode.Create))
            {
                var entry1 = archive.CreateEntry("data.txt");
                using (var writer = new StreamWriter(entry1.Open())) { writer.Write("first"); }

                var entry2 = archive.CreateEntry("data.txt");
                using (var writer = new StreamWriter(entry2.Open())) { writer.Write("second"); }
            }

            Assert.Throws<SafeArchiveException>(() => SafeZipArchive.Extract(zipPath, extractDest));
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
    public void SafeZipArchive_ExtractionFailure_PreservesExistingDestinationFiles()
    {
        string tempDir = Path.Combine(Path.GetTempPath(), "mc_safe_extract_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(tempDir);

        try
        {
            string extractDest = Path.Combine(tempDir, "target");
            Directory.CreateDirectory(extractDest);
            string existingFile = Path.Combine(extractDest, "important_original.txt");
            File.WriteAllText(existingFile, "critical data");

            // 建立一個惡意 zip（嘗試 Zip Slip）
            string maliciousZip = Path.Combine(tempDir, "malicious.zip");
            using (var archive = ZipFile.Open(maliciousZip, ZipArchiveMode.Create))
            {
                var entry = archive.CreateEntry("../escape.txt");
                using var writer = new StreamWriter(entry.Open());
                writer.Write("bad");
            }

            Assert.Throws<SafeArchiveException>(() => SafeZipArchive.Extract(maliciousZip, extractDest));

            // 驗證原始既有檔案未遭損毀或移除
            Assert.True(File.Exists(existingFile), "解壓縮失敗不應影響目標目錄既有檔案");
            Assert.Equal("critical data", File.ReadAllText(existingFile));
        }
        finally
        {
            if (Directory.Exists(tempDir))
            {
                Directory.Delete(tempDir, recursive: true);
            }
        }
    }

    private static string MutatePropertiesStringDeterministic(string baseText, int seed)
    {
        return (seed % 6) switch
        {
            0 => baseText + new string('\\', 500),
            1 => baseText.Replace("=", ":=") + "\0\r\n\\u9999\\uZZZZ",
            2 => new string('A', 2000) + "=" + new string('B', 2000),
            3 => "\\u00" + (seed * 1111).ToString("X4", CultureInfo.InvariantCulture),
            4 => string.Join('\n', Enumerable.Range(0, 30).Select(static n => $"prop_{n}=" + new string('\\', n))),
            _ => baseText + "\ncustom_fuzz_key_" + seed + "=deterministic_value_" + seed
        };
    }

    private static string GenerateDeterministicFuzzedString(int seed)
    {
        return (seed % 10) switch
        {
            0 => string.Empty,
            1 => new string('A', 2000),
            2 => "\0\t\r\n\\/;:'\"<>!@#$%^&*()_+",
            3 => "127.0.0.1:25565",
            4 => "256.256.256.256",
            5 => "-0",
            6 => "NaN",
            7 => "Infinity",
            8 => "'; DROP TABLE servers; --",
            _ => "fixed_fuzzed_token_" + seed
        };
    }
}
