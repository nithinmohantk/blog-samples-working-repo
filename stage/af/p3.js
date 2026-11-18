(()=>{const G=window.G,SN=window.SN,P=window.PARTS,IM=window.IM;
P.push(G.h2('Cost'));
P.push(G.p('Cost here is what a team has to own and run.'));
P.push(G.table(['','Hand-built endpoint','Framework endpoint'],[
['Service code, with comments and lab endpoints','196 lines in 3 files','136 lines in 3 files'],
['Protocol code you maintain','JSON registration, request conversion, SSE result','None'],
['Approval check','82 lines of your own','A framework option, on by default'],
['State kept on the server','Pending approvals only','The whole session: history and pending approvals'],
['Shared store needed with two instances','Small: one entry per open approval','A session store for every conversation'],
['Bytes for one order question','1,430','4,901']]));
P.push(G.p('Sixty lines is not much of a saving, and half of what is left on the framework side is two wrappers, one of which exists only to stop the framework and the protocol from disagreeing. The real trade is different. The hand-built service keeps almost nothing and checks approvals itself. The framework service keeps everything and checks approvals for you, and in exchange you operate a session store.'));

P.push(G.h2('Production considerations'));
P.push(G.ul([
'<strong>The session store is now part of the approval path.</strong> If a session is lost, the pending approval goes with it and the user\'s Approve click does nothing. The seventh row of the matrix shows the other effect: with no stored session and the wrapper on, the model saw one message of a three-message conversation. The in-memory store is marked for evaluation only. Production needs a durable, shared one.',
'<strong>Keep isolation on.</strong> <code>WithSessionStore</code> and <code>WithInMemorySessionStore</code> take a <code>withIsolation</code> argument that defaults to true. I turned it off because neither service has an identity to isolate by. I did not test it. Without it, the thread id in the request is the only key to a session.',
'<strong>Neither endpoint is safe to expose to untrusted callers.</strong> In the changed-call test the framework paid the proposed refund on the say-so of a hand-written POST that knew the thread and the interrupt id. That is an approval by someone who was never asked. Binding protects what gets approved. It does not establish who approved it.',
'<strong>Log what the framework drops.</strong> A refused approval is HTTP 200. Count them in a wrapper and alert on them.',
'<strong>Capture the real exception.</strong> The client is told only that streaming failed, which is the right thing to tell a client. Make sure the server log has the rest. During this work I had to hook first-chance exceptions to see the cause.',
'<strong>Decide who can read the stream.</strong> <code>rawEvent</code> carries the agent name, content types and message ids of every update. With Blazor interactive server the browser never sees it, because the web app is the AG-UI client. A client running in the browser would.',
'<strong>Check what the session stores.</strong> <code>CaseStateAgent</code> adds a system message on every turn. I did not measure whether those accumulate in the stored history. With a real model, measure it before relying on it.',
'<strong>Keep the matrix test.</strong> This is a preview package, and every cell in that table is behaviour that can change in the next build. The test runs with the others in the pipeline and tells you which cells moved.']));
P.push(G.callout('compliance','AUDIT','An approval is a decision by a person, and a record of it should name who decided, what was proposed and what ran. Neither service authenticates anyone, so neither can produce that record. The framework service adds a gap of its own: an approval it drops leaves no trace at the endpoint. Where approvals gate money or anything clinical, write the record yourself, at the point the tool runs and at the point an answer is refused.'));

P.push(G.h2('Decision framework'));
P.push(G.table(['If this is true','Prefer','Why'],[
['The agent service should stay stateless and scale without a conversation store','Hand-built','The client carries the conversation; the server keeps one small table'],
['A tampered or replayed approval must be refused visibly','Hand-built','HTTP 409 with a reason, before any event is sent'],
['The event stream can reach a browser or another party you do not control','Hand-built','It can leave out rawEvent today'],
['The server should own the conversation and not trust the client\'s copy','Framework','Sessions, with history and pending approvals on the server'],
['You already run Agent Framework agents or workflows','Framework','One hosting model, and the endpoint is one call'],
['You want the least protocol code to maintain','Framework','With a session store, the new-messages wrapper and the matrix test']]));
P.push(G.p('For this order desk, today, I would keep the hand-built endpoint. It has fewer moving parts, it refuses loudly, and it does not depend on a preview hosting package or an evaluation-only store. That changes the day the server needs to own the conversation, for example when the history must survive a browser refresh or be shared between devices. At that point the framework\'s session model is the thing you would otherwise have to build, and its approval binding comes with it.'));

P.push(G.h2('Key takeaways'));
P.push(G.ul([
'For text, tool calls, shared state and cancellation, <code>MapAGUIServer</code> and a hand-built endpoint on <code>AGUI.Server</code> send the same events. The same Blazor app passed nine browser steps against both.',
'With these clients and this preview, an approval did not complete on the shortest framework setup. It needed a session store, and a wrapper that takes only new messages from the client.',
'A session store and an AG-UI client both hold the conversation. Passed through unchanged, the model received five messages where the client sent three.',
'Framework approval binding blocks a forged call and runs the stored one. It answers a replayed or forged approval with HTTP 200, so add your own logging.',
'Turning binding off to make approvals work reopens the hole from the first article: one hand-written POST refunded an order nobody proposed.',
'The framework stream was 3.4 times the size of the trimmed hand-built stream, with no switch found to reduce it.']));

P.push(G.callout('note','HOW THIS WAS CHECKED','Everything in this article comes from one pipeline run on 18 November 2026: <a href="https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/44363641369" target="_blank" rel="noopener">GitHub Actions run 44363641369</a>, commit <code>93b7416</code>, with the transcripts, wire traces and the settings matrix on the <code>ci-results-agentic-ui-blazor</code> branch. 48 xUnit and bUnit tests passed, the 28 wire tests passed again on AGUI 1.0.0 and Microsoft.Extensions.AI 10.11.0, and nine Chromium steps passed against each service. The model is a scripted stand-in and all orders are invented. Not done: no real model was called; the C# client loop shown in the Agent Framework documentation was not run, the clients here are <code>AGUIChatClient</code> used directly and the Blazor components over it; Agent Framework was studied through its public API and its behaviour, not its source, so the explanation of approval binding is an inference; session isolation was not tested; stores are in memory on one instance; one preview build was tested and later builds may behave differently.'));
P.push(window.GETCODE);
P.push(G.h2('References &amp; Further Reading'));
P.push(G.box([
G.ref('https://www.dataa.dev/2026/11/18/building-an-agentic-ui-with-blazor-and-dotnet-11/','Building an Agentic UI with Blazor and .NET 11','The first article: the Blazor app, the hand-built endpoint and the forged approval finding'),
G.ref('https://learn.microsoft.com/agent-framework/integrations/ag-ui/getting-started','Agent Framework: Getting started with AG-UI','MapAGUIServer hosting and the client'),
G.ref('https://learn.microsoft.com/agent-framework/integrations/ag-ui/human-in-the-loop','Agent Framework: Human-in-the-loop with AG-UI','Approval-required tools, interrupts and the resume payload'),
G.ref('https://learn.microsoft.com/agent-framework/integrations/ag-ui/state-management','Agent Framework: State management with AG-UI','Reading client state in a delegating agent and mapping tool results to state events'),
G.ref('https://learn.microsoft.com/en-us/agent-framework/integrations/by-component/ui/ag-ui/security-considerations','Agent Framework: AG-UI security considerations','Untrusted clients, state validation, thread ownership and approval state'),
G.ref('https://github.com/ag-ui-protocol/ag-ui/tree/main/sdks/dotnet','AG-UI .NET SDK source','Where a resume entry is turned into an approval request and response'),
G.ref('https://github.com/nithinmohantk/blog-samples-working-repo/tree/main/agentic-ui-blazor','Sample code for this article','Both agent services, the Blazor app, the shared tests, the settings matrix and the pipeline script')]));
})();
