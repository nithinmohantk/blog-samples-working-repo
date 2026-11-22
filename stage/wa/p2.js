(()=>{const G=window.G,SN=window.SN,P=window.PARTS,IM=window.IM;
P.push(G.h2('The agent service'));
P.push(G.p('The agent service trusts nothing but the token. It validates the signature, issuer, audience and lifetime, and maps the token\'s roles to a policy:'));
P.push(G.code('csharp',SN('src/Desk.Agent/Program.cs','// Every request needs a token','\n\nbuilder.Services.AddHttpContextAccessor')));
P.push(G.p('With a real identity provider the key disappears: set <code>Authority</code> and <code>Audience</code> and the handler fetches the signing keys itself. Pinning <code>ValidAlgorithms</code> is worth keeping either way.'));
P.push(G.p('The endpoint is the one from the first article with two additions. It works out who the caller is, and it passes that person to the approval check on the way in and to the approval watcher on the way out:'));
P.push(G.code('csharp',SN('src/Desk.Agent/Program.cs','app.MapPost("/agent", (','\n\n// For the lab only')));
P.push(G.p('The approval table now records who each approval was asked of. The order of the checks inside <code>Redeem</code> is the part I got wrong in my head before I wrote the test:'));
P.push(G.code('csharp',SN('src/Desk.Agent/PendingApprovals.cs','    public ApprovalRefusal? Redeem','\n}')));
P.push(G.p('The first article removed the pending entry and then compared the call. Add an owner check after the removal and anybody with a valid token can cancel somebody else\'s pending approval by answering it wrongly. The owner is compared first, and the entry is removed only when the right person answers.'));
P.push(G.mer(G.MS+`
sequenceDiagram
    participant B as Browser (Sam)
    participant H as Web host
    participant A as Agent service
    participant L as Ledger
    B->>H: Refund order O-1001 (cookie, header)
    H->>A: Same request, Bearer token for Sam
    A-->>B: Events, run ends on an interrupt
    Note over A: Pending approval stored for Sam
    B->>H: Approve, with the proposed call
    H->>A: Same request, new token for Sam
    Note over A: Owner is Sam, call matches
    A->>L: refund_order as Sam, 42.00
    L-->>A: Refused, above Sam's limit of 40.00
    A-->>B: The agent says a supervisor has to approve`));
P.push(G.p('The last rule lives in the tool, because the tool is where money moves. It asks who the caller is at the moment it runs:'));
P.push(G.code('csharp',SN('src/Desk.Core/DeskTools.cs','        // The last check before money moves','\n\n        // The key comes from')));
P.push(G.p('The caller comes from the request\'s validated token through a function the service passes in when it builds the pipeline:'));
P.push(G.code('csharp',SN('src/Desk.Agent/Program.cs','// The tools ask who the caller is','\n\nWebApplication app')));
P.push(G.p('Nothing about the caller is put into the conversation. The model is not told who the user is or what they may approve, and it has no argument through which it could say. An instruction hidden in an order note can talk the model into proposing a refund; it cannot change who approved it. The ledger entry records the approver, which is the audit trail a refund needs.'));
P.push(G.callout('warning','A LIMIT THE USER CANNOT SEE','The refusal comes back as a tool result, so the run continues and the agent explains it in words. The default approval block still shows "Approved" in green above that explanation, because the label reports the click and not the outcome. In a real desk I would either hide the Approve button when the amount is above the person\'s limit or route the request to a supervisor\'s queue. Both need the conversation to live on the server, which is the subject of a later article.'));

P.push(G.h2('The client in the browser'));
P.push(G.p('The components, the tool card, the shared-state panel and the Stop button are the files from the first article. What changes is where the chat client points and what happens around it:'));
P.push(G.code('csharp',SN('src/Desk.Client/Program.cs','// Same origin','\n\nawait builder')));
P.push(G.p('There is no token code here because there is no token here. The browser attaches the cookie to a same-origin request by itself. When the session has ended, the host answers 401 and one small handler sends the person to sign in:'));
P.push(G.code('csharp',SN('src/Desk.Client/SessionHandler.cs','public sealed class SessionHandler')));
P.push(G.p('One change was forced by publishing. A published WebAssembly app is trimmed, and JSON serialisation that discovers properties by reflection is what trimming breaks first. The shared state and the tool result now use metadata generated at build time:'));
P.push(G.code('csharp',SN('src/Desk.Client/Components/Contracts.cs','[JsonSourceGenerationOptions(JsonSerializerDefaults.Web)]')));
P.push(G.p('The host renders nothing on the server. Its root component is a shell that starts the app in the browser with prerendering off, so no component ever runs in two places and no service has to exist on both sides.'));
P.push(IM(3,'Screenshot of the order desk running as a WebAssembly app in Chromium, signed in as Sam: a refund of 37.50 on order O-1003 is recorded, then a refund of 42.00 on order O-1001 shows Approved but the agent answers that it is above the approval limit and a supervisor has to approve it','Sam approves 42.00, above the limit of 40.00. The click is accepted; the tool refuses.'));
})();
