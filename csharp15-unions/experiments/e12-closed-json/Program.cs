using System.Text.Json;
JsonSerializerOptions options = new(JsonSerializerDefaults.Web) { InferClosedTypePolymorphism = true };
Outcome outcome = new Rejected("rx-1", "interaction");
string json = JsonSerializer.Serialize(outcome, options);
Console.WriteLine("serialize: " + json);
try { Console.WriteLine("deserialize: " + JsonSerializer.Deserialize<Outcome>(json, options)); }
catch (Exception ex) { Console.WriteLine("deserialize: " + ex.GetType().Name + ": " + ex.Message.Split('\n')[0]); }

public closed record class Outcome(string PrescriptionId);
public sealed record Dispensed(string PrescriptionId, string Pharmacy) : Outcome(PrescriptionId);
public sealed record Rejected(string PrescriptionId, string Reason) : Outcome(PrescriptionId);
