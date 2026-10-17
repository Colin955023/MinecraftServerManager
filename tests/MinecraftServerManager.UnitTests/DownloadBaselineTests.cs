using System.Diagnostics;
using System.Net;
using System.Net.Http;
using MinecraftServerManager.Infrastructure.Http;
using Xunit;

namespace MinecraftServerManager.UnitTests;

public sealed class DownloadBaselineTests(ITestOutputHelper output)
{
    private const long BatchFileBytes = 1024 * 1024;
    private const long LargeFileBytes = 100 * 1024 * 1024;

    [Fact]
    public async Task MeasureSequentialDownloadBaselines()
    {
        string root = Path.Combine(Path.GetTempPath(), "msm-download-baseline-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);

        try
        {
            foreach ((int fileCount, int latencyMilliseconds) in new[] { (20, 15), (100, 15) })
            {
                DownloadMeasurement measurement = await MeasureAsync(
                    root,
                    $"{fileCount} files",
                    fileCount,
                    BatchFileBytes,
                    latencyMilliseconds);
                WriteMeasurement(measurement);
            }

            DownloadMeasurement largeFile = await MeasureAsync(root, "100 MiB file", 1, LargeFileBytes, 0);
            WriteMeasurement(largeFile);
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

    private void WriteMeasurement(DownloadMeasurement measurement)
    {
        double totalMiB = (double)measurement.FileCount * measurement.FileBytes / 1024 / 1024;
        double throughputMiBPerSecond = totalMiB / measurement.Elapsed.TotalSeconds;
        output.WriteLine(
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

    private sealed class DownloadResponseHandler(long contentLength, TimeSpan latency) : HttpMessageHandler
    {
        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            await Task.Delay(latency, cancellationToken);
            var response = new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StreamContent(new ZeroStream(contentLength)),
            };
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
