using System.Threading.Channels;

namespace MinecraftServerManager.App.Collections;

/// <summary>主控台記錄行緩衝：有界 Channel，滿載捨棄最舊行，由 UI 計時器批次排出</summary>
public sealed class LogLineBuffer
{
    private readonly Channel<string> _channel;
    private readonly List<string> _reusableBatch = [];

    /// <summary>建立指定容量之記錄行緩衝</summary>
    public LogLineBuffer(int capacity)
    {
        ArgumentOutOfRangeException.ThrowIfLessThan(capacity, 1);
        _channel = Channel.CreateBounded<string>(new BoundedChannelOptions(capacity)
        {
            FullMode = BoundedChannelFullMode.DropOldest,
            SingleReader = true,
            SingleWriter = false,
        });
    }

    public int Count => _channel.Reader.Count;

    /// <summary>寫入一行記錄（任意執行緒）</summary>
    public void Post(string line) => _channel.Writer.TryWrite(line);

    /// <summary>捨棄所有待排出行</summary>
    public void Clear() => Skip(int.MaxValue);

    /// <summary>排出最多 <paramref name="maxLines"/> 行至 <paramref name="destination"/>，回傳行數</summary>
    public int DrainTo(List<string> destination, int maxLines = int.MaxValue)
    {
        ArgumentNullException.ThrowIfNull(destination);
        int taken = 0;
        while (taken < maxLines && _channel.Reader.TryRead(out string? line))
        {
            destination.Add(line);
            taken++;
        }

        return taken;
    }

    /// <summary>排出待處理行至 <paramref name="target"/>，超過高水位時修剪至低水位；回傳是否有新行</summary>
    /// <remarks>待處理行超過高水位時只排出最新的低水位筆數，單次 UI 工作量以高水位為上限</remarks>
    public bool FlushTo(BulkObservableCollection<string> target, int highWatermark, int lowWatermark)
    {
        ArgumentNullException.ThrowIfNull(target);
        ArgumentOutOfRangeException.ThrowIfLessThan(highWatermark, 1);
        ArgumentOutOfRangeException.ThrowIfNegative(lowWatermark);
        ArgumentOutOfRangeException.ThrowIfGreaterThan(lowWatermark, highWatermark);

        int pending = Count;
        int maxLines = highWatermark;
        if (pending > highWatermark)
        {
            // 超量的舊行即使排出也會被修剪，直接捨棄
            Skip(pending - lowWatermark);
            maxLines = lowWatermark;
        }

        try
        {
            if (DrainTo(_reusableBatch, maxLines) == 0)
            {
                return false;
            }

            target.AppendAndTrim(_reusableBatch, highWatermark, lowWatermark);
            return true;
        }
        finally
        {
            _reusableBatch.Clear();
        }
    }

    private void Skip(int count)
    {
        for (int i = 0; i < count && _channel.Reader.TryRead(out _); i++)
        {
        }
    }
}
