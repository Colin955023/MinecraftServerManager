using System.Text;
using MinecraftServerManager.Domain.Mods;
using Xunit;

namespace MinecraftServerManager.UnitTests.Mods;

public sealed class FlexVersionFuzzingTests
{
    private static readonly string[] MutationTokens =
    [
        "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
        "a", "b", "c", "d", "z", "A", "B", "Z",
        ".", "-", "+", "_", " ", "\t", "\0", "/", "\\", ":", ";",
        "!", "@", "#", "$", "%", "^", "&", "*", "(", ")", "~",
        "繁", "體", "中", "文", "🎮", "🚀", "..", "---", "++", "mc1.21"
    ];

    [Fact]
    public void RobustnessFuzzing_RandomStrings_NeverThrowsUnhandledException()
    {
        var random = new Random(42);

        for (int i = 0; i < 5000; i++)
        {
            int count = random.Next(0, 50);
            var sb = new StringBuilder();
            for (int j = 0; j < count; j++)
            {
                sb.Append(MutationTokens[random.Next(MutationTokens.Length)]);
            }

            string input = sb.ToString();

            // 驗證解析與標準化絕不擲出未捕捉例外
            string normalized = FlexVersion.NormalizeModVersionString(input);
            var version = new FlexVersion(input);
            var versionFromNorm = new FlexVersion(normalized);

            Assert.NotNull(version);
            Assert.NotNull(versionFromNorm);

            int selfCmp = version.CompareTo(version);
            Assert.Equal(0, selfCmp);
        }
    }

    [Fact]
    public void AlgebraicAxiomsFuzzing_ReflexivityAntisymmetryTransitivity_Hold()
    {
        var random = new Random(1337);
        var generated = new List<string> { "", "0", "1", "1.0", "1.0.0", "v1.0", "1.0-alpha", "1.0+build.1" };

        for (int i = 0; i < 300; i++)
        {
            int segments = random.Next(1, 5);
            var parts = new List<string>();
            for (int s = 0; s < segments; s++)
            {
                if (random.Next(2) == 0)
                {
                    parts.Add(random.Next(0, 100).ToString(System.Globalization.CultureInfo.InvariantCulture));
                }
                else
                {
                    parts.Add($"pre{random.Next(0, 10)}");
                }
            }
            string ver = string.Join('.', parts);
            if (random.Next(3) == 0)
            {
                ver += $"-beta.{random.Next(1, 5)}";
            }
            if (random.Next(3) == 0)
            {
                ver += $"+build.{random.Next(1, 100)}";
            }
            generated.Add(ver);
        }

        // 隨機選取三元組測試偏序公理
        for (int i = 0; i < 2000; i++)
        {
            string a = generated[random.Next(generated.Count)];
            string b = generated[random.Next(generated.Count)];
            string c = generated[random.Next(generated.Count)];

            int cmpAB = Math.Sign(FlexVersion.Compare(a, b));
            int cmpBA = Math.Sign(FlexVersion.Compare(b, a));

            // 1. 自反性
            Assert.Equal(0, FlexVersion.Compare(a, a));

            // 2. 反對稱性
            Assert.Equal(-cmpAB, cmpBA);

            // 3. 傳遞性
            int cmpBC = Math.Sign(FlexVersion.Compare(b, c));
            if (cmpAB > 0 && cmpBC > 0)
            {
                Assert.True(FlexVersion.Compare(a, c) > 0);
            }
            else if (cmpAB < 0 && cmpBC < 0)
            {
                Assert.True(FlexVersion.Compare(a, c) < 0);
            }
            else if (cmpAB == 0 && cmpBC == 0)
            {
                Assert.Equal(0, FlexVersion.Compare(a, c));
            }
        }
    }

    [Fact]
    public void BuildMetadataFuzzing_MetadataDoesNotAffectComparison()
    {
        var random = new Random(2024);
        string[] baseVersions = ["1.0.0", "2.15.4", "0.102.0", "15.1.5", "7.0.0"];

        foreach (string b in baseVersions)
        {
            for (int i = 0; i < 50; i++)
            {
                int len = random.Next(1, 20);
                var metaSb = new StringBuilder(len);
                for (int j = 0; j < len; j++)
                {
                    metaSb.Append(MutationTokens[random.Next(MutationTokens.Length)]);
                }
                string meta = metaSb.ToString().Replace('+', '_'); // 避免第二個加號

                string withMeta1 = $"{b}+{meta}";
                string withMeta2 = $"{b}+diff_{i}";

                Assert.Equal(0, FlexVersion.Compare(b, withMeta1));
                Assert.Equal(0, FlexVersion.Compare(withMeta1, withMeta2));
            }
        }
    }

    [Fact]
    public void LeadingZerosFuzzing_ProducesIdenticalOrdering()
    {
        var random = new Random(888);
        for (int i = 0; i < 200; i++)
        {
            int n1 = random.Next(0, 1000);
            int n2 = random.Next(0, 1000);

            string zeros1 = new('0', random.Next(1, 5));
            string zeros2 = new('0', random.Next(1, 5));

            string v1 = $"{n1}.{n2}";
            string v1Padded = $"{zeros1}{n1}.{zeros2}{n2}";

            Assert.Equal(0, FlexVersion.Compare(v1, v1Padded));
        }
    }

    [Fact]
    public void ExtremelyLargeNumbersFuzzing_DoesNotOverflow()
    {
        string large99 = new('9', 150);
        string large100 = "1" + new string('0', 150);

        // 151 位數應大於 150 位數
        Assert.True(FlexVersion.Compare(large100, large99) > 0);
        Assert.True(FlexVersion.Compare(large99, large100) < 0);

        string vA = $"1.0.{large100}";
        string vB = $"1.0.{large99}";
        Assert.True(FlexVersion.Compare(vA, vB) > 0);
    }
}
