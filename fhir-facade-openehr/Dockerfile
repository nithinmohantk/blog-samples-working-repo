# Build and run on .NET 11. To stay on the .NET 10 long-term support release, change both tags to 10.0,
# the TargetFramework in the project file to net10.0 and the JwtBearer package version to 10.0.x.
FROM mcr.microsoft.com/dotnet/sdk:11.0 AS build
WORKDIR /src
COPY src/FhirFacade/ ./
RUN dotnet publish FhirFacade.csproj -c Release -o /app

FROM mcr.microsoft.com/dotnet/aspnet:11.0
WORKDIR /app
COPY --from=build /app ./
USER $APP_UID
ENTRYPOINT ["dotnet", "FhirFacade.dll"]
