using System.Globalization;
using System.Text;

namespace AdtToFhir.Core;

/// <summary>The message could not be read as HL7 v2 at all. The caller answers with a reject, not an error.</summary>
public sealed class Hl7ParseException(string message) : Exception(message);

/// <summary>The four delimiters and the escape character, as the sender declared them in MSH-1 and MSH-2.</summary>
public readonly record struct Hl7Delimiters(char Field, char Component, char Repetition, char Escape, char SubComponent)
{
    public static readonly Hl7Delimiters Standard = new('|', '^', '~', '\\', '&');
}

/// <summary>One segment. Fields, repetitions, components and sub-components are addressed by their HL7 numbers.</summary>
public sealed class Hl7Segment
{
    private readonly string[] _fields;
    private readonly Hl7Delimiters _d;

    internal Hl7Segment(string line, Hl7Delimiters delimiters)
    {
        _d = delimiters;
        string[] parts = line.Split(delimiters.Field);
        Name = parts[0];
        if (Name == "MSH")
        {
            // MSH-1 is the field separator itself, so every later field sits one place further along.
            _fields = new string[parts.Length + 1];
            _fields[0] = "MSH";
            _fields[1] = delimiters.Field.ToString();
            Array.Copy(parts, 1, _fields, 2, parts.Length - 1);
        }
        else
        {
            _fields = parts;
        }
    }

    public string Name { get; }

    /// <summary>The field exactly as sent, escapes and all. Empty when the field is absent.</summary>
    public string Raw(int field) => field < _fields.Length ? _fields[field] : "";

    /// <summary>True when the sender wrote two double quotes, which in HL7 v2 means "delete what you hold".</summary>
    public bool IsExplicitNull(int field) => Raw(field) == "\"\"";

    public int RepetitionCount(int field)
    {
        string raw = Raw(field);
        if (raw.Length == 0 || IsExplicitNull(field)) { return 0; }
        return IsEncodingCharacters(field) ? 1 : raw.Split(_d.Repetition).Length;
    }

    /// <summary>One value, unescaped. Numbers are 1-based as in the standard; repetition is 0-based.</summary>
    public string Value(int field, int component = 1, int subComponent = 1, int repetition = 0)
    {
        string raw = Raw(field);
        if (raw.Length == 0 || IsExplicitNull(field)) { return ""; }
        if (IsEncodingCharacters(field)) { return raw; }
        string[] repetitions = raw.Split(_d.Repetition);
        if (repetition >= repetitions.Length) { return ""; }
        string[] components = repetitions[repetition].Split(_d.Component);
        if (component > components.Length) { return ""; }
        string[] subComponents = components[component - 1].Split(_d.SubComponent);
        return subComponent > subComponents.Length ? "" : Unescape(subComponents[subComponent - 1]);
    }

    private bool IsEncodingCharacters(int field) => Name == "MSH" && field <= 2;

    /// <summary>Turns the escape sequences of chapter 2 back into the characters they stand for.</summary>
    private string Unescape(string text)
    {
        if (!text.Contains(_d.Escape)) { return text; }
        StringBuilder result = new(text.Length);
        for (int i = 0; i < text.Length; i++)
        {
            if (text[i] != _d.Escape) { result.Append(text[i]); continue; }
            int end = text.IndexOf(_d.Escape, i + 1);
            if (end < 0) { result.Append(text, i, text.Length - i); break; }   // a lone escape character: keep what was sent
            string code = text[(i + 1)..end];
            switch (code)
            {
                case "F": result.Append(_d.Field); break;
                case "S": result.Append(_d.Component); break;
                case "T": result.Append(_d.SubComponent); break;
                case "R": result.Append(_d.Repetition); break;
                case "E": result.Append(_d.Escape); break;
                case ".br": result.Append('\n'); break;
                default:
                    if (code.Length > 1 && code[0] == 'X' && code.Length % 2 == 1 && code.Skip(1).All(Uri.IsHexDigit))
                    {
                        byte[] bytes = Convert.FromHexString(code.AsSpan(1));
                        result.Append(Encoding.UTF8.GetString(bytes));
                    }
                    // Anything else is formatting (\H\, \N\, \.sp\ and so on) with no place in a FHIR string: dropped.
                    break;
            }
            i = end;
        }
        return result.ToString();
    }
}

/// <summary>A parsed message. It keeps every segment, including the ones nothing maps, so they can be reported.</summary>
public sealed class Hl7Message
{
    private Hl7Message(Hl7Delimiters delimiters, IReadOnlyList<Hl7Segment> segments)
    {
        Delimiters = delimiters;
        Segments = segments;
    }

    public Hl7Delimiters Delimiters { get; }
    public IReadOnlyList<Hl7Segment> Segments { get; }

    public Hl7Segment? First(string name) => Segments.FirstOrDefault(s => s.Name == name);
    public IEnumerable<Hl7Segment> All(string name) => Segments.Where(s => s.Name == name);

    public string MessageCode => First("MSH")!.Value(9, 1);
    public string TriggerEvent => First("MSH")!.Value(9, 2);
    public string ControlId => First("MSH")!.Value(10);
    public string Version => First("MSH")!.Value(12);

    public static Hl7Message Parse(string text)
    {
        // MLLP wraps a message in 0x0B ... 0x1C 0x0D. A file or a queue may or may not have kept the frame.
        string body = text.Trim('\u000B', '\u001C', '\r', '\n', ' ', '﻿');
        if (body.Length < 8 || !body.StartsWith("MSH", StringComparison.Ordinal))
        {
            throw new Hl7ParseException("The message does not start with an MSH segment.");
        }
        Hl7Delimiters d = new(body[3], body[4], body[5], body[6], body[7]);
        char[] five = [d.Field, d.Component, d.Repetition, d.Escape, d.SubComponent];
        if (five.Distinct().Count() != 5 || five.Any(char.IsLetterOrDigit) || five.Any(char.IsWhiteSpace))
        {
            throw new Hl7ParseException("MSH-1 and MSH-2 do not declare five distinct delimiter characters.");
        }
        List<Hl7Segment> segments = [];
        foreach (string line in body.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries))
        {
            if (line.Length < 3 || !line.Take(3).All(c => char.IsAsciiLetterUpper(c) || char.IsAsciiDigit(c)) || (line.Length > 3 && line[3] != d.Field))
            {
                throw new Hl7ParseException($"Line {segments.Count + 1} is not a segment: '{Shorten(line)}'.");
            }
            segments.Add(new Hl7Segment(line, d));
        }
        Hl7Message message = new(d, segments);
        if (message.ControlId.Length == 0) { throw new Hl7ParseException("MSH-10, the message control ID, is empty."); }
        return message;
    }

    private static string Shorten(string line) => line.Length <= 24 ? line : string.Create(CultureInfo.InvariantCulture, $"{line[..24]}...");
}
