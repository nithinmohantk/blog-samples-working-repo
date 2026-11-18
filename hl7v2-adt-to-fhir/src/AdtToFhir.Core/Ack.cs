using System.Globalization;

namespace AdtToFhir.Core;

/// <summary>Builds the acknowledgement a sender waits for. AA accepted, AE error (resend after a fix), AR rejected.</summary>
public static class Ack
{
    public static string Build(Hl7Message original, string code, string text, DateTimeOffset now)
    {
        Hl7Segment msh = original.First("MSH")!;
        Hl7Delimiters d = original.Delimiters;
        string encoding = msh.Raw(2);
        string stamp = now.ToString("yyyyMMddHHmmsszzz", CultureInfo.InvariantCulture).Replace(":", "", StringComparison.Ordinal);
        // Sender and receiver swap places; the control ID of the original goes back in MSA-2 so the sender can pair them.
        string[] header =
        [
            "MSH", encoding, msh.Raw(5), msh.Raw(6), msh.Raw(3), msh.Raw(4), stamp, "",
            $"ACK{d.Component}{original.TriggerEvent}{d.Component}ACK", $"ACK-{original.ControlId}", msh.Raw(11), msh.Raw(12),
        ];
        string[] acknowledgement = ["MSA", code, original.ControlId, Escape(text, d)];
        return string.Join(d.Field, header) + "\r" + string.Join(d.Field, acknowledgement) + "\r";
    }

    /// <summary>The reverse of unescaping: a delimiter inside free text must not be read as a delimiter.</summary>
    public static string Escape(string text, Hl7Delimiters d)
    {
        System.Text.StringBuilder result = new(text.Length);
        foreach (char c in text)
        {
            if (c == d.Escape) { result.Append(d.Escape).Append('E').Append(d.Escape); }
            else if (c == d.Field) { result.Append(d.Escape).Append('F').Append(d.Escape); }
            else if (c == d.Component) { result.Append(d.Escape).Append('S').Append(d.Escape); }
            else if (c == d.SubComponent) { result.Append(d.Escape).Append('T').Append(d.Escape); }
            else if (c == d.Repetition) { result.Append(d.Escape).Append('R').Append(d.Escape); }
            else if (c is '\r' or '\n') { result.Append(' '); }
            else { result.Append(c); }
        }
        return result.ToString();
    }
}
