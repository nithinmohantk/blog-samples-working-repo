(()=>{const G=window.G,SN=window.SN,P=window.PARTS,IM=window.IM;
P.push(G.h2('Approvals on the agent service'));
P.push(G.p('Everything so far is about the web app. The other half of a pending approval is on the agent service: the table that says "I proposed exactly this call and am waiting". The first article kept it in a dictionary and said so. A conversation that survives a restart of the web app makes that dictionary the next thing to break, because the user can now come back after the agent service has restarted too.'));
P.push(G.p('The table sits behind a two-method interface now, with a SQLite implementation. Taking an approval deletes it and returns it in one statement:'));
P.push(G.code('csharp',SN('src/Desk.Agent/ApprovalStores.cs','    public bool TryTake(string interruptId, out PendingApproval approval)\n    {','\n\n    private SqliteConnection Open()')));
P.push(G.p('One statement matters because "is it there" followed by "remove it" is a race between two tabs, or two instances, answering at the same moment. With <code>DELETE ... RETURNING</code> the database decides who got it.'));

P.push(G.h2('Test setup'));
P.push(G.p('Everything ran in GitHub Actions on a hosted Linux runner with .NET SDK 11.0.100, <code>Microsoft.AspNetCore.Components.AI</code> 0.1.0-preview.1.26466.103, the AG-UI packages 1.0.1, <code>Microsoft.Extensions.AI</code> 11.0.0 and <code>Microsoft.Data.Sqlite</code> 11.0.0.'));
P.push(G.ul([
'<strong>18 xUnit tests.</strong> The UI agent with a journal behind it, talking to the agent service on an in-memory server. A reload, to the server, is new objects for the same conversation id, and that is what the tests do. "The agent service restarts" disposes the in-memory server and starts another on the same data folder.',
'<strong>10 browser steps.</strong> Chromium, driven by Playwright, against both services as real processes. The script stops and starts them itself, because several steps are "stop it and start it again".']));
P.push(G.p('The model is the scripted stand-in from the first article, so every run decides the same way. All orders and customers are invented.'));
P.push(G.callout('info','A DEPENDENCY TO PIN','The build failed once on NuGet warning NU1902. The Blazor AI preview reaches <code>Microsoft.Extensions.Validation</code> through release-candidate builds of the component packages, and NuGet reports that release candidate under advisory GHSA-m28h-pj36-4364. The sample pins the package to the released 11.0.0 with central transitive pinning. Check your own dependency graph with <code>dotnet nuget why</code>.'));

P.push(G.h2('Test results'));
P.push(G.p('<strong>When the thread is told.</strong> A counting thread, 1.3 seconds into an answer, with twelve words already on the page:'));
P.push(G.code('text',SN('@r/03-tests.txt','0a calls to the thread','1 reload')));
P.push(G.p('<strong>What a reload brings back.</strong> A conversation with an order lookup, a draft reply and a refund waiting for approval restored as the same three turns and eight blocks, in the same order, with the order card as a typed block again. The one difference is the status: AwaitingInput before, Idle after.'));
P.push(G.p('<strong>The default buttons, and two tabs.</strong>'));
P.push(G.code('text',SN('@r/03-tests.txt','4 default Approve()','6 agent service restarted')));
P.push(G.p('Tab B\'s answer is refused by the agent service with HTTP 409, the conversation status becomes Error, and the ledger shows one refund and one attempt. In the browser the component shows its own "Something went wrong" band with a Retry button; the sample adds a line that says what actually happened: the approval was already answered and this click paid nothing.'));
P.push(G.p('<strong>The agent service restarts while an approval waits.</strong> With approvals in memory the answer after the restart is a 409 and nothing is paid, because the server no longer knows it asked. With approvals in SQLite the refund is paid once. Twenty concurrent attempts to take one pending approval from the SQLite store produced exactly one success.'));
P.push(G.p('<strong>An answer that does not finish.</strong>'));
P.push(G.table(['How it ended','Recorder','Rows on disk','After a reload'],[
['Page went away 1.5 s in','Off','0','Nothing. The question is gone too'],
['Page went away 1.5 s in','On','11','The question, the words that arrived, and a notice'],
['User pressed Stop 1.5 s in','Off','0','Nothing'],
['User pressed Stop 1.5 s in','On','8','The question and the words that arrived']]));
P.push(G.p('After a Stop and a new question, the request to the agent service carried two user messages, the stopped one and the new one. With the recorder, a reload shows both turns, which matches what the model was sent.'));
P.push(G.p('<strong>In the browser.</strong> All ten steps passed:'));
P.push(G.table(['Step','What was observed'],[
['Reload','The order card and the answer are back'],
['Shared state','The draft reply and the signature the user typed are back in the panel'],
['Approval, then reload, then Approve','Paid once: O-1003, 37.50'],
['Reload again','No Approve button anywhere; the old approval reads "Answered"'],
['Web app stopped and started','The same address shows the whole conversation and the panel'],
['Agent service stopped and started while an approval waited','Approve after the restart paid O-1002'],
['Two tabs, same approval','Second tab paid; first tab\'s click refused, with the reason on the page; three refunds in total'],
['Reload 1.5 s into a 156-word answer','About 14 words came back, with a notice; the run on the agent service had ended early and did not resume'],
['Default buttons on a restored approval','Label reads "Approved"; requests sent 0; refund attempts 0']]));
P.push(G.p('A reload in the middle of an answer does not continue the answer. Tearing down the old page cancels the run on the agent service, and the new page shows what had arrived. Resuming a run that is still going is a different design, with the run owned by the server and the page attaching to it.'));

P.push(G.h2('Cost'));
P.push(IM(2,'Numbers for a persisted agentic UI conversation: a three-turn journal is 65 rows uncompacted and 20 rows compacted, and after 10, 50 and 100 turns the journal is 11.9, 59.4 and 118.9 KiB, restore takes 1, 3 and 5 milliseconds, and the next request to the stateless agent service carries 6.2, 32.7 and 65.9 KiB','What the journal and the stateless agent service cost as a conversation grows.'));
P.push(G.p('Storage is small. Three turns took 65 rows and 12,266 characters with one row per streamed word, and 20 rows and 3,317 characters compacted, a little over a quarter of the characters. A hundred turns of order lookups came to 700 rows and 118.9 KiB.'));
P.push(G.code('text',SN('@r/03-tests.txt','8 after  10 turns','9 twenty concurrent')));
P.push(G.p('Restore is not the cost: five milliseconds for a hundred turns, from a local file. The number to watch is the last one on each line. The agent service is stateless, so the hundredth question travels with all 397 earlier messages, 65.9 KiB, and with a real model every one of those is input tokens. Persisting the conversation in the web app does nothing about that. It is the argument for the other design, where the server owns the history and the client sends only what is new.'));
P.push(G.p('Write cost was not measured. The recorder writes one row per streamed update, each in its own SQLite transaction, which is fine on a local disk at this scale and is the first thing I would batch against a networked database.'));

P.push(G.h2('Production considerations'));
P.push(G.ul([
'<strong>Own the approval buttons.</strong> With this preview, a restored approval block must not keep the default buttons. The failure is silent and the label is wrong.',
'<strong>Tie conversations to people.</strong> An address that opens a conversation is a secret in a URL. Store the owner with the journal and check it on open.',
'<strong>Treat the journal as the data it contains.</strong> It holds every tool result. If <code>get_order</code> returns a name and an address, so does the file. Encrypt it, set a retention period, and include it when somebody asks for their data or its deletion.',
'<strong>Expire approvals in the UI too.</strong> The server gives an approval ten minutes. A restored block older than that still shows buttons, and the click is refused. Show the age, or hide the buttons after the deadline.',
'<strong>Decide what a stopped turn is.</strong> Here it stays in the conversation, because the agent keeps sending it. If a stopped question should be forgotten, the history sent to the model has to forget it as well.',
'<strong>Use a real database for more than one web instance.</strong> SQLite on local disk ties a conversation to a machine. The store is two tables and four statements; moving it is small.',
'<strong>Version what you store.</strong> The journal is serialised library types from a preview. A package update can change them. Keep the package version with each conversation, and expect to write a migration or to expire old conversations.']));
P.push(G.callout('compliance','RETENTION','Before this change the conversation disappeared when the tab closed. Now it is kept until something deletes it, and nothing in this sample does. That is a change in what the system stores about customers, and it needs a retention rule before it needs anything else.'));

P.push(G.h2('Decision framework'));
P.push(G.table(['If this is true','Prefer','Why'],[
['A lost conversation is an annoyance and approvals are answered within seconds','No persistence','Nothing to store, secure or expire'],
['Users reload, switch devices or come back after lunch, and the agent service must stay stateless','A journal in the web app, as here','The UI owns the history; the agent service needs only durable approvals'],
['Conversations are long, or the model bill is dominated by resent history','History on the server, as with Agent Framework sessions','The client sends only new messages; the second article measured what that takes'],
['An answer must keep running when the page goes away','A run owned by the server, with pages attaching to it','Not built here; a journal restores what arrived and no more'],
['Another person must be able to answer the approval','A server-side approval queue','The approval has to outlive the conversation it came from']]));
P.push(G.p('For this order desk the journal is the right size of answer. It keeps the agent service simple, it makes a reload and a restart harmless, and the code is four small classes. I would not ship it without three of the additions above: an owner on each conversation, a retention rule, and the approval buttons replaced.'));

P.push(G.h2('Key takeaways'));
P.push(G.ul([
'The Blazor AI preview can rebuild a conversation from a thread you supply. It ships no thread, and it reports a turn to the thread only when the turn is over.',
'With the default buttons, Approve on a restored approval changes the label to "Approved" and sends nothing. Send the answer as a message.',
'Shared state is not restored by the agent. Store it beside the journal.',
'A tool result read back from JSON is a different type from the live one, and a typed tool card failed on it until the string was put back.',
'To keep a turn that is interrupted or stopped, record it below the agent, where the updates arrive.',
'A persisted conversation needs persisted approvals on the server. In memory, a restart turns a waiting approval into a 409.',
'A stateless agent service resends everything: 65.9 KiB with the hundredth question.']));

P.push(G.callout('note','HOW THIS WAS CHECKED','Everything in this article comes from one pipeline run on 22 November 2026: <a href="https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/45009252873" target="_blank" rel="noopener">GitHub Actions run 45009252873</a>, commit <code>7546397</code>, with the transcripts, the recorded results and the screenshots on the <code>ci-results-agentic-ui-durable-sessions</code> branch. 18 xUnit tests and 10 Chromium steps passed. The model is a scripted stand-in and all orders are invented. Not done: no real model was called; there is no sign-in and no check of who opens a conversation; the journal is not encrypted and nothing deletes it; write latency was not measured; one web instance and one agent instance were used, with SQLite files on local disk; expiry of an approval was not exercised in the browser; Blazor WebAssembly was not tested with the journal; the preview was studied through its public API and its behaviour, not its source, so the explanation of why a restored Approve sends nothing is an inference; one preview build was tested and later builds may behave differently.'));
P.push(window.GETCODE);
P.push(G.h2('References &amp; Further Reading'));
P.push(G.box([
G.ref('https://www.dataa.dev/2026/11/18/building-an-agentic-ui-with-blazor-and-dotnet-11/','Building an Agentic UI with Blazor and .NET 11','The first article: the components, the hand-built endpoint and the approval check'),
G.ref('https://www.dataa.dev/2026/11/25/agent-framework-hosting-vs-hand-built-ag-ui-endpoint-dotnet-11/','Agent Framework Hosting vs a Hand-Built AG-UI Endpoint in .NET 11','The second article: the design where the server owns the conversation'),
G.ref('https://www.dataa.dev/2026/12/02/agentic-ui-blazor-webassembly-authentication/','Agentic UI in Blazor WebAssembly: Sessions, Tokens and Who May Approve a Refund','Who is calling, and whose approval it is'),
G.ref('https://learn.microsoft.com/en-us/agent-framework/integrations/by-component/ui/ag-ui/security-considerations','Agent Framework: AG-UI security considerations','Thread ownership and approval state on the server'),
G.ref('https://github.com/ag-ui-protocol/ag-ui/tree/main/sdks/dotnet','AG-UI .NET SDK source','Where an approval response becomes a resume entry'),
G.ref('https://github.com/nithinmohantk/blog-samples-working-repo/tree/main/agentic-ui-durable-sessions','Sample code for this article','The journal, the recorder, the restore components, the approval store, the tests and the pipeline script')]));
})();
