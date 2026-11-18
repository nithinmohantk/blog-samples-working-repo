namespace FhirEvents.Core;

public enum Outcome
{
    /// <summary>The projection now holds a newer version of the resource.</summary>
    Applied,

    /// <summary>The projection now records the resource as deleted.</summary>
    Tombstoned,

    /// <summary>The projection already held this version or a later one. Duplicates and late arrivals end here.</summary>
    SkippedNotNewer,

    /// <summary>The resource no longer exists on the server. Its delete event will record that.</summary>
    SkippedGone,

    /// <summary>A resource type this projection does not hold.</summary>
    Ignored,
}

/// <summary>
/// Applies one change event to the projection. Safe to call any number of times, in any order, for the same
/// resource: the stored version only ever moves forward.
/// </summary>
public sealed class FhirChangeHandler(IFhirReader fhir, IProjectionStore store)
{
    public const string ProjectedType = "Observation";

    public async Task<Outcome> HandleAsync(FhirChangeEvent change, CancellationToken cancellationToken)
    {
        if (change.ResourceType != ProjectedType)
        {
            return Outcome.Ignored;
        }

        // A cheap read that saves a call to the FHIR server for duplicates and late arrivals.
        // Correctness does not rest on it: the conditional write below decides.
        ProjectionRow? stored = await store.GetAsync(change.ResourceType, change.ResourceId, cancellationToken);
        if (stored?.Version >= change.Version)
        {
            return Outcome.SkippedNotNewer;
        }

        if (change.Kind == ChangeKind.Deleted)
        {
            ProjectionRow tombstone = ProjectionRow.Tombstone(change.ResourceType, change.ResourceId, change.Version);
            return await store.UpsertIfNewerAsync(tombstone, cancellationToken) ? Outcome.Tombstoned : Outcome.SkippedNotNewer;
        }

        // The event says something changed. What is projected is the server's current state, which may
        // already be later than the version the event names.
        FhirReadResult current = await fhir.ReadCurrentAsync(change.ResourceType, change.ResourceId, cancellationToken);
        if (current.Resource is null)
        {
            return Outcome.SkippedGone;
        }

        ProjectionRow row = ProjectionRow.FromObservation(current.Resource, current.Version);
        return await store.UpsertIfNewerAsync(row, cancellationToken) ? Outcome.Applied : Outcome.SkippedNotNewer;
    }
}
