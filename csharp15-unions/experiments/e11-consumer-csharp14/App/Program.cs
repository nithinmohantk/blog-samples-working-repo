// A C# 14 project consuming a union declared in a C# 15 library.
Outcome constructed = new Outcome(new Dispensed("rx-1", "Main Street"));
Console.WriteLine("constructor and Value work: " + constructed.Value);
Console.WriteLine(constructed.Value switch { Dispensed d => "dispensed at " + d.Pharmacy, Rejected r => "rejected", Referred q => "referred", _ => "unknown" });
