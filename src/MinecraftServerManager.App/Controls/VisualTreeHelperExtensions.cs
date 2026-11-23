using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;

namespace MinecraftServerManager.App.Controls;

/// <summary>WinUI 視覺樹走訪共用擴充方法</summary>
internal static class VisualTreeHelperExtensions
{
    /// <summary>從起始節點（含自身）向上搜尋第一個指定型別之視覺祖先</summary>
    public static T? FindAncestor<T>(this DependencyObject? start) where T : DependencyObject
    {
        for (DependencyObject? node = start; node is not null; node = VisualTreeHelper.GetParent(node))
        {
            if (node is T match)
            {
                return match;
            }
        }

        return null;
    }

    /// <summary>從根節點（含自身）深度優先搜尋第一個指定型別之視覺子系</summary>
    public static T? FindDescendant<T>(this DependencyObject? root) where T : DependencyObject
    {
        if (root is null)
        {
            return null;
        }

        if (root is T match)
        {
            return match;
        }

        int count = VisualTreeHelper.GetChildrenCount(root);
        for (int i = 0; i < count; i++)
        {
            var child = VisualTreeHelper.GetChild(root, i);
            if (child is T direct)
            {
                return direct;
            }

            if (child.FindDescendant<T>() is { } found)
            {
                return found;
            }
        }

        return null;
    }

    /// <summary>沿視覺樹向上取得最頂端之 <see cref="UIElement"/> 根節點</summary>
    public static UIElement FindVisualRoot(this UIElement element)
    {
        ArgumentNullException.ThrowIfNull(element);
        UIElement root = element;
        while (VisualTreeHelper.GetParent(root) is UIElement parent)
        {
            root = parent;
        }

        return root;
    }
}
