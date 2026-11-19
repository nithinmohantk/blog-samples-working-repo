(()=>{const G=window.G,P=window.PARTS,IM=window.IM;
P.push(G.h2('For architects'));
P.push(G.p('<strong>Agents get a place to run that you own.</strong> The AKS items belong together. Open-weight models and agents from Foundry can be deployed to your own AKS clusters, so you choose the GPUs and regions for cost, latency and data residency. Agent Sandbox runs code written by an agent in a sandbox isolated at virtual machine level. Agent Grid enforces policy on calls between agents, models, tools and Azure services. Flex nodes extend the same cluster to servers outside Azure. Together that is a reference shape for regulated workloads that cannot send prompts and data to a shared model endpoint. All four are in preview.'));
P.push(G.p('<strong>Context is now a platform.</strong> Microsoft IQ is GA with no new SKU. It packages four sources of context, Work IQ for Microsoft 365 data, Fabric IQ for business data, Foundry IQ for documents and Web IQ for the web, and exposes them to Microsoft Copilot, GitHub Copilot, Foundry and any agent harness through MCP. The design consequence is that retrieval stops being something each agent team builds. It also means the permissions on those sources become the permissions of every agent that connects, so the access review has to happen before the connection, not after.'));
P.push(G.p('<strong>Modernization has one name.</strong> Azure Catalyst, GA, joins the migration tooling in Azure with GitHub Copilot modernization. The agent that plans migrations is GA. Extending it into carrying out the modernization, and a BizTalk to Logic Apps path, are in preview. For estates with BizTalk still in production, that preview is worth an early look, because in my experience BizTalk estates are getting harder to staff.'));
P.push(G.p('<strong>Operations.</strong> Azure Monitor health models are GA. They turn telemetry into a health graph that separates platform problems from application failures and ranks incidents by business impact, which is what most teams build by hand in dashboards. Chaos Studio Workspaces are GA, with reusable scenarios such as losing an availability zone. Windows Server 2028 is in preview with post-quantum cryptography and NVMe over Fabrics. The page gives no release date.'));

P.push(G.h2('Agent governance'));
P.push(G.p('The security chapter is the longest, and most of it answers one question: an agent is running somewhere in the estate, so who is it and what can it reach? Reading the items together, I see controls at five layers. The diagram is my arrangement of them, not Microsoft\'s.'));
P.push(G.mer(G.MF+`
flowchart TD
    A["Identity:<br>Entra Agent ID for cloud and local agents"] --> B["Network:<br>Global Secure Access, MCP Firewall"]
    B --> C["Device:<br>Intune compliance, Windows process containers"]
    C --> D["Runtime:<br>Agent Sandbox and Agent Grid on AKS"]
    D --> E["Data:<br>Purview protection for agent interactions"]
    E --> F["Oversight:<br>Agent 365 inventory, risk and cost"]
    style A fill:#EBF8FF,stroke:#0073BB,stroke-width:2px,color:#004C74
    style B fill:#F3E8FF,stroke:#7C3AED,stroke-width:2px,color:#4C1D95
    style C fill:#FFF3E0,stroke:#FF9900,stroke-width:2px,color:#232F3E
    style D fill:#FFF3E0,stroke:#FF9900,stroke-width:2px,color:#232F3E
    style E fill:#F0FFF4,stroke:#1D8102,stroke-width:2px,color:#145202
    style F fill:#FEF2F2,stroke:#D13212,stroke-width:2px,color:#991B1B`));
P.push(G.ul([
'<strong>Identity.</strong> Entra Agent ID is extended to local agents that are discovered on devices, starting with GitHub Copilot CLI and Claude Code, so their activity can be told apart from the person\'s. Preview.',
'<strong>Network.</strong> An MCP Firewall in Entra Global Secure Access controls access to MCP servers, tools, resources and prompts. Preview. Acquiring agent traffic selectively is GA.',
'<strong>Device.</strong> Intune can mark a device with unapproved agents as noncompliant, and Conditional Access can then block it from company data. Windows adds process containers that give each agent a workspace with limits on communication and network reach. Both preview.',
'<strong>Runtime protection.</strong> Defender runtime protection for local agents on Windows is GA, and the page names Claude Code and GitHub Copilot CLI among those covered.',
'<strong>Oversight.</strong> Agent 365 adds a risk level per agent in preview, governance for plugins and skills at GA, and MCP governance for Azure AI Gateway and LiteLLM in preview.']));
P.push(G.p('One GA item sits apart from these: the Microsoft MCP Server for Enterprise, which lets agents and applications query Entra data through a permissions-based interface. It is the first of these controls a developer can build against today.'));
P.push(G.callout('warning','MOST OF THE CONTROL PLANE IS PREVIEW','Agents are already running in many organisations. Agent identity for local agents, the MCP Firewall, device compliance for agents, process containers and the AKS sandbox are all in preview. If you are approving agents for production now, the controls you can rely on are the ones you already had: application identities, network policy, and review of what each agent is connected to.'));
P.push(G.p('This matches what I found last week when I tested an approval flow in <a href="https://www.dataa.dev/2026/11/18/building-an-agentic-ui-with-blazor-and-dotnet-11/">Building an Agentic UI with Blazor and .NET 11</a>: the protocol let a caller approve an action the agent never proposed, and the fix was a check on the server. Platform controls will help. They do not replace knowing who is allowed to approve what in your own service.'));

P.push(G.h2('What to do next'));
P.push(G.p('This is how I would sort the announcements for a team planning its next quarter. It is a judgement from reading the page, and nothing here has been tried yet.'));
P.push(G.table(['Decision','Items','Why'],[
['Use now','Foundry multi-turn evaluation and production insights; Azure Monitor health models; Cosmos DB Shell; Microsoft MCP Server for Enterprise','GA, low risk to adopt, and each replaces something teams build by hand'],
['Evaluate for a real workload','Azure HorizonDB; Cobalt 200 VMs; Microsoft-Decision-1.1; Copilot SDK 2.0; Azure Catalyst','GA, but the page gives no limits or prices, so test with your own data and load'],
['Try in a sandbox','Azure SQL Database container; Agent Sandbox and Agent Grid on AKS; Entra Agent ID for local agents; MCP Firewall','Preview. Learn the model now, do not depend on it yet'],
['Watch','Windows Server 2028; Fabric HorizonDB; Managed and Programmed Training; BizTalk to Logic Apps','Preview with no dates given']]));
P.push(IM(2,'Suggested sorting of Microsoft Ignite 2026 announcements into use now, evaluate, try in a sandbox and watch','How I would sort the announcements for planning. A judgement from reading, not from testing.'));

P.push(G.h2('Open questions'));
P.push(G.p('A Book of News is an index of announcements. These are the things I looked for and did not find on the page. The linked product posts may answer some of them.'));
P.push(G.ul([
'<strong>HorizonDB limits and price.</strong> The page gives no storage ceiling, replica count, vector index type or pricing.',
'<strong>How close the SQL container really is.</strong> "Same engine" needs testing. The page does not say what happens with service features such as elastic pools, geo-replication and Entra authentication.',
'<strong>The six languages of Copilot SDK 2.0.</strong> Not named on the page.',
'<strong>Agent Grid and Agent Sandbox prerequisites.</strong> Which AKS versions, node types and regions, and what the sandbox costs in start-up time.',
'<strong>What an Agent ID for a local agent can be scoped to.</strong> The page says activity is separated from the human\'s. It does not say whether permissions can be narrower than the user\'s.',
'<strong>Dates.</strong> Windows Server 2028 and most previews have no stated release date.']));

P.push(G.h2('Key takeaways'));
P.push(G.ul([
'Ignite 2026 is about operating agents: where they run, what identity they have, and what they can reach.',
'The generally available items a developer can use today are in data and evaluation: HorizonDB, the Cosmos DB Shell, Foundry evaluation and production insights, Copilot SDK 2.0.',
'The agent runtime on AKS and most agent governance controls are in preview. Plan for them, and keep your own controls until they ship.',
'The Azure SQL Database container is a small item with a large effect on local development and CI, if it holds up in testing.',
'Microsoft IQ makes enterprise context available to any MCP-capable agent. Review access to the underlying sources before connecting agents to them.',
'Two products are called HorizonDB. Check which one a document means.']));

P.push(G.callout('note','HOW THIS WAS CHECKED','This article is a reading of one source, Microsoft\'s Ignite 2026 Book of News, as published on 19 November 2026. Every product name, status and figure comes from that page. Nothing was installed, deployed or measured, and no session was attended. I did not open the product posts the page links to, so details that live only there are not covered. The grouping into layers, the use, evaluate, try and watch sorting, and the opinions are mine. Preview features change, and the page may be updated after this date.'));
P.push(G.h2('References &amp; Further Reading'));
P.push(G.box([
G.ref('https://news.microsoft.com/events/ignite/2026/book-of-news/','Microsoft Ignite 2026 Book of News','The source for every announcement, status and figure in this article'),
G.ref('https://www.dataa.dev/2026/11/18/building-an-agentic-ui-with-blazor-and-dotnet-11/','Building an Agentic UI with Blazor and .NET 11','The approval test referred to in the agent governance section')]));
})();
