// 測試替身僅於測試程序內以反射建立，不參與發布修剪；關閉修剪分析的反射警告
#pragma warning disable CA1852, IL2026, IL2062, IL2067, IL2070, IL2072, IL2075, IL2091
using System.Reflection;

namespace MinecraftServerManager.TestSupport;

/// <summary>
/// 測試用「不做事」服務替身產生器：所有方法立即回傳預設值（Task 回傳已完成、集合回傳空集合、其餘為 default），
/// 用於必填相依與本次測試無關的情境，避免在 src 內保留僅供測試的可選參數。
/// </summary>
internal static class NoOp
{
    public static T Create<T>() where T : class => DispatchProxy.Create<T, NoOpProxy>();

    private class NoOpProxy : DispatchProxy
    {
        protected override object? Invoke(MethodInfo? targetMethod, object?[]? args)
        {
            Type returnType = targetMethod?.ReturnType ?? typeof(void);
            if (returnType == typeof(void))
            {
                return null;
            }

            if (returnType == typeof(Task))
            {
                return Task.CompletedTask;
            }

            if (returnType.IsGenericType && returnType.GetGenericTypeDefinition() == typeof(Task<>))
            {
                Type resultType = returnType.GetGenericArguments()[0];
                return typeof(Task)
                    .GetMethod(nameof(Task.FromResult))!
                    .MakeGenericMethod(resultType)
                    .Invoke(null, [DefaultFor(resultType)]);
            }

            return DefaultFor(returnType);
        }

        private static object? DefaultFor(Type type)
        {
            if (type == typeof(string))
            {
                return string.Empty;
            }

            if (type.IsGenericType)
            {
                Type definition = type.GetGenericTypeDefinition();
                Type[] arguments = type.GetGenericArguments();
                if (definition == typeof(IReadOnlyList<>) || definition == typeof(IReadOnlyCollection<>) || definition == typeof(IEnumerable<>))
                {
                    return Array.CreateInstance(arguments[0], 0);
                }

                if (definition == typeof(IReadOnlyDictionary<,>))
                {
                    return Activator.CreateInstance(typeof(Dictionary<,>).MakeGenericType(arguments));
                }
            }

            return type.IsValueType ? Activator.CreateInstance(type) : null;
        }
    }
}
