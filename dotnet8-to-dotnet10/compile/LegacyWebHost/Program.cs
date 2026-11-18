using Microsoft.AspNetCore;

// The pre-.NET 6 hosting model, still found in services that were upgraded in place.
IWebHost host = WebHost.CreateDefaultBuilder(args).Configure(app => app.Run(context => context.Response.WriteAsync("ok"))).Build();
Console.WriteLine(host.GetType().Name);
