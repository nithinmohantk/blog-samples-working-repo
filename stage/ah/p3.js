(()=>{const G=window.G,SN=window.SN,P=window.PARTS,IM=window.IM;
P.push(G.h2('Cost'));
P.push(G.p('The cost of a harness is code to own and a little time on every call.'));
P.push(G.table(['Part','File','Lines'],[
['Bare loop','bare.py','20'],
['Loop and the eight steps','loop.py','166'],
['Tool contracts','tools.py','58'],
['Sandbox','sandbox.py','50'],
['Store','store.py','37'],
['Budget','budget.py','28'],
['Policy','policy.py','27']]));
P.push(G.p('That is 366 lines against 20, including comments. None of it is clever, and that is the point: every part is a few dozen lines around a tool that already exists. The container sandbox is the expensive one at run time, because each snippet starts a container. I did not measure that overhead here, and it will differ on your hosts. The store writes to disk after every step with full synchronisation, which is the right default for money and too slow for a chat toy.'));
P.push(G.p('The cost of not having one shows in the results. Two megabytes of CSV, at a rough four characters per token, is about half a million tokens on a single request, where the model accepts it at all. One runaway loop at 500 calls is 500 billed requests that produced nothing.'));

P.push(G.h2('Production considerations'));
P.push(G.ul([
'<strong>Pick every number on purpose.</strong> Twelve model calls, twenty tool calls, 4,000 characters per result: these are the lab\'s defaults, not recommendations. Set them per task type and alert when a run hits one.',
'<strong>The approver is the security boundary.</strong> Here it is a function. In production it asks a person or a rule engine, shows them the exact arguments, and records who answered. Approve the call that will run, not a description of it.',
'<strong>A timed-out tool is abandoned, not stopped.</strong> The harness stops waiting after the limit. The thread keeps going. Anything that must be stopped has to run where it can be killed, which means the sandbox or a separate service.',
'<strong>Replace SQLite when there is more than one worker.</strong> The store has no lock that stops two workers resuming the same run. A shared database with a lease per run, or a durable workflow engine, is the next step.',
'<strong>Truncation loses information.</strong> Cutting a result to 4,000 characters is safe and blunt. Better tools take a limit and a filter as arguments, so the model can ask for less. I measured what tool listings cost in context in <a href="https://www.dataa.dev/2026/03/05/the-context-cost-of-mcp-tools/">The Context Cost of MCP Tools</a>.',
'<strong>Traces hold what users typed.</strong> The sample records names, ids and error types, not prompts or tool results. Turning content capture on is a data protection decision.',
'<strong>Tools from elsewhere need the same gate.</strong> If tools arrive over MCP from a server you do not run, their descriptions and results are untrusted input. The eight steps apply unchanged. <a href="https://www.dataa.dev/2026/02/17/red-teaming-an-mcp-server/">Red-Teaming an MCP Server</a> covers what a hostile server can try.',
'<strong>Keep the bad days as tests.</strong> The lab runs in seconds with no model. Every incident you have in production should become one more scenario.']));
P.push(G.callout('compliance','AUDIT','A regulator or an auditor will ask who allowed an action, not which model suggested it. The harness has the three records that answer it: the tool call with its arguments, the approver\'s decision, and the stored result under an idempotency key. Keep them together and keep them longer than the conversation.'));

P.push(G.h2('Decision framework'));
P.push(G.p('Agent frameworks ship some of these parts, and the question is usually which ones you still own. Use this table against whatever you run today.'));
P.push(G.table(['If your agent','You need at least','Why'],[
['Only reads, for one user, in a session','Budget, tool contracts, result limits','Runaway cost and crashes are the only risks'],
['Calls services that fail or stall','Timeouts and retries on top','One slow dependency should not hold a run'],
['Reads documents, tickets, email or web pages','An approval gate on every write','Any of that text can carry instructions'],
['Changes anything: money, records, messages','Approval, a store, idempotency keys','A restart must not repeat the change'],
['Runs code it wrote','A sandbox with no network','A child process leaves the network open'],
['Runs unattended','Tracing and alerts on refusals and budget stops','Nobody is watching the output']]));
P.push(G.p('If I could add only one part to a bare loop, it would be the approval gate on writes. It is 27 lines, and it is the one part that turned a wrong action into no action. Budgets come second, because they are four numbers and they cap every failure you have not thought of yet.'));

P.push(G.h2('Key takeaways'));
P.push(G.ul([
'A bare agent loop handled none of the eleven scenarios well. Three were crashes. Six ended with a normal-looking answer and a wrong or unsafe outcome.',
'A refusal should be a tool result the model can read, not an exception. The model corrected a wrong argument and a wrong tool name once it was told.',
'The harness did not detect the hidden instruction. It stopped the refund because writes need an approver the model does not control.',
'Limits on a child process stopped a 1 GB allocation and kept an API key out of generated code. They did not stop a network connection. A container without a network did.',
'Paying once across a crash took two things: the harness kept the call id, and the ledger honoured the idempotency key.',
'All of it is 366 lines around JSON Schema, SQLite, OpenTelemetry, process limits and a container.']));

P.push(G.callout('note','HOW THIS WAS CHECKED','Everything here comes from one pipeline run: <a href="https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/44508276684" target="_blank" rel="noopener">GitHub Actions run 44508276684</a>, commit <code>3c1bbcc</code>, with the outcomes, traces and checks on the <code>ci-results-agent-harness-production</code> branch. Python 3.13, jsonschema 4.26.0 and OpenTelemetry SDK 1.44.0, with dependencies resolved as of 14 September 2026. 12 unit tests pass, 11 scenarios ran on both loops and three again in a container, and 25 of 25 outcome checks pass. The model is a scripted stand-in, so the scenarios show what a harness does when a model misbehaves, not how often a real model does. No hosted model was called. The API key in the lab is a made-up value. Not measured: latency overhead of any part, container start-up time, token counts, behaviour with two workers on one run. The approver is a function, not a person. Linux only.'));
P.push(window.GETCODE);
P.push(G.h2('References &amp; Further Reading'));
P.push(G.box([
G.ref('https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md','OpenTelemetry GenAI semantic conventions: agent spans','The invoke_agent span and its attributes, marked as in development'),
G.ref('https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md','OpenTelemetry GenAI semantic conventions: inference and tool spans','The chat and execute_tool spans used by the harness'),
G.ref('https://www.dataa.dev/2026/03/24/crash-checkpoint-resume-durable-agent-state/','Crash, Checkpoint, Resume: Durable Agent State in LangGraph, Agent Framework and ADK','What three frameworks repeat after a crash'),
G.ref('https://www.dataa.dev/2026/02/17/red-teaming-an-mcp-server/','Red-Teaming an MCP Server','Poisoned descriptions, rug pulls and confused deputies'),
G.ref('https://www.dataa.dev/2026/03/05/the-context-cost-of-mcp-tools/','The Context Cost of MCP Tools','Tokens per server and per tool'),
G.ref('https://github.com/nithinmohantk/blog-samples-working-repo/tree/main/agent-harness-production','Sample code for this article','Both loops, the eleven scenarios, the tests and the pipeline script')]));
})();
