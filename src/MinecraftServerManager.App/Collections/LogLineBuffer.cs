using System.Threading.Channels;

namespace MinecraftServerManager.App.Collections;

/// <summary>主控台記錄行緩衝：多寫入端、單一讀取端之有界 Channel，滿載時捨棄最舊行，由 UI 計時器批次排出</summary>
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

    /// <summary>目前待排出行數</summary>
    public int Count => _channel.Reader.Count;

    /// <summary>寫入一行記錄（任意執行緒）</summary>
    public void Post(string line) => _channel.Writer.TryWrite(line);

    /// <summary>捨棄所有待排出行</summary>
    public void Clear()
    {
        while (_channel.Reader.TryRead(out _))
        {
        }
    }

    /// <summary>排出最多 <paramref name="maxLines"/> 行並附加至 <paramref name="destination"/>，回傳排出行數</summary>
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

    /// <summary>排出全部待處理行並批次附加至 <paramref name="target"/>；超過高水位時修剪至低水位。回傳是否有新行</summary>
    public bool FlushTo(BulkObservableCollection<string> target, int highWatermark, int lowWatermark)
    {
        ArgumentNullException.ThrowIfNull(target);
        _reusableBatch.Clear();
        if (DrainTo(_reusableBatch) == 0)
        {
            return false;
        }

        target.AppendAndTrim(_reusableBatch, highWatermark, lowWatermark);
        _reusableBatch.Clear();
        return true;
    }
}
