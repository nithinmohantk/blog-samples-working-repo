using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace ClinicalCoding.Core;

/// <summary>Everything between the model's response and the reviewer's screen.</summary>
public static partial class ResponseGuard
{
    /// <summary>Defence in depth: check the shape again even though the service enforces the schema.</summary>
    public static Extraction Parse(string raw, CodingSubset subset)
    {
        JsonDocument document;
        try
        {
            document = JsonDocument.Parse(raw);
        }
        catch (JsonException ex)
        {
            throw new ShapeException($"not JSON: {ex.Message}");
        }

        using (document)
        {
            JsonElement root = document.RootElement;
            RequireKeys(root, "the document", "conditions", "observations");
            HashSet<string> units = [.. subset.Observations.Select(o => o.Unit), CodingSubset.OtherUnit];
            List<ConditionItem> conditions = [];
            List<ObservationItem> observations = [];

            foreach ((JsonElement item, int index) in Items(root, "conditions"))
            {
                string where = $"conditions[{index}]";
                RequireKeys(item, where, "evidence", "code", "assertion");
                string code = RequireString(item, "code", where);
                string assertion = RequireString(item, "assertion", where);
                if (code != CodingSubset.Uncoded && subset.Condition(code) is null)
                {
                    throw new ShapeException($"{where}: code '{code}' is not in the subset");
                }

                if (!ExtractionSchema.Assertions.Contains(assertion))
                {
                    throw new ShapeException($"{where}: unknown assertion");
                }

                conditions.Add(new ConditionItem(RequireString(item, "evidence", where), code, assertion));
            }

            foreach ((JsonElement item, int index) in Items(root, "observations"))
            {
                string where = $"observations[{index}]";
                RequireKeys(item, where, "evidence", "code", "value", "unit");
                string code = RequireString(item, "code", where);
                string unit = RequireString(item, "unit", where);
                if (subset.Observation(code) is null)
                {
                    throw new ShapeException($"{where}: code '{code}' is not in the subset");
                }

                JsonElement value = item.GetProperty("value");
                if (value.ValueKind != JsonValueKind.Number || !value.TryGetDecimal(out decimal number))
                {
                    throw new ShapeException($"{where}: value must be a number");
                }

                if (!units.Contains(unit))
                {
                    throw new ShapeException($"{where}: unknown unit");
                }

                observations.Add(new ObservationItem(RequireString(item, "evidence", where), code, number, unit));
            }

            return new Extraction(conditions, observations);
        }
    }

    /// <summary>Turns a well-formed response into proposals and stops the ones the note cannot support.</summary>
    public static IReadOnlyList<Proposal> Check(Extraction extraction, string noteText, CodingSubset subset)
    {
        string note = Squash(noteText);
        List<Proposal> proposals = [];
        HashSet<string> seen = [];

        for (int i = 0; i < extraction.Conditions.Count; i++)
        {
            ConditionItem item = extraction.Conditions[i];
            ConditionCode? definition = subset.Condition(item.Code);
            Proposal proposal = new()
            {
                Id = $"c{i + 1}", Kind = "condition", Code = definition?.Code, Display = definition?.Display,
                Assertion = item.Assertion, Evidence = item.Evidence,
            };
            if (definition is null)
            {
                proposal.Flags.Add("no code in the subset fits: code by hand or reject");
            }

            string evidence = Squash(item.Evidence);
            string key = $"condition|{item.Code}|{item.Assertion}|{evidence}";
            if (evidence.Length == 0 || !note.Contains(evidence, StringComparison.Ordinal))
            {
                Stop(proposal, ProposalStatus.Blocked, "the evidence is not text from the note");
            }
            else if (seen.Contains(key))
            {
                Stop(proposal, ProposalStatus.Duplicate, "same item as an earlier one");
            }
            else if (item.Assertion is "absent" or "family_history")
            {
                Stop(proposal, ProposalStatus.NotProposed,
                    item.Assertion == "absent" ? "the note rules this out" : "this is about a relative, not the patient");
            }

            seen.Add(key);
            proposals.Add(proposal);
        }

        for (int i = 0; i < extraction.Observations.Count; i++)
        {
            ObservationItem item = extraction.Observations[i];
            ObservationCode definition = subset.Observation(item.Code)!;
            Proposal proposal = new()
            {
                Id = $"o{i + 1}", Kind = "observation", Code = definition.Code, Display = definition.Display,
                Value = item.Value, Unit = item.Unit, Evidence = item.Evidence,
            };
            string evidence = Squash(item.Evidence);
            string key = $"observation|{item.Code}|{item.Value.ToString(CultureInfo.InvariantCulture)}|{evidence}";
            if (evidence.Length == 0 || !note.Contains(evidence, StringComparison.Ordinal))
            {
                Stop(proposal, ProposalStatus.Blocked, "the evidence is not text from the note");
            }
            else if (!NumbersIn(evidence).Contains(item.Value))
            {
                Stop(proposal, ProposalStatus.Blocked, "the value does not appear in the evidence");
            }
            else if (item.Unit != definition.Unit)
            {
                Stop(proposal, ProposalStatus.Blocked, $"only {definition.Unit} is accepted for this code: enter by hand");
            }
            else if (seen.Contains(key))
            {
                Stop(proposal, ProposalStatus.Duplicate, "same item as an earlier one");
            }
            else if (item.Value < definition.Low || item.Value > definition.High)
            {
                proposal.Flags.Add(string.Create(CultureInfo.InvariantCulture,
                    $"outside the expected range {definition.Low} to {definition.High} {definition.Unit}: check the source"));
            }

            seen.Add(key);
            proposals.Add(proposal);
        }

        return proposals;
    }

    public static string Squash(string text) => string.Join(' ', text.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));

    private static IEnumerable<decimal> NumbersIn(string text) =>
        NumberPattern().Matches(text).Select(m => decimal.Parse(m.Value.Replace(',', '.'), NumberStyles.Number, CultureInfo.InvariantCulture));

    private static void Stop(Proposal proposal, string status, string reason)
    {
        proposal.Status = status;
        proposal.Reasons.Add(reason);
    }

    private static IEnumerable<(JsonElement Item, int Index)> Items(JsonElement root, string name)
    {
        JsonElement array = root.GetProperty(name);
        if (array.ValueKind != JsonValueKind.Array)
        {
            throw new ShapeException($"'{name}' must be an array");
        }

        return array.EnumerateArray().Select((item, index) => (item, index));
    }

    private static void RequireKeys(JsonElement element, string where, params string[] keys)
    {
        if (element.ValueKind != JsonValueKind.Object ||
            !element.EnumerateObject().Select(p => p.Name).Order(StringComparer.Ordinal).SequenceEqual(keys.Order(StringComparer.Ordinal)))
        {
            throw new ShapeException($"{where} must have exactly: {string.Join(", ", keys)}");
        }
    }

    private static string RequireString(JsonElement element, string name, string where) =>
        element.GetProperty(name) is { ValueKind: JsonValueKind.String } value
            ? value.GetString()!
            : throw new ShapeException($"{where}: {name} must be a string");

    [GeneratedRegex(@"\d+(?:[.,]\d+)?")]
    private static partial Regex NumberPattern();
}
