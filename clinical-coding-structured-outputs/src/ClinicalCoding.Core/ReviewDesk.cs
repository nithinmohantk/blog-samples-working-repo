namespace ClinicalCoding.Core;

/// <summary>Applies a reviewer's decisions. A proposal with no decision stays pending and produces nothing.</summary>
public static class ReviewDesk
{
    public static IReadOnlyList<AcceptedItem> Apply(IReadOnlyList<Proposal> proposals, IEnumerable<Decision> decisions, CodingSubset subset)
    {
        Dictionary<string, Proposal> byId = proposals.ToDictionary(p => p.Id);
        List<AcceptedItem> accepted = [];
        HashSet<string> decided = [];

        foreach (Decision decision in decisions)
        {
            if (!byId.TryGetValue(decision.Proposal, out Proposal? proposal))
            {
                throw new ReviewException($"no proposal '{decision.Proposal}'");
            }

            if (decided.Contains(proposal.Id))
            {
                throw new ReviewException($"proposal '{proposal.Id}' already has a decision");
            }

            if (proposal.Status != ProposalStatus.ForReview)
            {
                throw new ReviewException($"proposal '{proposal.Id}' is {proposal.Status} and cannot be decided");
            }

            string? code = proposal.Code;
            string? display = proposal.Display;
            string verification = "confirmed";
            switch (decision.Action)
            {
                case "reject":
                    decided.Add(proposal.Id);
                    continue;
                case "recode":
                    ConditionCode replacement = (proposal.Kind == "condition" ? subset.Condition(decision.Code) : null)
                        ?? throw new ReviewException("a recode needs a condition code from the subset");
                    (code, display) = (replacement.Code, replacement.Display);
                    break;
                case "accept_provisional":
                    if (proposal.Kind != "condition")
                    {
                        throw new ReviewException("only a condition can be accepted as provisional");
                    }

                    verification = "provisional";
                    break;
                case "accept":
                    break;
                default:
                    throw new ReviewException($"unknown action '{decision.Action}'");
            }

            if (code is null || display is null)
            {
                throw new ReviewException($"proposal '{proposal.Id}' has no code: recode or reject it");
            }

            decided.Add(proposal.Id);
            accepted.Add(new AcceptedItem(proposal, code, display, verification));
        }

        return accepted;
    }
}
