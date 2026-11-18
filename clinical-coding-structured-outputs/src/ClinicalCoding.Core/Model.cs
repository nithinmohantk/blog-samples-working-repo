using System.Text.Json;

namespace ClinicalCoding.Core;

public sealed record ConditionCode(string Code, string Display, string Hint);

public sealed record ObservationCode(string Code, string Display, string Unit, string Category, decimal Low, decimal High);

/// <summary>The closed set of codes the assistant may propose. Displays come from here, never from the model.</summary>
public sealed class CodingSubset
{
    public const string Uncoded = "uncoded";
    public const string OtherUnit = "other";

    public required IReadOnlyList<ConditionCode> Conditions { get; init; }
    public required IReadOnlyList<ObservationCode> Observations { get; init; }

    public ConditionCode? Condition(string? code) => Conditions.FirstOrDefault(c => c.Code == code);
    public ObservationCode? Observation(string? code) => Observations.FirstOrDefault(o => o.Code == code);

    public static CodingSubset Load(string path)
    {
        using JsonDocument document = JsonDocument.Parse(File.ReadAllText(path));
        JsonElement root = document.RootElement;
        return new CodingSubset
        {
            Conditions = [.. root.GetProperty("conditions").EnumerateArray().Select(c => new ConditionCode(
                c.GetProperty("code").GetString()!, c.GetProperty("display").GetString()!, c.GetProperty("hint").GetString()!))],
            Observations = [.. root.GetProperty("observations").EnumerateArray().Select(o => new ObservationCode(
                o.GetProperty("code").GetString()!, o.GetProperty("display").GetString()!, o.GetProperty("unit").GetString()!,
                o.GetProperty("category").GetString()!, o.GetProperty("low").GetDecimal(), o.GetProperty("high").GetDecimal()))],
        };
    }
}

public sealed record ConditionItem(string Evidence, string Code, string Assertion);

public sealed record ObservationItem(string Evidence, string Code, decimal Value, string Unit);

public sealed record Extraction(IReadOnlyList<ConditionItem> Conditions, IReadOnlyList<ObservationItem> Observations);

public static class ProposalStatus
{
    public const string ForReview = "for_review";
    public const string NotProposed = "not_proposed";
    public const string Blocked = "blocked";
    public const string Duplicate = "duplicate";
}

/// <summary>One item a reviewer may be shown. Only <see cref="ProposalStatus.ForReview"/> items can be decided.</summary>
public sealed class Proposal
{
    public required string Id { get; init; }
    public required string Kind { get; init; }
    public string? Code { get; init; }
    public string? Display { get; init; }
    public string? Assertion { get; init; }
    public decimal? Value { get; init; }
    public string? Unit { get; init; }
    public required string Evidence { get; init; }
    public string Status { get; set; } = ProposalStatus.ForReview;
    public List<string> Reasons { get; } = [];
    public List<string> Flags { get; } = [];
}

public sealed record Decision(string Proposal, string Action, string? Code = null);

public sealed record AcceptedItem(Proposal Proposal, string Code, string Display, string Verification);

public sealed record NoteContext(string Patient, string Document, string Date, string Text);

public sealed record Party(string Reference, string Display);

public sealed record ReviewContext(Party Reviewer, Party Device, string At);

/// <summary>The response is not a document of the agreed shape. Nothing in it is used.</summary>
public sealed class ShapeException(string message) : Exception(message);

/// <summary>A review decision that the rules do not allow.</summary>
public sealed class ReviewException(string message) : Exception(message);
