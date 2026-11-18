(()=>{const G=window.G,SN=window.SN,P=window.PARTS,IM=window.IM;
P.push(G.h2('Wire format'));
P.push(G.p('AG-UI over HTTP is a POST with a JSON body and a response of Server-Sent Events. It can be read with curl. This is the complete response to "Where is order O-1002?", as the pipeline captured it:'));
P.push(G.code('text',SN('@r/05-raw-sse.txt','data: {"type":"RUN_STARTED"',null).replace(/\n+$/,'')));
P.push(G.p('Every scenario in the sample is a variation on that sequence. The tests record them:'));
P.push(G.table(['Scenario','Events, in order'],[
['Text','<code>RUN_STARTED</code>, <code>TEXT_MESSAGE_START</code>, <code>TEXT_MESSAGE_CONTENT</code> ×27, <code>TEXT_MESSAGE_END</code>, <code>RUN_FINISHED</code>'],
['Backend tool','<code>RUN_STARTED</code>, <code>TOOL_CALL_START</code>, <code>TOOL_CALL_ARGS</code>, <code>TOOL_CALL_END</code>, <code>TOOL_CALL_RESULT</code>, text message, <code>RUN_FINISHED</code>'],
['Approval, first run','<code>RUN_STARTED</code>, <code>TOOL_CALL_START</code>, <code>TOOL_CALL_ARGS</code>, <code>TOOL_CALL_END</code>, <code>RUN_FINISHED</code> with outcome <code>interrupt</code>'],
['Approval, second run','<code>RUN_STARTED</code>, the same tool call again, <code>TOOL_CALL_RESULT</code>, text message, <code>RUN_FINISHED</code>'],
['Shared state','<code>RUN_STARTED</code>, tool call, <code>TOOL_CALL_RESULT</code>, <code>STATE_SNAPSHOT</code>, text message, <code>RUN_FINISHED</code>'],
['Stopped by the user','<code>RUN_STARTED</code>, <code>TEXT_MESSAGE_START</code>, <code>TEXT_MESSAGE_CONTENT</code> ×3, then the stream ends. No <code>RUN_FINISHED</code>']]));
P.push(IM(1,'AG-UI events on the wire for six scenarios: text, backend tool, approval first run ending in an interrupt, approval second run with resume, shared state with a state snapshot, and a stopped run with no RUN_FINISHED','The event sequences recorded by the wire tests.'));
P.push(G.p('Two of those rows are worth a closer look. An approval is not a pause inside one request. The first run ends, with an outcome that says why:'));
P.push(G.code('json',SN('@r/wire-traces.txt','{\n  "type": "RUN_FINISHED",','request 2:').replace(/\n+$/,'')));
P.push(G.p('The answer is a second, separate request. It carries a <code>resume</code> entry, and that entry contains the decision and the tool call it applies to:'));
P.push(G.code('text',SN('@r/wire-traces.txt','request 2: messages=[user] state=none resume=[{"interruptId"','\nevents 2:')));
P.push(G.p('The server holds nothing between the two requests. That is what makes the endpoint easy to scale, and it is also the source of the security finding further down.'));
P.push(G.p('The stopped run shows the other thing to plan for. When the user presses Stop, the client drops the connection, the server\'s cancellation token fires, and the stream simply ends. A client that waits for <code>RUN_FINISHED</code> before tidying up will wait for ever.'));

P.push(G.h2('Blazor components'));
P.push(G.p('The web app registers one service: a chat client that speaks AG-UI to the agent.'));
P.push(G.code('csharp',SN('src/Desk.Web/Program.cs','// The UI does not know there is a model.','\nWebApplication app = builder.Build();').replace(/\n+$/,'')));
P.push(G.p('The page is composed from the lower-level components, so that a Stop button and a side panel can sit inside the same agent boundary:'));
P.push(G.code('razor',SN('src/Desk.Web/Components/DeskChat.razor','<div class="desk">','\n@code {').replace(/\n+$/,'')));
P.push(G.p('<code>AgentBoundary</code> cascades an <code>AgentContext</code> to everything inside it. <code>MessageList</code> renders the conversation as blocks: text, tool calls, approvals. <code>BlockRenderer</code> replaces the rendering of one block type. <code>MessageInput</code> sends, and disables itself while a run is streaming or an approval is waiting.'));
P.push(G.p('<strong>A typed tool card.</strong> A tool call arrives as a name and a bag of JSON. A source generator turns it into a typed object, filling the argument properties as they stream in and the result property when it arrives:'));
P.push(G.code('csharp',SN('src/Desk.Web/Components/OrderToolBlock.cs','[ToolBlock("get_order")]',null).replace(/\n+$/,'')));
P.push(G.p('The card is then an ordinary component with a loading state and a result state. The contract between the UI and the agent is the JSON of the tool result, not a shared assembly.'));
P.push(G.p('<strong>Approval.</strong> There is no approval code in the page at all. The default rendering of an approval block shows the tool name, its arguments and two buttons, and the buttons call <code>Approve</code> or <code>Reject</code> on the block. Replacing that with a designed dialog is one more <code>BlockRenderer</code>.'));
P.push(IM(3,'Screenshot of the order desk in Chromium: an order card for O-1001 rendered from a tool call, then an approval block for refund_order with the arguments and Approve and Reject buttons, and an empty draft reply panel on the right','The running app in the browser test, before Approve is clicked.'));
P.push(G.p('<strong>Shared state.</strong> The agent is created with a state type. Outbound, each request carries the current state. Inbound, a state snapshot event replaces it:'));
P.push(G.code('csharp',SN('src/Desk.Web/Components/DeskChat.razor','    protected override void OnInitialized()','\n    public void Dispose()').replace(/\n+$/,'')));
P.push(G.p('The panel binds to <code>_agent.State</code> and subscribes to its change notification, because the agent changes the state from outside the render cycle. In the browser run the user typed a signature into the panel, asked for a formal draft, and the draft came back signed: state went from page to agent to tool and back.'));
P.push(G.p('<strong>Stop.</strong> Cancelling is one call on the cascaded context:'));
P.push(G.code('razor',SN('src/Desk.Web/Components/StopButton.razor','@implements IDisposable',null).replace(/\n+$/,'')));
})();
