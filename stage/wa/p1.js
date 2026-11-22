(()=>{const G=window.G,SN=window.SN,P=window.PARTS,IM=window.IM;
const A1='<a href="https://www.dataa.dev/2026/11/18/building-an-agentic-ui-with-blazor-and-dotnet-11/">Building an Agentic UI with Blazor and .NET 11</a>';
const A2='<a href="https://www.dataa.dev/2026/11/25/agent-framework-hosting-vs-hand-built-ag-ui-endpoint-dotnet-11/">Agent Framework Hosting vs a Hand-Built AG-UI Endpoint</a>';
P.push(G.p('The order desk in '+A1+' ran its Blazor components on the server. The browser held a SignalR connection and nothing else, so the only program that could call the agent service was one I had written. That is why the forged approval in that article needed somebody already inside the network.'));
P.push(G.p('Move the same components to Blazor WebAssembly and that protection is gone. The AG-UI client now runs in the browser, and whatever the page can send, anybody with the developer tools open can send too. The agent endpoint has to know who is asking on every request, and a refund has to know who approved it.'));
P.push(G.p('I rebuilt the order desk that way and tested it in a pipeline: a WebAssembly client, a web host that keeps the session in a cookie, and an agent service that accepts only a short-lived token for a named person. The components moved to the browser without a change to their markup. The work was in three places the first article did not need: tying each pending approval to the person it was asked of, giving the refund tool the caller\'s identity, and deciding what happens when the session ends halfway through a conversation.'));

P.push(G.h2('The problem'));
P.push(G.p('An agentic UI makes authorisation harder than an ordinary web API does, for one reason. The request that moves money is not "refund order O-1001". It is "here is my answer to the approval you asked for", and the tool call being approved travels inside that request. A token that proves the request came from a signed-in person says nothing about whether that person was the one asked, or whether they are allowed to approve that amount.'));
P.push(G.p('So there are three separate questions, and a design that answers only the first is still open:'));
P.push(G.ul([
'<strong>Who is calling?</strong> Authentication, on every request, at a service the browser cannot reach around.',
'<strong>Is this approval theirs to give?</strong> The approval must have been asked of this person, for this call, and not answered before.',
'<strong>May they approve this much?</strong> A rule about the person and the amount, enforced where the money moves.']));
P.push(G.p('There is also a question about the browser itself. A WebAssembly app is downloaded code. It can be read, changed and replayed, and anything it stores can be stolen by a script that gets into the page. Where the credentials live decides how bad that day is.'));

P.push(G.h2('Architecture'));
P.push(G.mer(G.MF+`
flowchart TD
    S["Sign-in page:<br>lab stand-in for OpenID Connect"] --> H
    B["Browser: Blazor WebAssembly app,<br>AGUIChatClient, holds no token"] -- "POST /agent with the session cookie<br>and an X-Desk-Client header" --> H["Web host: cookie session,<br>forwards the event stream"]
    H -- "Bearer token for this person,<br>valid for two minutes" --> A["Agent service: validates the token,<br>ties each approval to a person"]
    A --> T["refund_order tool:<br>asks who the caller is"]
    T --> L["Ledger: one refund per order,<br>with who approved it"]
    style B fill:#EBF8FF,stroke:#0073BB,stroke-width:2px,color:#004C74
    style S fill:#EBF8FF,stroke:#0073BB,stroke-width:2px,color:#004C74
    style H fill:#FFF3E0,stroke:#FF9900,stroke-width:2px,color:#232F3E
    style A fill:#F3E8FF,stroke:#7C3AED,stroke-width:2px,color:#4C1D95
    style T fill:#F3E8FF,stroke:#7C3AED,stroke-width:2px,color:#4C1D95
    style L fill:#F0FFF4,stroke:#1D8102,stroke-width:2px,color:#145202`));
P.push(G.p('This is the backend-for-frontend arrangement. The browser talks only to the host that served it. The session is an HttpOnly cookie, which the page\'s own code cannot read. The host swaps the cookie for a short-lived token addressed to the agent service and passes the event stream back as it arrives. RFC 10017, the IETF\'s current best practice for browser-based applications, ranks this pattern first for security and recommends it for business applications and anything that handles personal data. Microsoft\'s Blazor guidance for OpenID Connect uses the same shape.'));
P.push(G.p('The alternative is to give the browser an access token and let it call the agent service directly. That removes a hop and adds CORS, token storage in the page and token refresh in the page. I did not build it. For an endpoint whose requests can move money, I would want a strong reason to put the token where a script can reach it.'));
P.push(IM(1,'Four columns showing what the browser, the web host, the agent service and the refund tool each hold, check and refuse: the browser holds only an HttpOnly cookie, the web host checks the session and a custom header, the agent service validates the token and the approval owner, and the refund tool applies the approver limit','What each layer holds, what it checks, and how it refuses.'));
P.push(G.callout('info','STAND-INS','Three parts of this sample are stand-ins, so that the pipeline needs no account anywhere. Sign-in is a page with two buttons for two invented people, Sam at the order desk and Alex the supervisor. The token is signed with a fake key that sits in the public repository. The model is the scripted one from the first article. The cookie session, the token validation, the approval checks and the tool rule are real code.'));

P.push(G.h2('The web host'));
P.push(G.p('The host has three jobs: serve the WebAssembly app to signed-in people, keep the session, and forward <code>/agent</code>. The cookie setup is where the first decisions are made:'));
P.push(G.code('csharp',SN('src/Desk.Bff/Program.cs','// The session is a cookie','builder.Services.AddAuthorization();')));
P.push(G.p('<code>HttpOnly</code> keeps the cookie away from script. <code>SameSite=Strict</code> keeps it off requests that start on another site. The redirect handler matters more than it looks: by default an expired session answers an API call with a redirect to an HTML sign-in page, which a streaming client then tries to parse as events. A call from code should get a plain 401.'));
P.push(G.p('The forwarder is thirty lines. It refuses a request that lacks a custom header, builds a token for the signed-in person, and copies the response through without buffering:'));
P.push(G.code('csharp',SN('src/Desk.Bff/AgentForwarder.cs','    public static async Task ForwardAsync','\n}')));
P.push(G.p('The header check is the cross-site defence. A page on another site can make a browser send a form post with the victim\'s cookie, but it cannot add a custom header without a CORS preflight, and this host allows no other origin. The OWASP cheat sheet describes the technique and is clear that it is one layer: the SameSite attribute is the second.'));
P.push(G.p('Two details are easy to get wrong. <code>DisableBuffering</code> and the flush after every read are what keep the answer arriving word by word; without them a proxy can hold the whole response until the run ends. And <code>RequestAborted</code> is passed to every call, because that is how a Stop click in the browser becomes a cancelled run on the agent service.'));
P.push(G.callout('tip','USE A PROXY LIBRARY IN PRODUCTION','I wrote the forwarder by hand so that every line of the hop is visible. In a real system use YARP, as Microsoft\'s Blazor sample does with <code>MapForwarder</code> and a request transform that attaches the token. It handles header rules, timeouts and HTTP/2 that thirty lines do not.'));
})();
