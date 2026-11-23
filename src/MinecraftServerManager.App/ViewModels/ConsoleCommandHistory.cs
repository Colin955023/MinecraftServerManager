namespace MinecraftServerManager.App.ViewModels;

/// <summary>主控台指令歷史：略過連續重複、限制筆數，瀏覽時保留未送出的草稿</summary>
internal sealed class ConsoleCommandHistory(int capacity)
{
    private readonly List<string> _items = [];
    private int _index = -1;
    private string _draft = string.Empty;

    /// <summary>記錄已送出的指令並重設瀏覽位置</summary>
    public void Add(string command)
    {
        _draft = string.Empty;
        if (_items.Count == 0 || _items[^1] != command)
        {
            _items.Add(command);
            if (_items.Count > capacity)
            {
                _items.RemoveAt(0);
            }
        }

        _index = _items.Count;
    }

    /// <summary>瀏覽歷史並回傳應顯示的文字；離開歷史時還原草稿，無歷史回傳 null</summary>
    public string? Navigate(bool previous, string currentText)
    {
        if (_items.Count == 0)
        {
            return null;
        }

        if (previous)
        {
            if (_index == -1 || _index == _items.Count)
            {
                _draft = currentText;
                _index = _items.Count - 1;
            }
            else if (_index > 0)
            {
                _index--;
            }

            return _items[_index];
        }

        if (_index >= 0 && _index < _items.Count - 1)
        {
            _index++;
            return _items[_index];
        }

        if (_index == _items.Count - 1)
        {
            _index = _items.Count;
            return _draft;
        }

        return currentText;
    }
}
