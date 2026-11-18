(()=>{const G=window.G,SN=window.SN,P=window.PARTS,IM=window.IM;
P.push(G.p('A chat box that streams text is no longer the interesting part of an AI feature. The interesting part is everything the agent does besides talk: it calls a tool and the result should appear as a proper card, it wants to do something irreversible and a person has to say yes, it fills in a form that the user then edits. That is an agentic UI, and until this autumn a Blazor team had to build all of it by hand.'));
P.push(G.p('Two things changed. The AG-UI protocol got a .NET SDK, and ASP.NET Core 11 arrived with a preview package of Blazor components that understand streamed text, tool calls, approvals and shared state. This article builds a small order desk with them on .NET 11: a Blazor Web App in front, an agent service behind it, AG-UI between the two.'));
P.push(G.p('It is built to be tested. The model is replaced by a scripted stand-in, so the same conversation produces the same events every time, and four layers of tests run in a pipeline with no keys: 26 xUnit and bUnit tests and nine steps in a real browser. Along the way the tests turned up two things worth knowing before production. An approval can be forged with one hand-written HTTP request unless the server checks it, and an optional field makes the event stream three to four times larger than it needs to be.'));

P.push(G.h2('The problem'));
P.push(G.p('An agent emits more than text. In one turn it can stream words, ask for a tool, wait for the result, change some state the page is showing, and stop to ask permission. A UI that treats all of that as a string ends up parsing markdown for hidden JSON, or polling, or building a private protocol between the page and the server.'));
P.push(G.p('The second problem is testing. A component that renders whatever a model says cannot be tested against a model: the output changes, the calls cost money, and a pipeline needs credentials. So the UI goes untested, and the first time anyone finds out what happens when a user clicks Reject is in production.'));
P.push(G.p('Both problems have the same answer: a typed stream of events with a defined vocabulary, and a seam where the model can be swapped for something deterministic.'));

P.push(G.h2('Architecture'));
P.push(G.mer(G.MF+`
flowchart TD
    B["Browser"] -- "SignalR circuit" --> W["Blazor Web App, interactive server:<br>UIAgent and Blazor AI components"]
    W -- "IChatClient" --> C["AGUIChatClient"]
    C -- "HTTP POST, run request" --> E["Agent service: AG-UI endpoint"]
    E -- "Server-Sent Events" --> C
    E --> V["Verify approvals against<br>what this server proposed"]
    V --> P["Chat client pipeline:<br>function invocation, then the model"]
    P --> T["Tools: get_order, draft_reply,<br>refund_order (needs approval)"]
    T --> L["Ledger: payment stand-in,<br>one refund per key"]
    style W fill:#EBF8FF,stroke:#0073BB,stroke-width:2px,color:#004C74
    style E fill:#F3E8FF,stroke:#7C3AED,stroke-width:2px,color:#4C1D95
    style V fill:#F3E8FF,stroke:#7C3AED,stroke-width:2px,color:#4C1D95
    style L fill:#F0FFF4,stroke:#1D8102,stroke-width:2px,color:#145202`));
P.push(G.p('Three decisions shape it.'));
P.push(G.ul([
'<strong>The agent is a separate service.</strong> It owns the model, the tools and the rules. The web app owns rendering. Either can be replaced, and other front ends that speak AG-UI can use the same agent.',
'<strong>The UI depends on <code>IChatClient</code>, nothing more specific.</strong> In production that is an <code>AGUIChatClient</code> pointed at the agent service. In a component test it is the agent pipeline plugged in directly. The components do not know the difference.',
'<strong>The browser never speaks AG-UI.</strong> With the interactive server render mode, the browser holds a SignalR circuit to the Blazor app, and the Blazor app calls the agent service from the server. The browser run confirmed it: the only hosts the page contacted were the web app and its WebSocket. That matters for the approval finding below.']));

P.push(G.h2('Packages'));
P.push(G.code('xml',SN('Directory.Packages.props','    <PackageVersion Include="Microsoft.AspNetCore.Components.AI"','    <PackageVersion Include="Microsoft.AspNetCore.Mvc.Testing"').replace(/\n$/,'')));
P.push(G.table(['Package','What it gives','Status'],[
['<code>Microsoft.AspNetCore.Components.AI</code>','<code>UIAgent</code>, <code>AgentBoundary</code>, <code>MessageList</code>, <code>MessageInput</code>, <code>BlockRenderer</code>, approval and state types','Experimental preview, published 16 September 2026. Targets <code>net11.0</code> only'],
['<code>AGUI.Client</code>','<code>AGUIChatClient</code>, an <code>IChatClient</code> over the protocol','1.0.1, published 12 October 2026'],
['<code>AGUI.Server</code>, <code>AGUI.Formatting</code>','Turning a run request into a chat request, and chat updates into events written as Server-Sent Events','1.0.1'],
['<code>Microsoft.Extensions.AI</code>','<code>IChatClient</code>, function invocation, <code>ApprovalRequiredAIFunction</code>','11.0.0, published with .NET 11 on 10 November 2026']]));
P.push(G.callout('warning','PIN THE PREVIEW PACKAGE','A floating prerelease version of <code>Microsoft.AspNetCore.Components.AI</code> resolves to <code>11.0.0-preview.7</code>. That is an older build from the .NET 11 preview train, and it sorts above the current <code>0.1.0-preview.1</code> line because 11 is greater than 0. The first restore in this project picked it. Name the exact version.'));
P.push(G.p('Microsoft Agent Framework has its own hosting package for AG-UI, with <code>MapAGUIServer</code>. This sample does not use it. The endpoint is built on <code>AGUI.Server</code> directly, which keeps every step visible and avoids a second preview dependency.'));

P.push(G.h2('Agent pipeline'));
P.push(G.p('The agent is a chat client pipeline: a model at the bottom, the loop that runs tool calls above it, and the tools added to every request. This is the seam. Replace <code>ScriptedModel</code> with a real model client and nothing else changes.'));
P.push(G.code('csharp',SN('src/Desk.Core/DeskAgent.cs','    public static IChatClient Create(','\n}\n')));
P.push(G.p('<code>ScriptedModel</code> reads the conversation and decides the way a simple model would: an order id with the word "refund" becomes a call to <code>refund_order</code>, a tool result becomes a sentence about it, anything else becomes text, streamed a word at a time. Same conversation in, same updates out.'));
P.push(G.p('The tools are plain methods. One line makes the refund need a person:'));
P.push(G.code('csharp',SN('src/Desk.Core/DeskTools.cs','    public IList<AITool> Create() =>','\n    private Order? GetOrder(')));
P.push(G.p('The refund itself does two things that do not depend on any UI. It applies the payment rule, and it records the refund under a key built from the order, so that a repeated approval or a retried request cannot pay twice. The <a href="https://www.dataa.dev/2026/03/24/crash-checkpoint-resume-durable-agent-state/">crash and resume article</a> explains why the key comes from the business operation and not from the tool call.'));
P.push(G.code('csharp',SN('src/Desk.Core/DeskTools.cs','    private RefundResult RefundOrder(','\n    private CaseState DraftReply(')));

P.push(G.h2('AG-UI endpoint'));
P.push(G.p('The whole server side of the protocol is one endpoint. It binds the run request, turns it into messages and options, runs the pipeline, and writes the updates back as events.'));
P.push(G.code('csharp',SN('src/Desk.Agent/Program.cs','app.MapPost("/agent", (','\n// For the lab only')));
P.push(G.p('Two lines carry the shared state. <code>MapResultAsStateSnapshot</code> says the result of <code>draft_reply</code> is the new state, so it is sent as a state event as well as a tool result. And state arriving from the page is put in front of the model as part of the conversation, which is how a real model would see it too.'));
})();
