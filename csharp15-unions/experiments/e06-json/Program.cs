using System.Text.Json;
using System.Text.Json.Serialization;
JsonSerializerOptions web = new(JsonSerializerDefaults.Web);
void Try(string name, Func<string> action) { try { Console.WriteLine($"{name}: {action()}"); } catch (Exception ex) { Console.WriteLine($"{name}: {ex.GetType().Name}: {ex.Message.Split('\n')[0]}"); } }

Outcome outcome = new Rejected("rx-1", "interaction with warfarin");
Try("serialize, classifier declared", () => JsonSerializer.Serialize(outcome, web));
Try("serialize inside a record", () => JsonSerializer.Serialize(new Envelope("evt-1", outcome), web));
Try("serialize default union", () => JsonSerializer.Serialize(default(Outcome), web));
Try("deserialize Rejected by shape", () => JsonSerializer.Deserialize<Outcome>("""{"prescriptionId":"rx-1","reason":"x"}""", web).Value?.ToString() ?? "null");
Try("deserialize Dispensed by shape", () => JsonSerializer.Deserialize<Outcome>("""{"prescriptionId":"rx-1","pharmacy":"Main Street"}""", web).Value?.ToString() ?? "null");
Try("deserialize, shape matches no case", () => JsonSerializer.Deserialize<Outcome>("""{"prescriptionId":"rx-1","unknown":1}""", web).Value?.ToString() ?? "null");
Try("deserialize, only the shared property", () => JsonSerializer.Deserialize<Outcome>("""{"prescriptionId":"rx-1"}""", web).Value?.ToString() ?? "null");
Try("deserialize null", () => JsonSerializer.Deserialize<Outcome>("null", web).Value?.ToString() ?? "null");
Try("round trip inside a record", () => JsonSerializer.Deserialize<Envelope>(JsonSerializer.Serialize(new Envelope("evt-1", outcome), web), web)!.ToString());

Plain plain = new A("x");
Try("serialize, no classifier", () => JsonSerializer.Serialize(plain, web));
Try("deserialize, no classifier", () => JsonSerializer.Deserialize<Plain>("""{"name":"x"}""", web).Value?.ToString() ?? "null");
Try("ambiguous shapes with classifier", () => JsonSerializer.Deserialize<Twins>("""{"name":"x"}""", web).Value?.GetType().Name ?? "null");
Try("primitive cases: number", () => JsonSerializer.Deserialize<TextOrNumber>("42", web).Value?.GetType().Name ?? "null");
Try("primitive cases: string", () => JsonSerializer.Deserialize<TextOrNumber>("\"forty-two\"", web).Value?.GetType().Name ?? "null");
Try("primitive cases: serialize", () => JsonSerializer.Serialize<TextOrNumber>(42, web) + " " + JsonSerializer.Serialize<TextOrNumber>("x", web));

public sealed record Dispensed(string PrescriptionId, string Pharmacy);
public sealed record Rejected(string PrescriptionId, string Reason);
public sealed record Referred(string PrescriptionId, string Question);
[JsonUnion(TypeClassifier = typeof(JsonUnionTypeStructuralClassifier))]
public union Outcome(Dispensed, Rejected, Referred);
public sealed record Envelope(string EventId, Outcome Outcome);

public sealed record A(string Name);
public sealed record B(string Name);
public union Plain(A, B);
[JsonUnion(TypeClassifier = typeof(JsonUnionTypeStructuralClassifier))]
public union Twins(A, B);
public union TextOrNumber(string, int);
