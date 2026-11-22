(()=>{const G=window.G,SN=window.SN,P=window.PARTS,IM=window.IM;
P.push(G.h2('Test setup'));
P.push(G.p('Everything ran in GitHub Actions on a hosted Linux runner with .NET SDK 11.0.100. There are two layers of tests.'));
P.push(G.ul([
'<strong>23 xUnit tests on in-memory servers.</strong> The agent service is called with tokens the tests make themselves: valid, expired, addressed to another audience, signed with another key, unsigned, and edited after signing. Then the web host is put in front of it with a test client that keeps cookies the way a browser does.',
'<strong>11 browser steps.</strong> Chromium, driven by Playwright, against the <em>published</em> output of both services: the trimmed and compressed WebAssembly app, as it would be deployed. Sizes are read from the browser\'s own network log.']));
P.push(G.p('The model is scripted, so every run makes the same decisions. All orders, customers and people are invented.'));

P.push(G.h2('Test results'));
P.push(G.p('<strong>Tokens.</strong> The agent service refused every token that was not exactly right, and no refused request reached the agent pipeline:'));
P.push(G.code('text',SN('@r/auth-results.txt','agent service | expired token','approval asked of sam')));
P.push(G.p('The unsigned token is the old <code>alg: none</code> trick, and the edited one changes the role from agent to supervisor and keeps the original signature. Both are 401. A valid token for a person with no desk role is 403: authenticated, not allowed.'));
P.push(G.p('<strong>Approvals belong to a person.</strong> Sam asked for a refund on O-1003 and the run stopped for approval. Alex, with a valid supervisor token, sent the approval. The answer was 403 and nothing was paid. Sam then sent the same approval and it was paid once, recorded against Sam. The failed attempt did not use up the pending approval.'));
P.push(G.p('<strong>The limit is applied to the approver.</strong>'));
P.push(G.table(['Refund','Approved by','Result','Ledger'],[
['O-1003, 37.50','Sam (limit 40.00)','The refund is recorded','1 refund, approvedBy sam'],
['O-1001, 42.00','Sam (limit 40.00)','Refused, a supervisor has to approve','0 refunds'],
['O-1001, 42.00','Alex (supervisor)','The refund is recorded','1 refund, approvedBy alex']]));
P.push(G.p('<strong>A forged approval with a real token.</strong> The first article forged an approval with no identity at all. This time the forger is Sam, signed in, sending one hand-written POST that approves a refund the agent never proposed:'));
P.push(G.table(['Forged refund','Approval check','HTTP','Refunds'],[
['O-1001, 42.00','On','409','0'],
['O-1002, 18.25','On','409','0'],
['O-1001, 42.00','Off','200','0, the tool refused it as above Sam\'s limit'],
['O-1002, 18.25','Off','200','1, paid']]));
P.push(G.p('The last row is the reason authentication does not replace the approval check. Sam is who the token says, Sam is allowed to approve 18.25, and the refund was still one the agent never proposed and nobody was asked about. The tool\'s rule limits the damage to what the person could have approved anyway. Only the server-side approval table stops it.'));
P.push(IM(2,'Table of ten requests and what happened to each: no session redirects to sign-in, a request without the custom header is 400, six kinds of bad token are 401, a wrong role is 403, an approval answered by another person is 403, forged approvals are 409 with the check on, and with the check off a small forged refund is paid','Every refusal measured in the run, and the two results to design around.'));
P.push(G.p('<strong>A stream outlives its token.</strong> One test issues a token valid for three seconds, with no clock allowance, and asks a question whose answer streams for 23.5 seconds. The stream ran to <code>RUN_FINISHED</code>. The next request with the same token was 401. The token is checked when the request arrives and not again. A two-minute token therefore bounds when a run can start, not how long it can go on, and revoking a person\'s access does not end a run that is already streaming. If that matters, put a time limit on the run itself.'));
P.push(G.p('<strong>In the browser.</strong> All eleven steps passed against the published app:'));
P.push(G.table(['Step','What was observed'],[
['Open the app with no session','Redirected to the sign-in page; the app shell is not served'],
['First load after sign-in','68 responses, 3,002 KiB over the wire, 2,994 KiB of it under <code>/_framework/</code>, Brotli and gzip'],
['Reload','59 of 68 responses from the browser cache, 5 KiB over the wire'],
['Streaming','Words of the answer on the page at 0.6 s intervals: 7, 11, 15, 19, 23'],
['Stop','The agent service\'s stream ended after 22 events with no <code>RUN_FINISHED</code>'],
['What the page can read','<code>document.cookie</code> empty; no request carried an <code>Authorization</code> header; the browser talked to one host'],
['POST without the custom header','400'],
['Cookie removed mid-conversation','The next question ended at the sign-in page; the conversation on the page was lost'],
['Sam, then Alex, on O-1001','Refused for Sam, paid for Alex, ledger shows who approved each refund']]));
P.push(G.p('Streaming worked in WebAssembly with no extra setting: the answer grew on the page while the server was still writing it, through the browser\'s fetch, the forwarder and back. The browser console showed two errors in the whole run, the 400 and the 401 the tests caused on purpose.'));
P.push(G.p('The load times were 1.7 seconds from sign-in to a usable chat with an empty cache and 1.2 seconds on reload. Both were measured on one machine with no network between browser and server, so they show start-up cost and say nothing about a real connection. The 3 MiB is the number to carry to a slow link.'));

P.push(G.h2('Cost'));
P.push(G.p('The price of moving to the browser is a download. The published <code>_framework</code> folder holds 68 files: 13.78 MiB as built, 3.81 MiB as Brotli. A first visit pulled 3.0 MiB. That is less than the whole folder, which also holds source maps and three sets of globalisation data. The largest parts are the .NET runtime (980 KiB compressed) and the core library (627 KiB). The AI components, the AG-UI client and <code>Microsoft.Extensions.AI</code> are small next to them.'));
P.push(G.p('What it buys is on the server. The Blazor Server version held a circuit and a WebSocket for every open tab, with the component state in server memory. Here the host holds nothing between requests but a cookie key, and an idle tab costs nothing. I did not measure server memory per user for either version, so treat that as the design difference and not as a number.'));
P.push(G.p('The pipeline spends nothing on models or identity providers. The whole run, from restore to the last browser step, took a little over two minutes on a hosted runner.'));

P.push(G.h2('Production considerations'));
P.push(G.ul([
'<strong>Replace the stand-ins in this order.</strong> Sign-in becomes OpenID Connect against your identity provider. The token becomes one the host obtains from that provider for the agent service\'s audience. Then delete <code>LabTokenIssuer</code> and the key.',
'<strong>The app\'s code is public.</strong> The framework files are served to anybody; one request with no session returned the script. Everything in the client project ships to the browser. The publish step checks that no server project and no key is in the bundle, and that check is worth keeping.',
'<strong>Decide what a lost session costs.</strong> Here it costs the conversation, including any approval that was waiting. A 30-minute fixed session is a reasonable default for a desk tool; whether the conversation should survive it is a product decision.',
'<strong>Bound the run, not only the token.</strong> A stream continued for twenty seconds after its token expired. Give long runs their own time limit and a way to cancel them from the server.',
'<strong>Keep the approval table shared.</strong> It is in memory on one instance. With two instances an approval asked by one is unknown to the other, and the honest answer is a 409.',
'<strong>Log refusals.</strong> A 403 on an approval and a 409 on a forged one are the signals somebody is probing the endpoint. Log the subject, the interrupt id and the reason; do not log the token.',
'<strong>Rate limits belong on the host.</strong> A signed-in browser can now start runs as fast as it can post. None is set in this sample.']));
P.push(G.callout('compliance','PERSONAL DATA IN THE BROWSER','Server-side Blazor kept the conversation in server memory. In WebAssembly the whole conversation, including anything the tools return, is in the browser\'s memory and is sent back on every request. If tool results contain personal data, the browser is now a place that data is processed, and the device it runs on is in scope for your data protection assessment.'));

P.push(G.h2('Decision framework'));
P.push(G.table(['If this is true','Prefer','Why'],[
['Internal tool, stable network, a few hundred users','Blazor Server, as in the first article','No download, no public endpoint, and the browser cannot call the agent at all'],
['Many users, idle tabs, or a need to scale the web tier without sticky sessions','WebAssembly behind a web host, as here','No circuit per tab; the host is stateless apart from the cookie key'],
['The agent service is called by other back ends too','WebAssembly behind a web host','The agent service already validates a token per person; other callers get their own audience'],
['A JavaScript front end or a mobile app must call the agent directly','Tokens in the client, with the approval table and the tool rule unchanged','Not tested here; RFC 10017 ranks it below a backend for frontend'],
['An approval must be given by a different person than the one who asked','Neither as built','The conversation has to live on the server first']]));
P.push(G.p('For this order desk I would ship the arrangement in this article. The browser holds nothing worth stealing, the agent service can sit on a private network, and each of the three questions from the start has one place where it is answered: the token handler, the approval table and the refund tool.'));

P.push(G.h2('Key takeaways'));
P.push(G.ul([
'The Blazor AI components ran in WebAssembly unchanged, published and trimmed, with streaming and Stop working through a forwarding host.',
'In the browser the page is the AG-UI client. Keep the session in an HttpOnly cookie on the host and give the browser no token.',
'Authentication does not make an approval safe. A signed-in person forged an approval for a refund nobody proposed, and with the server-side check off it was paid.',
'Tie each pending approval to the person it was asked of, and compare the owner before removing the entry.',
'Put the amount rule in the tool, fed by the caller\'s validated identity and never by the model.',
'A token is checked when a request starts. A run that is already streaming continues after the token expires.',
'The first visit downloaded 3.0 MiB. A reload downloaded 5 KiB.']));

P.push(G.callout('note','HOW THIS WAS CHECKED','Everything in this article comes from one pipeline run on 22 November 2026: <a href="https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/45003297156" target="_blank" rel="noopener">GitHub Actions run 45003297156</a>, commit <code>d895d20</code>, with the transcripts, the recorded results and the screenshots on the <code>ci-results-agentic-ui-wasm-auth</code> branch. 23 xUnit tests passed on in-memory servers and 11 Chromium steps passed against the published output, on .NET SDK 11.0.100 with <code>Microsoft.AspNetCore.Components.AI</code> 0.1.0-preview.1.26466.103, <code>Microsoft.AspNetCore.Components.WebAssembly</code> and <code>Microsoft.AspNetCore.Authentication.JwtBearer</code> 11.0.0, the AG-UI packages 1.0.1 and <code>Microsoft.Extensions.AI</code> 11.0.0. Not done: no identity provider was used, sign-in and the token issuer are stand-ins; no real model was called; the browser-holds-a-token alternative was not built; YARP was not used; ahead-of-time compilation of the WebAssembly app was not tried; load times were measured on one machine with no network in between; server memory per user was not measured; the approval table is in memory on one instance; one preview build of the Blazor AI components was tested and later builds may behave differently.'));
P.push(window.GETCODE);
P.push(G.h2('References &amp; Further Reading'));
P.push(G.box([
G.ref('https://www.dataa.dev/2026/11/18/building-an-agentic-ui-with-blazor-and-dotnet-11/','Building an Agentic UI with Blazor and .NET 11','The first article: the components, the hand-built endpoint and the forged approval'),
G.ref('https://www.dataa.dev/2026/11/25/agent-framework-hosting-vs-hand-built-ag-ui-endpoint-dotnet-11/','Agent Framework Hosting vs a Hand-Built AG-UI Endpoint in .NET 11','The second article: the same UI on Agent Framework hosting, with sessions'),
G.ref('https://datatracker.ietf.org/doc/rfc10017/','RFC 10017: OAuth 2.0 for Browser-Based Applications','The IETF best current practice that ranks the backend-for-frontend pattern first'),
G.ref('https://learn.microsoft.com/aspnet/core/blazor/security/blazor-web-app-with-oidc','Secure an ASP.NET Core Blazor Web App with OpenID Connect','Microsoft\'s backend-for-frontend sample with YARP, token storage in the cookie and token refresh'),
G.ref('https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html','OWASP Cross-Site Request Forgery Prevention Cheat Sheet','Custom request headers and SameSite cookies, and the limits of each'),
G.ref('https://learn.microsoft.com/en-us/agent-framework/integrations/by-component/ui/ag-ui/security-considerations','Agent Framework: AG-UI security considerations','Untrusted clients, thread ownership and approval state'),
G.ref('https://github.com/nithinmohantk/blog-samples-working-repo/tree/main/agentic-ui-wasm-auth','Sample code for this article','The WebAssembly client, the web host, the agent service, the tests and the pipeline script')]));
})();
