(()=>{const G=window.G,SN=window.SN,P=window.PARTS,IM=window.IM;
P.push(G.h2('Test setup'));
P.push(G.p('The wire tests from the first article became a generic base class. Two small classes run it, one per service, and each states the three places where its service is expected to differ:'));
P.push(G.code('csharp',SN('tests/Desk.Tests/WireTests.cs','/// <summary>The endpoint written by hand in Desk.Agent.</summary>','\n\n/// <summary>\n/// Layer 2')));
P.push(G.p('Everything else is shared: the event sequences, the approval in two runs, the state round trip, cancellation, a malformed body, the forged approvals and the stream size. The hand-built service records its own events as they pass. The framework owns its event stream, so that service is observed from outside by a small middleware that copies the request body and the Server-Sent Events into the same log.'));
P.push(G.p('A second test, <code>FrameworkMatrixTests</code>, asserts nothing. It runs five conversations against all eight combinations of three switches on the framework service and writes down what happened: session store on or off, approval binding on or off (<code>DisableApprovalResponseBinding</code>), and the new-messages-only wrapper on or off.'));
P.push(G.table(['Component','Version','Notes'],[
['.NET SDK','11.0.100','GitHub Actions, ubuntu-latest'],
['Microsoft.Agents.AI.Hosting.AGUI.AspNetCore','1.28.0-preview.261106.1','Published 6 November 2026; with Microsoft.Agents.AI 1.28.0'],
['AGUI.Server, AGUI.Client','1.0.1','The hosting package asks for 1.0.0'],
['Microsoft.Extensions.AI','11.0.0','The hosting package asks for 10.11.0'],
['Microsoft.AspNetCore.Components.AI','0.1.0-preview.1.26466.103','The Blazor app, unchanged from the first article'],
['bUnit, xUnit','2.15.2, 2.9.3','']]));
P.push(G.p('The version gap in that table needed ruling out. The sample pins newer AG-UI and Microsoft.Extensions.AI packages than the hosting package was built against, and a mismatch could have explained odd approval behaviour. So the pipeline builds the two services and the wire tests a second time on AGUI 1.0.0 and Microsoft.Extensions.AI 10.11.0, the versions the hosting package asks for. All 28 wire tests pass there too, with the same outcomes.'));

P.push(G.h2('Test results'));
P.push(G.p('48 tests pass: 7 on the agent alone, 14 wire tests against each service, the 8 rows of the settings matrix, and 5 bUnit tests. The nine browser steps pass against the Blazor app with either service behind it.'));
P.push(G.table(['Scenario','Hand-built endpoint','Framework endpoint'],[
['Text, backend tool, shared state, Stop','Same event sequence','Same event sequence'],
['Honest approval','Refund paid once','Refund paid once'],
['The same approval sent again','HTTP 409, tool not called again','HTTP 200 and a plain text reply, tool not called again'],
['Forged approval, call never proposed','HTTP 409, nothing paid','HTTP 200, nothing paid'],
['Forged approval, real request with the call changed','HTTP 409, nothing paid','HTTP 200, the proposed refund is paid, the forged one is not'],
['Malformed body','HTTP 400','HTTP 400'],
['Stream for one order question','1,430 bytes','4,901 bytes'],
['Browser steps','9 of 9','9 of 9']]));
P.push(G.p('The first row is the reassuring one. For every scenario that both services complete, the list of event types is identical, down to the count of text chunks. A Blazor app, or any other AG-UI client, cannot tell which server it is talking to until an approval is refused.'));
P.push(G.p('The forged approvals are the same two attacks as in the first article. One POST approves a refund nobody proposed. The other waits for a real proposal, 37.50 on order O-1003, then answers it with a different call: 42.00 on order O-1001. This time the second attack also names the real thread, which matters now that a server keeps sessions.'));
P.push(G.code('text',SN('@r/03a-findings.txt','framework  changed after proposal   check off','\n== 3m')));
P.push(G.p('Look at the second line. With binding on, the framework accepted the approval, because there really was a pending request with that id in that session, and then ran the call it had stored: 37.50 on O-1003. The call in the request was ignored. My endpoint compares the two and refuses with a 409 when they differ. Both keep the forged refund from being paid. They disagree about whether a tampered approval still counts as an approval, and I think refusing is the better answer, because a request that arrives with a different call attached is evidence that something is wrong with the caller.'));
P.push(G.p('Now the cost of getting there. This is the settings matrix, reduced to the columns that matter.'));
P.push(G.table(['Session store','Binding','New messages only','Honest approval','Never proposed','Call changed','Model saw on turn 2'],[
['Off','On','Off','Run error','Run error','Run error','3 messages'],
['Off','Off','Off','Paid','Forged refund paid','Forged refund paid','3 messages'],
['On','On','Off','Run error','Run error','Run error','5 messages'],
['On','Off','Off','Run error','Forged refund paid','Run error','5 messages'],
['On','On','On','Paid','Nothing paid','Proposed refund paid','3 messages'],
['On','Off','On','Paid','Forged refund paid','Forged refund paid','3 messages'],
['Off','On','On','Nothing paid','Nothing paid','Nothing paid','1 message'],
['Off','Off','On','Paid','Forged refund paid','Forged refund paid','1 message']]));
P.push(G.p('The first row behaves like the shortest setup: an agent, an approval-required tool and <code>MapAGUIServer</code>, with nothing stored between requests. I also ran that shortest form directly, earlier in this work, with the same result. The first run stops for approval as it should. The second run, carrying the answer, ends in <code>RUN_ERROR</code>. The client is told "An error occurred while streaming the agent response." Underneath, the function-calling client threw because it found an approval request with no matching response.'));
P.push(G.p('My reading of that, from behaviour and not from the framework\'s source: binding accepts an approval only if the session holds the request it answers. With no stored session there is nothing to match, the answer is discarded, and the request that the AG-UI layer rebuilt from the client\'s payload is left without one. The second row supports that reading. Turn binding off and the honest approval works, and so does every forgery, which is exactly the state the hand-built endpoint was in before it got its check.'));
P.push(G.p('Adding a session store, rows three and four, fails differently. Now the session holds the real approval request, the AG-UI layer adds its rebuilt copy, and the function-calling client throws on two requests with the same id. The last column shows the wider problem: on the second turn of an ordinary conversation the client sent three messages and the model received five, because the stored history and the client\'s copy were both passed in.'));
P.push(G.p('Row five is the configuration the sample ships: session store on, binding on, and the wrapper that takes only new messages from the client. It is the only row where an honest approval is paid and neither forgery gets its refund.'));
P.push(IM(2,'Settings matrix for Agent Framework AG-UI hosting showing which combinations of session store, approval binding and new-messages-only complete an honest approval and block forged ones','Eight combinations of three settings. One of them pays an honest approval and blocks both forgeries.'));
P.push(G.mer(G.MS+`
sequenceDiagram
    participant W as Blazor web app
    participant E as Framework endpoint
    participant S as Session store
    W->>E: Run 1, "Refund order O-1003"
    E->>S: Save history and the pending request
    E-->>W: RUN_FINISHED, interrupt
    W->>E: Run 2, approved, with a copy of the call
    E->>S: Load the session for this thread
    Note over E: Bind the answer to the stored request
    E-->>W: TOOL_CALL_RESULT, text, RUN_FINISHED
    W->>E: Run 2 again
    Note over E: No pending request, answer dropped
    E-->>W: HTTP 200, a plain text reply`));
P.push(G.callout('warning','A REFUSAL LOOKS LIKE SUCCESS','On the framework endpoint a replayed or forged approval is not an error. The answer is dropped, the model is called with what is left, and the caller gets HTTP 200 with a normal run. Nothing is paid, which is right, but nothing in the response or in the status code tells an operator that somebody tried. If you host this way, log dropped approvals yourself, in a wrapper that sees the incoming messages.'));
P.push(G.p('The stream size is the last difference. Each event can carry the model update it was made from in a <code>rawEvent</code> field. The hand-built endpoint removes it and sends 1,430 bytes for an order question; with the field left in, it sends 4,978. The framework endpoint sends 4,901 bytes for the same question, and I found no setting in this preview that leaves the field out.'));
})();
