using System.Text.Json;

namespace MinecraftServerManager.Infrastructure.Utilities;

/// <summary>外部 JSON 屬性的型別安全讀取；型別不符視同缺漏，不擲例外</summary>
internal static class JsonElementReader
{
    extension(JsonElement element)
    {
        /// <summary>讀取字串屬性；非物件、缺漏或非字串回傳 null</summary>
        public string? GetStringOrNull(string propertyName) =>
            element.TryGetProperty(propertyName, JsonValueKind.String, out var value) ? value.GetString() : null;

        /// <summary>讀取字串屬性；非物件、缺漏或非字串回傳空字串</summary>
        public string GetStringOrEmpty(string propertyName) =>
            element.GetStringOrNull(propertyName) ?? string.Empty;

        /// <summary>讀取純字串元素；非字串或值為 null 時回傳 null</summary>
        public string? GetStringValue() =>
            element.ValueKind == JsonValueKind.String ? element.GetString() : null;

        /// <summary>讀取整數屬性；非物件、缺漏、非數字或超出 Int32 範圍回傳 null</summary>
        public int? GetInt32OrNull(string propertyName) =>
            element.TryGetProperty(propertyName, JsonValueKind.Number, out var value) && value.TryGetInt32(out int result)
                ? result
                : null;

        /// <summary>讀取布林屬性；非物件、缺漏或非布林回傳 null</summary>
        public bool? GetBooleanOrNull(string propertyName) =>
            element.ValueKind == JsonValueKind.Object
            && element.TryGetProperty(propertyName, out var value)
            && value.ValueKind is JsonValueKind.True or JsonValueKind.False
                ? value.GetBoolean()
                : null;

        /// <summary>取得指定型別的屬性；<paramref name="element"/> 非物件時回傳 false</summary>
        public bool TryGetProperty(string propertyName, JsonValueKind kind, out JsonElement value)
        {
            if (element.ValueKind == JsonValueKind.Object
                && element.TryGetProperty(propertyName, out value)
                && value.ValueKind == kind)
            {
                return true;
            }

            value = default;
            return false;
        }
    }
}
