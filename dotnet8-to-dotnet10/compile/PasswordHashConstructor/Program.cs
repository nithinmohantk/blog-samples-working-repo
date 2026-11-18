using System.Security.Cryptography;

// PBKDF2 through the Rfc2898DeriveBytes constructor.
using Rfc2898DeriveBytes pbkdf2 = new("correct horse", new byte[16], 100_000, HashAlgorithmName.SHA256);
Console.WriteLine(pbkdf2.GetBytes(32).Length);
