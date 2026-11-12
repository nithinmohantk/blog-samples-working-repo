# Blog samples

Sample code that accompanies articles on [dataa.dev](https://www.dataa.dev). One folder per article.
Each folder has its own README that says what the code does, how to run it, and what was and was not verified.

| Folder | Article | Languages |
| --- | --- | --- |
| `meai-two-clouds` | [One Abstraction, Two Clouds: Microsoft.Extensions.AI over Azure OpenAI and Amazon Bedrock](https://www.dataa.dev/?p=16300) | C# |
| `agentcore-vs-lambda` | [Bedrock AgentCore Runtime vs. Lambda for Hosting Agents](https://www.dataa.dev/?p=16305) | Python |
| `prompt-caching-economics` | [Prompt Caching Economics on Amazon Bedrock and Azure OpenAI](https://www.dataa.dev/?p=16315) | Python |
| `vector-store-comparison` | [Amazon S3 Vectors vs. OpenSearch Serverless vs. pgvector for RAG](https://www.dataa.dev/?p=16325) | Python, SQL |
| `a2a-mcp-interop` | [A2A and MCP Across Clouds](https://www.dataa.dev/?p=16318) | Python, C# |
| `secure-remote-mcp` | [Hosting Remote MCP Servers Securely on AWS and Azure](https://www.dataa.dev/?p=16322) | Python, C# |
| `fhir-rag` | [RAG over FHIR Data on AWS HealthLake and Azure Health Data Services](https://www.dataa.dev/?p=16328) | Python |
| `fhir-openehr` | [FHIR and openEHR: When to Use Which, and How They Coexist](https://www.dataa.dev/2026/07/25/fhir-and-openehr-when-to-use-which-and-how-they-coexist/) | Python, C# |
| `openehr-aql-to-fhir` | [Mapping openEHR Medication Orders to FHIR: AQL In, Transaction Bundle Out](https://www.dataa.dev/2026/08/01/mapping-openehr-medication-orders-to-fhir-aql-in-transaction-bundle-out/) | Python, C# |
| `clinical-queries` | [Querying Clinical Data: AQL vs. FHIR Search vs. SQL on FHIR](https://www.dataa.dev/2026/08/08/querying-clinical-data-aql-vs-fhir-search-vs-sql-on-fhir/) | Python, SQL, C#, AQL |
| `fhir-facade-openehr` | [A FHIR Facade over an openEHR Repository on Azure](https://www.dataa.dev/2026/08/15/fhir-facade-over-openehr-repository-on-azure-aspnet-core-entra-id-smart-scopes/) | C#, Python |
| `azure-api-for-fhir-migration` | [Migrating from Azure API for FHIR to Azure Health Data Services](https://www.dataa.dev/2026/08/23/migrating-azure-api-for-fhir-to-azure-health-data-services-export-import-identity-cut-over-runbook/) | Python, C# |
| `fhir-events-azure-functions` | [FHIR Subscriptions and Events on Azure: Keeping Downstream Systems in Step](https://www.dataa.dev/2026/08/30/fhir-subscriptions-and-events-on-azure-keeping-downstream-systems-in-step/) | C#, Python |

## Verification status

Not everything here has been compiled or run. The state at the time of the first commit:

* Python: the tests in every folder pass on Python 3.13.
* C# in `fhir-openehr`, `openehr-aql-to-fhir` and `clinical-queries`: compiled and run on the .NET 10 SDK.
* `fhir-facade-openehr`: self-test run on the .NET 10 SDK; the API built on the .NET 10 SDK image and run in Docker against EHRbase 2.39.0, where the Python test client passed 20 of 20 checks. Not deployed to Azure and not tested with Microsoft Entra ID.
* C# in `meai-two-clouds`, `a2a-mcp-interop/dotnet` and `secure-remote-mcp/dotnet`: **not yet compiled**. They depend on NuGet packages; run `dotnet build` before relying on them.
* `clinical-queries/live`: AQL run on EHRbase 2.39.0 and FHIR searches run on HAPI FHIR 8.6.0, both local. See `RESULTS.md` there for what passed, what failed and what was not covered.
* `azure-api-for-fhir-migration`: script tests and validator self-test pass; the validator was run in Docker against two HAPI FHIR servers. Not run against either Azure service.
* `fhir-events-azure-functions`: core self-test and Python rule pass; the Function App was built and run in Docker with PostgreSQL and HAPI FHIR, where the replay script passed 22 of 22. Events were built by the script, not by Event Grid.
* Nothing in this repository has been deployed to AWS or Azure.

## Healthcare samples

The FHIR and openEHR samples use synthetic data only. They are teaching material, not clinically validated software, and must not be used for clinical decisions.
