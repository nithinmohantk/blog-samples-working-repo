# TwoClouds.Chat

Sample code for the dataa.dev article "One Abstraction, Two Clouds: Microsoft.Extensions.AI over Azure OpenAI and Amazon Bedrock".

## Status

The code was written against the Microsoft.Extensions.AI 10.6.0 source and the AWS Bedrock extension source, but it has **not been compiled or run**. Build it before relying on it:

```
dotnet build
```

If the build reports errors, the most likely causes are package version alignment between `Azure.AI.OpenAI` and `Microsoft.Extensions.AI.OpenAI` (both depend on the `OpenAI` package).

## Run

1. Set the values in `appsettings.json`.
2. Sign in with `az login` and configure AWS credentials and a Region.
3. `dotnet run`, then `POST /chat` with `{"message":"Where is order ORD-10042?"}`.
