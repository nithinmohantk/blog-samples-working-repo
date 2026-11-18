using System.Net;
using Microsoft.AspNetCore.HttpOverrides;

// Trusting a reverse proxy's network for X-Forwarded-* headers.
ForwardedHeadersOptions options = new() { ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto };
options.KnownNetworks.Add(new Microsoft.AspNetCore.HttpOverrides.IPNetwork(IPAddress.Parse("10.0.0.0"), 8));
Console.WriteLine(options.KnownNetworks.Count);
