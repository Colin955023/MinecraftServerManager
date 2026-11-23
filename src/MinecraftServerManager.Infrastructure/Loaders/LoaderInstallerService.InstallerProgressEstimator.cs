using System.Buffers;
using System.Text.RegularExpressions;

namespace MinecraftServerManager.Infrastructure.Loaders;

public sealed partial class LoaderInstallerService
{
    private sealed partial class InstallerProgressEstimator
    {
        private static readonly SearchValues<string> CompletionWords = SearchValues.Create(["successfully installed", "installation complete", "all done"], StringComparison.OrdinalIgnoreCase);
        private static readonly SearchValues<string> PatchingWords = SearchValues.Create(["patching", "remapping", "injecting"], StringComparison.OrdinalIgnoreCase);
        private static readonly SearchValues<string> ProcessingWords = SearchValues.Create(["processor", "processing", "applying"], StringComparison.OrdinalIgnoreCase);
        private static readonly SearchValues<string> DownloadingWords = SearchValues.Create(["downloading", "extracting", "task"], StringComparison.OrdinalIgnoreCase);

        private int _current = 30;

        internal int FeedOutput(string line)
        {
            if (string.IsNullOrWhiteSpace(line))
            {
                return _current;
            }

            // 百分比匹配
            var match = PercentRegex().Match(line);
            if (match.Success && int.TryParse(match.Groups[1].Value, out int pct))
            {
                _current = Math.Max(_current, Math.Min(95, pct));
                return _current;
            }

            ReadOnlySpan<char> text = line;
            if (text.ContainsAny(CompletionWords))
            {
                _current = 98;
            }
            else if (text.ContainsAny(PatchingWords))
            {
                _current = Math.Max(_current, 85);
            }
            else if (text.ContainsAny(ProcessingWords))
            {
                _current = Math.Max(_current, Math.Min(80, _current + 2));
            }
            else if (text.ContainsAny(DownloadingWords))
            {
                _current = Math.Max(_current, Math.Min(65, _current + 1));
            }
            else
            {
                // 持續輸出但未命中特定詞彙時微幅平穩推進
                _current = Math.Min(92, _current + 1);
            }

            return _current;
        }

        [GeneratedRegex(@"(?<!\d)(100|\d{1,2})(?:\.\d+)?\s*%")]
        private static partial Regex PercentRegex();
    }
}
