(()=>{const G=window.G,P=window.PARTS,IM=window.IM;
const BON='<a href="https://news.microsoft.com/events/ignite/2026/book-of-news/" target="_blank" rel="noopener">Book of News</a>';
P.push(G.p('Microsoft Ignite 2026 is running in San Francisco from 17 to 20 November, and Microsoft has published its '+BON+' for the event: one long page listing every announcement with its status. I read it end to end as someone who builds and designs systems on this platform. This is my summary of what matters to developers and architects, what I would act on now, and what the page leaves unanswered.'));
P.push(G.p('The short version: almost every item is about agents. The question it answers is less how to build one and more how to run them: where they execute, what identity they carry, what they are allowed to reach, and how you find out what they did. The items that are generally available today are mostly data services and evaluation tooling. Most of the agent runtime and control features are still in preview.'));

P.push(G.h2('What was announced'));
P.push(G.p('The page has chapters on Azure, Microsoft Foundry, GitHub, Microsoft Copilot, Edge, Microsoft IQ, security and Windows. This table is my cut of it for people who write and design software. It leaves out most of the end-user Copilot and device management items.'));
P.push(G.table(['Area','Announcement','Status'],[
['Compute','Azure Cobalt 200 Arm-based VMs, with up to 50% better CPU performance than Cobalt 100','GA'],
['Agents on AKS','Foundry open-weight models and agents on your own AKS clusters, Agent Grid, Agent Sandbox extension, Flex nodes','Preview'],
['Operations','Azure Monitor health models; Chaos Studio Workspaces and AKS extension','GA'],
['Operations','Azure SRE Agent additions; Azure Copilot spaces and custom skills','Preview'],
['Modernization','Azure Catalyst platform and Azure Catalyst agent','GA'],
['Databases','Azure HorizonDB, a managed PostgreSQL-compatible database with built-in vector search','GA'],
['Databases','Azure SQL Database container for local development','Preview'],
['Databases','Azure Cosmos DB Shell with MCP integration, Rust SDK, semantic reranker','GA'],
['Databases','Database Hub in Fabric','GA'],
['Foundry','Multi-turn evaluation, production insights, Agent optimizer','GA'],
['Foundry','Managed Training and Programmed Training','Preview'],
['Models','Microsoft-Decision-1.1; MAI-Code-2 and MAI-Code-2-Flash in GitHub','GA'],
['GitHub','Copilot SDK 2.0 on a native Rust runtime, in six languages','GA'],
['Context','Microsoft IQ: Work IQ, Fabric IQ, Foundry IQ and Web IQ through MCP','GA'],
['Identity','Microsoft MCP Server for Enterprise (Entra data)','GA'],
['Identity','Entra Agent ID for discovered local agents; MCP Firewall','Preview'],
['Security','Microsoft Perception','GA'],
['Windows','Windows Server 2028; process containers for agents','Preview']]));
P.push(IM(1,'Microsoft Ignite 2026 announcements for developers and architects grouped by generally available and preview status','My reading of the Book of News: what is generally available and what is still in preview.'));

P.push(G.h2('For developers'));
P.push(G.p('<strong>A local Azure SQL Database.</strong> The item I expect to use first is the smallest one on the page. The Azure SQL Database container, in preview, runs the Azure SQL Database engine on your machine with no subscription. Microsoft says it has the same T-SQL dialect, system views, connection protocol and driver behaviour as the service, supports vector search, ledger and Always Encrypted with secure enclaves, and can run integration tests in CI. The usual choices for local work have been a SQL Server container, which is not the same product, or a shared cloud database. If the container does what the page says, integration tests can stop depending on a cloud instance.'));
P.push(G.p('<strong>HorizonDB is generally available.</strong> Azure HorizonDB is a fully managed, PostgreSQL-compatible database with built-in vector search. The GA list covers what a platform team asks about first: Entra ID, private endpoints, managed identities, customer-managed keys and multi-zone replication. The AI features on top of it, model management, AI Functions and AI Pipelines, are in preview, as is mirroring into Fabric. A second product with the same name, Microsoft Fabric HorizonDB, is a serverless PostgreSQL inside Fabric and is in preview. Read which one a document means before you plan around it.'));
P.push(G.p('<strong>Cosmos DB gets a shell and a Rust SDK.</strong> The Azure Cosmos DB Shell is GA in VS Code and the portal, and it includes MCP integration, so an AI assistant can work against a database through it. The Rust SDK and the semantic reranker are GA too. The page says seven updates and lists six.'));
P.push(G.p('<strong>Evaluation becomes a loop.</strong> Foundry now has multi-turn evaluation, which scores a whole conversation and not one reply, production insights, which groups recurring failures such as hallucinations and token spikes, and an Agent optimizer that proposes changes and tests them against your evaluations. All three are GA. This is the part of agent development most teams skip, and having it as a product removes one excuse. The two training options that feed from it, Managed Training and Programmed Training, are in preview.'));
P.push(G.p('<strong>Copilot SDK 2.0.</strong> GitHub\'s only numbered item is the Copilot SDK 2.0, GA, described as a production-proven agent harness on a native Rust runtime, available in six languages, for agents embedded in applications including multi-tenant ones. The page does not name the six languages. The same chapter mentions that the GitHub Copilot app now works with Azure DevOps repositories, and that Copilot code review gains local reviews in the CLI, secret detection and cross-repository context.'));
P.push(G.p('<strong>A small, fast model for decisions.</strong> Microsoft-Decision-1.1 is GA for routing, classification and verification. It is built on Gemma 4, accepts images, and Microsoft says it is more than twice as fast as the first version at the same price. This is the kind of model an agent calls many times per task to decide what to do next, where speed and cost matter more than depth. MAI-Code-2 and MAI-Code-2-Flash are GA in GitHub.'));
P.push(G.p('<strong>Copilot Studio agents as code.</strong> Copilot Managed Runtime is GA. The developer-facing part is that Copilot Studio agents and workflows can be built locally, edited in your own tools, kept in version control and published with a CLI. The page gives no separate status for that part.'));
})();
