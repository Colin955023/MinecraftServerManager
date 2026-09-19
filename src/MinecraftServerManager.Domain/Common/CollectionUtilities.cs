namespace MinecraftServerManager.Domain.Common;

/// <summary>
/// 領域集合高效能公用方法
/// </summary>
internal static class CollectionUtilities
{
    public static IReadOnlyList<T> ToReadOnlyList<T>(IEnumerable<T>? items)
    {
        if (items is null)
        {
            return [];
        }

        if (items is IReadOnlyList<T> { Count: 0 })
        {
            return [];
        }

        if (items is T[] arr)
        {
            return arr.Length == 0 ? [] : (T[])arr.Clone();
        }

        return [.. items];
    }
}
