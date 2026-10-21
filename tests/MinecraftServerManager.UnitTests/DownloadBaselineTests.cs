using System.Diagnostics;
using System.Net;
using System.Net.Http;
using MinecraftServerManager.Infrastructure.Http;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class DownloadBaselineTests(ITestOutputHelper output)
{
    private const long BatchFileBytes = 64 * 1024;
    private const long LargeFileBytes = 1024 * 1024;

    [Fact]
    public async Task MeasureSequentialDownloadBaselines()
    {
        string root = Path.Combine(Path.GetTempPath(), "msm-download-baseline-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);

        try
        {
            foreach ((int fileCount, int latencyMilliseconds) in new[] { (5, 5), (10, 5) })
            {
                DownloadMeasurement measurement = await MeasureAsync(
                    root,
                    $"{fileCount} files",
                    fileCount,
                    BatchFileBytes,
                    latencyMilliseconds);
                WriteMeasurement(measurement);
            }

            DownloadMeasurement largeFile = await MeasureAsync(root, "1 MiB file", 1, LargeFileBytes, 0);
            WriteMeasurement(largeFile);
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public async Task CompareParallelAndSequentialDownloadBaselines()
    {
        string root = Path.Combine(Path.GetTempPath(), "msm-download-compare-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);

        var sb = new System.Text.StringBuilder();
        try
        {
            sb.AppendLine("=== 多工平行 vs 循序下載基準比對 ===");

            // 1. 小型批次 (5 個檔案，5ms 延遲)
            DownloadMeasurement seq20 = await MeasureAsync(root, "循序 5 檔", 5, BatchFileBytes, 5);
            DownloadMeasurement par20 = await MeasureParallelBatchAsync(root, "平行 5 檔 (4並行)", 5, BatchFileBytes, 5, maxConcurrentDownloads: 4);
            sb.AppendLine(FormatMeasurement(seq20));
            sb.AppendLine(FormatMeasurement(par20));
            string msg20 = string.Format(System.Globalization.CultureInfo.InvariantCulture, "小型批次 (5 檔) 速度提升: {0:F2}x (耗時從 {1:F2}s 降至 {2:F2}s)",
                seq20.Elapsed.TotalSeconds / par20.Elapsed.TotalSeconds,
                seq20.Elapsed.TotalSeconds,
                par20.Elapsed.TotalSeconds);
            sb.AppendLine(msg20);

            // 2. 批次 (10 個檔案，5ms 延遲)
            DownloadMeasurement seq100 = await MeasureAsync(root, "循序 10 檔", 10, BatchFileBytes, 5);
            DownloadMeasurement par100 = await MeasureParallelBatchAsync(root, "平行 10 檔 (4並行)", 10, BatchFileBytes, 5, maxConcurrentDownloads: 4);
            sb.AppendLine(FormatMeasurement(seq100));
            sb.AppendLine(FormatMeasurement(par100));
            string msg100 = string.Format(System.Globalization.CultureInfo.InvariantCulture, "批次 (10 檔) 速度提升: {0:F2}x (耗時從 {1:F2}s 降至 {2:F2}s)",
                seq100.Elapsed.TotalSeconds / par100.Elapsed.TotalSeconds,
                seq100.Elapsed.TotalSeconds,
                par100.Elapsed.TotalSeconds);
            sb.AppendLine(msg100);

            output.WriteLine(sb.ToString());
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    private static async Task<DownloadMeasurement> MeasureAsync(
        string root,
        string scenario,
        int fileCount,
        long fileBytes,
        int latencyMilliseconds)
    {
        using var handler = new DownloadResponseHandler(fileBytes, TimeSpan.FromMilliseconds(latencyMilliseconds));
        using var client = new HttpClient(handler);
        var downloader = new HttpDownloadClient(client, ResolvePublicTestHostAsync);
        using var process = Process.GetCurrentProcess();
        process.Refresh();
        TimeSpan cpuBefore = process.TotalProcessorTime;
        long memoryBefore = process.WorkingSet64;
        long managedMemoryBefore = GC.GetTotalMemory(forceFullCollection: false);
        var stopwatch = Stopwatch.StartNew();

        for (int index = 0; index < fileCount; index++)
        {
            string target = Path.Combine(root, $"{scenario.Replace(' ', '-')}-{index}.bin");
            var result = await downloader.DownloadAsync(new Uri("https://download.example.test/file"), target);
            Assert.True(result.Success, result.Error);
        }

        stopwatch.Stop();
        process.Refresh();
        return new DownloadMeasurement(
            scenario,
            fileCount,
            fileBytes,
            stopwatch.Elapsed,
            process.TotalProcessorTime - cpuBefore,
            process.WorkingSet64 - memoryBefore,
            GC.GetTotalMemory(forceFullCollection: false) - managedMemoryBefore);
    }

    private static async Task<DownloadMeasurement> MeasureParallelBatchAsync(
        string root,
        string scenario,
        int fileCount,
        long fileBytes,
        int latencyMilliseconds,
        int maxConcurrentDownloads = 4)
    {
        using var handler = new DownloadResponseHandler(fileBytes, TimeSpan.FromMilliseconds(latencyMilliseconds));
        using var client = new HttpClient(handler);
        var downloader = new HttpDownloadClient(client, ResolvePublicTestHostAsync);

        using var process = Process.GetCurrentProcess();
        process.Refresh();
        TimeSpan cpuBefore = process.TotalProcessorTime;
        long memoryBefore = process.WorkingSet64;
        long managedMemoryBefore = GC.GetTotalMemory(forceFullCollection: false);
        var stopwatch = Stopwatch.StartNew();

        int[] indices = Enumerable.Range(0, fileCount).ToArray();
        await Parallel.ForEachAsync(indices, new ParallelOptions { MaxDegreeOfParallelism = maxConcurrentDownloads }, async (index, ct) =>
        {
            string target = Path.Combine(root, $"{scenario.Replace(' ', '-')}-{index}.bin");
            var uri = new Uri($"https://download.example.test/file-{index}");
            var result = await downloader.DownloadAsync(uri, target, cancellationToken: ct);
            Assert.True(result.Success, result.Error);
        });

        stopwatch.Stop();
        process.Refresh();
        return new DownloadMeasurement(
            scenario,
            fileCount,
            fileBytes,
            stopwatch.Elapsed,
            process.TotalProcessorTime - cpuBefore,
            process.WorkingSet64 - memoryBefore,
            GC.GetTotalMemory(forceFullCollection: false) - managedMemoryBefore);
    }

    private void WriteMeasurement(DownloadMeasurement measurement)
    {
        string line = FormatMeasurement(measurement);
        output.WriteLine(line);
        Console.WriteLine("[BENCHMARK] " + line);
    }

    private static string FormatMeasurement(DownloadMeasurement measurement)
    {
        double totalMiB = (double)measurement.FileCount * measurement.FileBytes / 1024 / 1024;
        double throughputMiBPerSecond = totalMiB / measurement.Elapsed.TotalSeconds;
        return string.Format(
            System.Globalization.CultureInfo.InvariantCulture,
            "{0}: {1} 檔，{2:F2} MiB，{3:F2} 秒，{4:F2} MiB/s，CPU {5:F0} ms，工作集差 {6} bytes，受控堆積差 {7} bytes",
            measurement.Scenario,
            measurement.FileCount,
            totalMiB,
            measurement.Elapsed.TotalSeconds,
            throughputMiBPerSecond,
            measurement.CpuTime.TotalMilliseconds,
            measurement.WorkingSetDelta,
            measurement.ManagedMemoryDelta);
    }

    private static Task<IPAddress[]> ResolvePublicTestHostAsync(string _, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        return Task.FromResult(new[] { IPAddress.Parse("93.184.216.34") });
    }

    private sealed class DownloadResponseHandler(long contentLength, TimeSpan latency, bool enableRanges = false) : HttpMessageHandler
    {
        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            await Task.Delay(latency, cancellationToken);
            if (enableRanges && request.Headers.Range is { Ranges: { Count: > 0 } ranges })
            {
                var range = ranges.First();
                long from = range.From ?? 0;
                long to = range.To ?? (contentLength - 1);
                long rangeLength = to - from + 1;

                var rangeResponse = new HttpResponseMessage(HttpStatusCode.PartialContent)
                {
                    Content = new StreamContent(new ZeroStream(rangeLength)),
                };
                rangeResponse.Headers.AcceptRanges.Add("bytes");
                rangeResponse.Content.Headers.ContentRange = new System.Net.Http.Headers.ContentRangeHeaderValue(from, to, contentLength);
                rangeResponse.Content.Headers.ContentLength = rangeLength;
                return rangeResponse;
            }

            var response = new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StreamContent(new ZeroStream(contentLength)),
            };
            if (enableRanges)
            {
                response.Headers.AcceptRanges.Add("bytes");
            }
            response.Content.Headers.ContentLength = contentLength;
            return response;
        }
    }

    private sealed class ZeroStream(long length) : Stream
    {
        private long _position;

        public override bool CanRead => true;

        public override bool CanSeek => false;

        public override bool CanWrite => false;

        public override long Length => length;

        public override long Position
        {
            get => _position;
            set => throw new NotSupportedException();
        }

        public override int Read(byte[] buffer, int offset, int count) => Read(buffer.AsSpan(offset, count));

        public override int Read(Span<byte> buffer)
        {
            int bytesToRead = (int)Math.Min(buffer.Length, length - _position);
            buffer[..bytesToRead].Clear();
            _position += bytesToRead;
            return bytesToRead;
        }

        public override ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            cancellationToken.ThrowIfCancellationRequested();
            return ValueTask.FromResult(Read(buffer.Span));
        }

        public override void Flush() => throw new NotSupportedException();

        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();

        public override void SetLength(long value) => throw new NotSupportedException();

        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
    }

    private sealed record DownloadMeasurement(
        string Scenario,
        int FileCount,
        long FileBytes,
        TimeSpan Elapsed,
        TimeSpan CpuTime,
        long WorkingSetDelta,
        long ManagedMemoryDelta);
}
