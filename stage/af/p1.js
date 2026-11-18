(()=>{const G=window.G,SN=window.SN,P=window.PARTS,IM=window.IM;
const PREV='<a href="https://www.dataa.dev/2026/11/18/building-an-agentic-ui-with-blazor-and-dotnet-11/">Building an Agentic UI with Blazor and .NET 11</a>';
P.push(G.p('Last week\'s article, '+PREV+', built an order desk in Blazor on top of an AG-UI endpoint written by hand: about two hundred lines that bind the request, run the agent, stream the events and check every approval against what the server proposed. Microsoft Agent Framework has a method, <code>MapAGUIServer</code>, that maps the same kind of endpoint in one call. The obvious question is whether the two hundred lines were worth writing.'));
P.push(G.p('So I built the agent service a second time on Agent Framework hosting and put it behind the same Blazor app. One test class now runs against both services, and the browser steps run twice. For text, tool calls, shared state and Stop, the two servers send the same events in the same order, and all nine browser steps pass on both.'));
P.push(G.p('Approvals are where they differ. With the clients used here, the shortest framework setup stopped for approval correctly and then failed on the answer. Getting an honest approval through took a session store and a ten-line wrapper. Once that was in place the framework did something my endpoint does not: when a request tried to swap the approved refund for a different one, it ran the refund the server had proposed and ignored the one in the request. It also did something I like less: it turned every refused approval into an ordinary HTTP 200.'));

P.push(G.h2('The problem'));
P.push(G.p('A hand-built endpoint is code a team owns. Somebody has to register the protocol\'s JSON types, turn a run request into chat messages, format Server-Sent Events, and decide what an approval is allowed to do. The first article found that last part matters: the approval and the tool call it approves both travel in the client\'s request, so without a server-side check one hand-written POST moved money.'));
P.push(G.p('A framework method that does all of this is attractive, and for most of it the attraction is justified. What a one-line mapping cannot tell you is what it decided on your behalf. Does it keep the conversation on the server or trust the copy the client sends? Does it check an approval against anything? What does a caller see when it refuses? Those answers decide whether the endpoint is safe to expose, and none of them is visible in the line of code.'));
P.push(G.p('The way to find out is to hold everything else still. Same model stand-in, same three tools, same payment ledger, same Blazor app, same tests. Only the hosting layer changes.'));

P.push(G.h2('Architecture'));
P.push(G.mer(G.MF+`
flowchart TD
    W["Blazor Web App:<br>UIAgent over AGUIChatClient"] -- "HTTP POST, whole conversation<br>and any approval answer" --> M["MapAGUIServer endpoint:<br>binding, events, interrupts"]
    M --> H["Hosted agent:<br>loads the session for this thread"]
    H <--> S["Session store:<br>history and pending approvals"]
    H --> N["NewMessagesOnlyAgent:<br>keep what follows the last assistant message"]
    N --> C["CaseStateAgent:<br>put the browser's state in front"]
    C --> A["ChatClientAgent:<br>tool loop, approval binding"]
    A --> T["Tools: get_order, draft_reply,<br>refund_order (needs approval)"]
    T --> L["Ledger: payment stand-in,<br>one refund per key"]
    style W fill:#EBF8FF,stroke:#0073BB,stroke-width:2px,color:#004C74
    style M fill:#F3E8FF,stroke:#7C3AED,stroke-width:2px,color:#4C1D95
    style H fill:#F3E8FF,stroke:#7C3AED,stroke-width:2px,color:#4C1D95
    style S fill:#F0FFF4,stroke:#1D8102,stroke-width:2px,color:#145202
    style L fill:#F0FFF4,stroke:#1D8102,stroke-width:2px,color:#145202`));
P.push(G.p('The hand-built service from the first article is stateless. Every request carries the whole conversation, and the only thing the server remembers is a small table of approvals it is waiting for. The framework service ends up stateful: the session for a thread lives on the server, holds the history and the pending approval, and is the thing an approval is checked against.'));
P.push(G.p('That difference is the whole design. An AG-UI client sends the full conversation on every request, because the protocol lets a server be stateless. A server that also keeps the conversation now has two copies, and has to choose one. The two wrappers in the diagram exist because of that choice.'));
P.push(IM(1,'Comparison of a hand-built AG-UI endpoint and Agent Framework MapAGUIServer hosting across events, approvals, forged approvals, refusals, stream size and browser steps','Both servers behind the same Blazor app, measured by the same tests.'));

P.push(G.h2('The framework host'));
P.push(G.p('The agent is registered by name, given a session store, and mapped. The model stand-in and the tools are the ones the hand-built service uses. <code>SeenByModel</code> is a test tool that notes what the model was handed; it is how the history numbers later in this article were measured.'));
P.push(G.code('csharp',SN('src/Desk.AgentFramework/Program.cs','IHostedAgentBuilder desk = builder.Services.AddAIAgent','\n\nWebApplication app')));
P.push(G.code('csharp',SN('src/Desk.AgentFramework/Program.cs','// One call maps the endpoint','\n\n// For the lab only')));
P.push(G.p('Compare that with the first article. There is no JSON registration, no <code>RunAgentInput</code> parameter, no event stream result type and no <code>UseFunctionInvocation()</code>: <code>AddAGUIServer()</code> registers the JSON types and the agent type runs the tool loop. <code>AGUIStreamOptions</code> is the same class as before, attached as endpoint metadata, so the result of <code>draft_reply</code> still goes out as a <code>STATE_SNAPSHOT</code>.'));
P.push(G.p('State coming the other way needs a wrapper. The endpoint keeps the original request on the chat options, and an agent that wraps the real one can read the browser\'s state from there and put it in front of the model:'));
P.push(G.code('csharp',SN('src/Desk.AgentFramework/CaseStateAgent.cs','    protected override IAsyncEnumerable<AgentResponseUpdate> RunCoreStreamingAsync','\n}')));
P.push(G.p('The second wrapper is the one I did not expect to write. It decides which copy of the conversation wins:'));
P.push(G.code('csharp',SN('src/Desk.AgentFramework/NewMessagesOnlyAgent.cs','    protected override IAsyncEnumerable<AgentResponseUpdate> RunCoreStreamingAsync','\n}')));
P.push(G.p('The session already holds everything up to the agent\'s last reply. From the client, the server takes only what comes after the last assistant message: the user\'s new turn, or their answer to an approval. The next two sections show what happens without it.'));
P.push(G.callout('warning','EVALUATION-ONLY TYPES','In this preview <code>InMemoryAgentSessionStore</code> and <code>NoopAgentSessionStore</code> are marked for evaluation only. Using them is compile error MAAI001 until the project suppresses it. The sample suppresses it in the project file, with a comment, for this one project.'));
})();
