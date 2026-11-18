FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src
COPY src/ ./src/
RUN dotnet publish src/FhirEvents.Functions/FhirEvents.Functions.csproj -c Release -o /home/site/wwwroot

FROM mcr.microsoft.com/azure-functions/dotnet-isolated:4-dotnet-isolated10.0
ENV AzureWebJobsScriptRoot=/home/site/wwwroot \
    AzureFunctionsJobHost__Logging__Console__IsEnabled=true
COPY --from=build /home/site/wwwroot /home/site/wwwroot
