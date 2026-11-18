using System.Security.Cryptography.X509Certificates;

// Loading a certificate from bytes with the constructor, as most code written before .NET 9 does.
byte[] bytes = args.Length > 0 ? File.ReadAllBytes(args[0]) : [];
if (bytes.Length > 0)
{
    using X509Certificate2 certificate = new(bytes);
    Console.WriteLine(certificate.Subject);
}
