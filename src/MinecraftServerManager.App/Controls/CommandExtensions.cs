using System.Windows.Input;

namespace MinecraftServerManager.App.Controls;

/// <summary>命令擴充方法</summary>
internal static class CommandExtensions
{
    /// <summary>可執行時才執行；回傳是否已執行</summary>
    public static bool TryExecute(this ICommand command, object? parameter = null)
    {
        if (!command.CanExecute(parameter))
        {
            return false;
        }

        command.Execute(parameter);
        return true;
    }
}
