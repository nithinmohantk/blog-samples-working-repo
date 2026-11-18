// The same consumer, using the implicit conversion and matching on the union itself.
Outcome converted = new Dispensed("rx-1", "Main Street");
Console.WriteLine(converted switch { Dispensed d => "dispensed", Rejected r => "rejected", Referred q => "referred" });
