using System.Globalization;
using System.Text;
using System.Text.Json;

namespace Desk.Core;

/// <summary>Tool name plus arguments in one canonical form: keys sorted, numbers by value.</summary>
public static class ToolCallFingerprint
{
    public static string Of(string name, JsonElement arguments)
    {
        StringBuilder text = new(name);
        text.Append('|');
        Canonical(arguments, text);
        return text.ToString();
    }

    private static void Canonical(JsonElement element, StringBuilder text)
    {
        switch (element.ValueKind)
        {
            case JsonValueKind.Object:
                text.Append('{');
                foreach (JsonProperty property in element.EnumerateObject().OrderBy(p => p.Name, StringComparer.Ordinal))
                {
                    text.Append(JsonEncodedText.Encode(property.Name)).Append(':');
                    Canonical(property.Value, text);
                    text.Append(',');
                }

                text.Append('}');
                break;
            case JsonValueKind.Array:
                text.Append('[');
                foreach (JsonElement item in element.EnumerateArray())
                {
                    Canonical(item, text);
                    text.Append(',');
                }

                text.Append(']');
                break;
            case JsonValueKind.Number when element.TryGetDecimal(out decimal number):
                text.Append(number.ToString("G29", CultureInfo.InvariantCulture));
                break;
            case JsonValueKind.Undefined:
                text.Append("{}");
                break;
            default:
                text.Append(element.GetRawText());
                break;
        }
    }
}
