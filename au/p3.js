(()=>{const G=window.G,SN=window.SN,P=window.PARTS,IM=window.IM;
P.push(G.h2('Approval security'));
P.push(G.p('Look again at the resume request. The client sends the decision, and it also sends the tool call: name and arguments. The server kept nothing from the first run, so on the second it rebuilds the call from what the client supplied.'));
P.push(G.p('A test asks the obvious question. It posts one request, written by hand, that approves a refund the agent never proposed. A second variant lets the agent propose 37.50 on one order, then approves 42.00 on another under the same interrupt id.'));
P.push(G.code('text',SN('@r/03a-findings.txt','changed after proposal   check off','== 3b.').replace(/\n+$/,'')));
P.push(G.p('With the endpoint as first written, both forged requests returned HTTP 200 and the refund was in the ledger. <code>ApprovalRequiredAIFunction</code> did what it promises: it did not run the function without an approval. The approval was simply not evidence that a person, or this server, had ever seen the call.'));
P.push(G.mer(G.MS+`
sequenceDiagram
    participant U as Desk user
    participant W as Blazor Server
    participant A as Agent service
    participant L as Ledger
    U->>W: Refund order O-1003
    W->>A: Run 1: user message
    A-->>W: Tool call, then RUN_FINISHED: interrupt
    Note over A: Remembers the proposed call<br>for this interrupt
    W-->>U: Approve or Reject
    U->>W: Approve
    W->>A: Run 2: resume with decision and tool call
    Note over A: Same call as proposed,<br>not yet answered: accepted
    A->>L: Refund once, keyed by order
    A-->>W: Tool result and text`));
P.push(G.p('The fix is for the server to remember what it proposed. On the way out, a small component watches the event stream and notes each tool call that a run ends on. On the way in, a resume is accepted only if it names a pending interrupt, within a time limit, with exactly the proposed call, and each one is used up when it is answered:'));
P.push(G.code('csharp',SN('src/Desk.Agent/PendingApprovals.cs','    public bool TryRedeem(','\n    /// <summary>Tool name plus arguments in one canonical form').replace(/\n+$/,'')));
P.push(G.p('With the check on, both forged requests get HTTP 409 and the ledger stays empty, the ordinary Approve and Reject paths still pass, and sending the same approval twice is refused the second time.'));
P.push(G.mer(G.MF+`
flowchart TD
    R["Run request with a resume entry"] --> K{"Interrupt id pending<br>on this server?"}
    K -- "no" --> X["409: never asked, or already answered"]
    K -- "yes" --> T{"Within the time limit?"}
    T -- "no" --> X2["409: expired"]
    T -- "yes" --> F{"Tool name and arguments<br>equal what was proposed?"}
    F -- "no" --> X3["409: not the proposed call"]
    F -- "yes" --> OK["Remove from pending,<br>run the pipeline"]
    OK --> RULES["Tool applies its own rules,<br>ledger records once per key"]
    style OK fill:#F0FFF4,stroke:#1D8102,stroke-width:2px,color:#145202
    style RULES fill:#F0FFF4,stroke:#1D8102,stroke-width:2px,color:#145202
    style X fill:#FEF2F2,stroke:#D13212,stroke-width:2px,color:#991B1B
    style X2 fill:#FEF2F2,stroke:#D13212,stroke-width:2px,color:#991B1B
    style X3 fill:#FEF2F2,stroke:#D13212,stroke-width:2px,color:#991B1B`));
P.push(G.callout('warning','WHO CAN REACH THE ENDPOINT','In this sample the browser cannot send that forged request, because only the Blazor server calls the agent service. That is the arrangement Microsoft\'s guidance recommends: do not expose an AG-UI server directly to untrusted clients. With Blazor WebAssembly, or any JavaScript front end calling the agent endpoint itself, the browser is the client and the forged request is one fetch away. Authenticate the endpoint, keep it off the public network where possible, and verify approvals on the server either way. An approval button is a user interface. It is not an authorization check.'));
P.push(G.p('Three layers now stand between a request and a payment, and each covers a different failure: the approval check stops calls nobody proposed, the tool\'s own rule stops amounts the business would refuse whoever approved them, and the ledger key stops the same refund being paid twice.'));

P.push(G.h2('Stream size'));
P.push(G.p('The first raw capture of the stream was much larger than the one shown above. Each event carried a <code>rawEvent</code> field holding the entire model update it was made from, so a five-character piece of text travelled inside several hundred bytes of JSON. The same two requests, with the field left in and with it removed:'));
P.push(G.code('text',SN('@r/03a-findings.txt','Where is order O-1002?     events',null).replace(/\n+$/,'')));
P.push(G.p('Removing it is one line per event in the endpoint, and every test and browser step passes without it: the Blazor components read the typed event, not the raw copy. Besides the size, the field shows internal structure, including complete tool results, to whoever can read the response. The endpoint in the sample strips it by default.'));

P.push(G.h2('Testing'));
P.push(G.p('The seam at <code>IChatClient</code> gives four places to test, each cheaper than the next one up.'));
P.push(IM(2,'Four test layers for an agentic UI: the agent pipeline alone with 7 tests, the service over AG-UI on an in-memory server with 14 tests, the Blazor component in bUnit with 5 tests, and a browser run with 9 steps, with what each layer catches','What runs at each layer, and what it is for.'));
P.push(G.table(['Layer','How','Count','What it catches'],[
['Agent alone','The pipeline called as an <code>IChatClient</code>','7 tests','Tool logic, approval behaviour, payment rules, idempotency'],
['Agent over AG-UI','<code>AGUIChatClient</code> against the real endpoint on an in-memory test server, plus hand-written requests','14 tests','Event sequences, resume, state round trip, cancellation, forged approvals, stream size'],
['Component','bUnit renders the chat with the pipeline plugged in; the test types, clicks and reads markup','5 tests','Tool card, approval buttons, disabled input, text after Approve and Reject'],
['Browser','Playwright drives Chromium against both running services','9 steps','The real circuit, state panel, Stop, and that the browser never calls the agent']]));
P.push(G.p('A component test reads like a description of the feature. No browser and no HTTP are involved, and it runs in milliseconds:'));
P.push(G.code('csharp',SN('tests/Desk.Tests/DeskChatTests.cs','    [Fact]\n    public void A_refund_waits_for_a_click_and_pays_after_Approve()','\n    [Fact]\n    public void A_rejected_refund_pays_nothing_and_says_so()').replace(/\n+$/,'')));
P.push(G.p('The browser run is the only layer that needs both services up. Its transcript:'));
P.push(G.code('text',SN('@r/04-browser.txt','ok   order card from a backend tool',null).replace(/\n+$/,'')));
P.push(G.callout('info','TEST SCOPE','The scripted model always makes the sensible choice for a given conversation. A real model can call the wrong tool, call two at once, or answer in text when it should have asked for approval. These tests show that the UI, the protocol and the server rules behave correctly for the events they are given. They say nothing about the quality of a model\'s decisions, which needs its own evaluation.'));

P.push(G.h2('Cost'));
P.push(G.p('The agentic UI adds little to what the model already costs. The Blazor side is a circuit per user, as for any interactive server app, plus one outbound HTTP stream per run. The parts that scale with usage are in the stream: a text event per chunk the model produces, and, if left on, the raw copy that multiplied the bytes by 3.5 to 4 in this lab. Approvals add a second request per approved action, and the server-side check adds a short-lived record per pending approval, which wants a shared store once there is more than one instance.'));
P.push(G.p('The saving is in the pipeline. All 26 tests and the browser run complete in a few minutes on a hosted runner without a model key, so the agentic parts of the UI can be tested on every commit.'));

P.push(G.h2('Production considerations'));
P.push(G.ul([
'<strong>Treat the Blazor AI package as a preview.</strong> It is marked experimental and versioned 0.1.0. Pin it, keep it behind your own components, and expect renames.',
'<strong>Authenticate the agent endpoint and scope everything by caller.</strong> Thread ids, pending approvals and state arrive from the client. None of them is proof of identity.',
'<strong>Validate state like any other input.</strong> The page can send arbitrary JSON as state, and this sample puts it in front of the model. Use a schema and a size limit.',
'<strong>Keep rules in the tools.</strong> The approval check proves the call was proposed. Only the tool can say whether it should be allowed.',
'<strong>Handle the stream ending without a final event.</strong> Stop, a dropped connection and a restarted instance all look the same to the client.',
'<strong>Decide what a refresh means.</strong> The conversation here lives in the circuit. A reload loses it, and a pending approval with it. Persisting threads is a separate design.',
'<strong>Render tool arguments with care.</strong> The default approval block shows raw JSON arguments. For anything a person must judge, show them the way the business would describe the action.',
'<strong>Trace both sides.</strong> The AG-UI client and server packages each expose an activity source. Join them to the model call so one approval can be followed end to end.']));
P.push(G.callout('compliance','AUDIT','An approval is a decision by a named person about a specific action. Record who approved what, with the arguments as proposed and the outcome, in the system that performs the action. The chat transcript is not that record.'));

P.push(G.h2('Decision framework'));
P.push(G.table(['Your situation','Approach','Why'],[
['Blazor app, agent owned by the same team','Interactive server, agent as a separate service, AG-UI between','The browser never reaches the agent endpoint'],
['Blazor WebAssembly or a JavaScript front end','Put a trusted backend in front of the agent, authenticate, verify approvals','The browser is the AG-UI client and can send any request'],
['Tool does something irreversible','Approval required, verified server-side, with rules and an idempotency key in the tool','Three different failures, three different controls'],
['Tool only reads','Typed tool block and a card','No approval needed; the value is in the rendering'],
['Agent and user edit the same form','Shared state with snapshots, validated on the way in','One state object, no private protocol'],
['No .NET 11 yet','AG-UI client and server run on .NET 8 and later; build the rendering yourself','The Blazor AI components target .NET 11 only'],
['Production deadline this quarter','Use the protocol packages now, wrap the preview components','The 1.0 packages are stable; the components are not']]));

P.push(G.h2('Key takeaways'));
P.push(G.ul([
'An agentic UI is a typed stream of events: text, tool calls, state, and a run that can end by asking for a decision. AG-UI gives that stream a vocabulary, and it is plain HTTP and Server-Sent Events.',
'On .NET 11 the experimental Blazor AI components render that stream with little code: a typed tool card is one attribute and one component, approval needs none.',
'Depend on <code>IChatClient</code> in the UI and swap the model for a scripted one in tests. That gave 26 tests and a nine-step browser run with no model key.',
'An approval travels as a second request that names the tool call. Without a server-side check, one forged request ran a refund nobody proposed. Remember what you proposed and verify it.',
'Strip <code>rawEvent</code> unless you need it. It made the stream 3.5 to 4 times larger here.']));
P.push(G.p('If you have built on these components with a real model behind them, I would like to hear which of these edges you met first.'));
P.push(G.callout('note','HOW THIS WAS CHECKED','Everything above ran in GitHub Actions on a hosted Linux runner with .NET SDK 11.0.100 and runtime 11.0.0, <code>Microsoft.AspNetCore.Components.AI</code> 0.1.0-preview.1.26466.103, <code>AGUI.Client</code>, <code>AGUI.Server</code> and <code>AGUI.Formatting</code> 1.0.1, <code>Microsoft.Extensions.AI</code> 11.0.0, bUnit 2.15.2 and Chromium through Playwright. 26 tests passed: 7 on the agent pipeline, 14 over AG-UI against an in-memory test server, 5 on the Blazor component in bUnit. 9 of 9 browser steps passed against the two running services. The event sequences, the interrupt and resume payloads, the raw stream, the forged-approval results and the stream sizes are copied from that run. The model was a scripted stand-in and all orders are invented. Not run: any language model; Microsoft Agent Framework hosting; Blazor WebAssembly or Auto render modes; authentication; more than one server instance; load. The forged-approval result applies to this endpoint, built on <code>AGUI.Server</code> 1.0.1; other hosting layers were not tested. <a href="https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/44300093955">The run is here</a>.'));
P.push('<!-- wp:html -->\n<div class="callout callout-tip sample-code-link" style="background: #e8f5e9; border-left: 4px solid #4caf50; padding: 16px 20px; margin: 20px 0; border-radius: 4px;"><div style="display: flex; align-items: start;"><span style="font-size: 24px; margin-right: 12px;">💡</span><div><strong style="color: #388e3c; display: block; margin-bottom: 8px;">GET THE CODE</strong><p style="margin: 0; color: #333;">The complete sample for this article is on GitHub: <a href="https://github.com/nithinmohantk/blog-samples-working-repo/tree/main/agentic-ui-blazor" target="_blank" rel="noopener">nithinmohantk/blog-samples-working-repo/agentic-ui-blazor</a>. Clone it with <code>git clone https://github.com/nithinmohantk/blog-samples-working-repo.git</code> and open the <code>agentic-ui-blazor</code> folder. Its README says how to run it and what has been verified.</p></div></div></div>\n<!-- /wp:html -->');
P.push(G.h2('Glossary'));
P.push(G.box([
G.term('Agentic UI','A user interface that renders what an agent does, not only what it says: tool calls, approvals and state changes.'),
G.term('AG-UI','An open protocol for the event stream between an agent and a user interface.'),
G.term('Run','One request to an agent and the events it produces, from RUN_STARTED to RUN_FINISHED.'),
G.term('Interrupt','A run that ends by asking for a decision instead of finishing the work.'),
G.term('Resume','The entry in the next request that answers an interrupt.'),
G.term('Shared state','A JSON object that both the agent and the page read and change.'),
G.term('IChatClient','The Microsoft.Extensions.AI abstraction for a chat model, which pipelines and clients both implement.'),
G.term('Interactive server','The Blazor render mode where components run on the server and the browser holds a SignalR circuit.'),
G.term('bUnit','A library that renders Blazor components in memory for tests.'),
G.term('Idempotency key','A value that lets the receiver recognise a repeated request and act once.')]));
P.push(G.h2('References &amp; Further Reading'));
P.push(G.box([
G.ref('https://learn.microsoft.com/en-us/aspnet/core/release-notes/aspnetcore-11','What\'s new in ASP.NET Core in .NET 11','Blazor changes, including the experimental AI components package'),
G.ref('https://devblogs.microsoft.com/dotnet/build-agentic-ui-blazor/','.NET Blog: Build agentic UI with Blazor','Microsoft\'s walkthrough of the components with Agent Framework and Foundry'),
G.ref('https://devblogs.microsoft.com/dotnet/ag-ui-dotnet-sdk/','.NET Blog: The AG-UI .NET SDK','The protocol packages, the server and client APIs and the renamed Agent Framework methods'),
G.ref('https://learn.microsoft.com/agent-framework/integrations/ag-ui/getting-started','Agent Framework: Getting started with AG-UI','MapAGUIServer hosting and the client, for comparison with the endpoint built here'),
G.ref('https://learn.microsoft.com/en-us/agent-framework/integrations/by-component/ui/ag-ui/security-considerations','Agent Framework: AG-UI security considerations','Untrusted clients, state validation, thread ownership and approval state'),
G.ref('https://github.com/ag-ui-protocol/ag-ui/tree/main/sdks/dotnet','AG-UI .NET SDK source','The packages and the getting-started samples, including approvals and state'),
G.ref('https://github.com/dotnet/aspnetcore/tree/main/src/Components/AI','ASP.NET Core: Components/AI source','The components, their tests and the sample apps they are tested with'),
G.ref('https://github.com/nithinmohantk/blog-samples-working-repo/tree/main/agentic-ui-blazor','Sample code for this article','The agent service, the Blazor app, four layers of tests and the pipeline script')]));
})();
