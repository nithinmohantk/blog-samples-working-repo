(()=>{const G=window.G,SN=window.SN,P=window.PARTS,IM=window.IM;
P.push(G.p('An agent harness is the code around the model: the loop that calls it, the tools it can use, and everything that decides what its requests are allowed to do. The model gets the attention. The harness decides whether the agent is safe to leave running.'));
P.push(G.p('The first harness most teams write is about twenty lines. Call the model, run the tool it asks for, append the result, repeat. It works in a demo. To see what it does on a bad day I wrote that loop, then wrote eleven bad days: a model that never stops, arguments that do not fit, a tool that hangs, an instruction hidden in a tool result, generated code that reads secrets, and a process that dies right after moving money. The bare loop crashed on three, looped forever on one, and on six it did something worse than crash: it finished normally with a wrong or unsafe result.'));
P.push(G.p('Then I added the parts that stop each failure, one at a time, using ordinary tools: JSON Schema, SQLite, OpenTelemetry, process limits and a container. The result is 366 lines of Python in six files. This article walks through each part, what it stops, and one thing it does not.'));

P.push(G.h2('The problem'));
P.push(G.p('This is the whole bare loop.'));
P.push(G.code('python',SN('harness/bare.py','def run_bare(',null).trimEnd()));
P.push(G.p('Read it as a list of things nobody decided. How many times may the model be called? What if the tool name is wrong, or the arguments are? How long may a tool take, and how much may it return? May the model move money because a document told it to? What happens to a half-finished run when the process restarts?'));
P.push(G.p('None of those questions is about the model. A better model makes some of them rarer and none of them go away, because several are caused by the world around the agent: a slow service, a hostile document, a deployment in the middle of a run. They are harness questions, and each one has a known answer.'));

P.push(G.h2('Architecture'));
P.push(G.p('The production harness keeps the same loop. What changes is that every tool call passes through eight steps, in a fixed order, before its result reaches the model.'));
P.push(G.mer(G.MF+`
flowchart TD
    M["Model asks for a tool call"] --> A["Step 1: Does the tool exist?"]
    A --> B["Step 2: Valid JSON that fits the schema?"]
    B --> C["Step 3: Was this write already done?<br>Then replay the recorded result"]
    C --> D["Step 4: Is it allowed?<br>Writes need an approver"]
    D --> E["Step 5: Is there budget left?"]
    E --> F["Step 6: Run with a time limit,<br>retry what is transient"]
    F --> H["Step 7: Cut the result to size"]
    H --> I["Step 8: Record a write under its key"]
    I --> R["Result text goes back to the model"]
    S["Store: SQLite"] <--> C
    I --> S
    style M fill:#EBF8FF,stroke:#0073BB,stroke-width:2px,color:#004C74
    style R fill:#EBF8FF,stroke:#0073BB,stroke-width:2px,color:#004C74
    style S fill:#F0FFF4,stroke:#1D8102,stroke-width:2px,color:#145202
    style D fill:#FEF2F2,stroke:#D13212,stroke-width:2px,color:#991B1B`));
P.push(G.p('Two design choices matter more than the rest. First, a refusal is a result. When a step says no, the model gets a short error as the tool\'s answer and the run continues, so the model can correct itself. Only the run budget ends a run. Second, the order is deliberate. The replay check comes before the approval check, so a restart does not ask a person to approve the same refund twice. The schema check comes before both, so nobody is asked to approve a request that could never be valid.'));
P.push(IM(1,'Eight parts of a production agent harness with the tool used for each and the failure it stops','The eight steps a tool call passes through, the tool behind each, and the failure it answers.'));

P.push(G.h2('The harness'));
P.push(G.p('<strong>Tool contracts.</strong> A tool is a function plus a JSON Schema for its arguments, a marker for whether it changes anything, a time limit and a retry count. The schema is checked with the <code>jsonschema</code> library before the function is called.'));
P.push(G.code('python',SN('harness/tools.py','@dataclass(frozen=True)\nclass Tool:','\n\n\nclass Registry')));
P.push(G.p('The schema is also where hard limits belong. The refund tool in the lab declares <code>"maximum": 200</code> on its amount. A request for 500 never reaches the approver or the tool, however the model was persuaded to ask.'));
P.push(G.p('<strong>The first two steps.</strong> An unknown tool and arguments that do not fit both come back to the model as text it can act on.'));
P.push(G.code('python',SN('harness/loop.py','        # 1. Does the tool exist?','\n\n        # 3.')));
P.push(G.p('<strong>Replay, approval and budget.</strong> Step three looks up the call\'s idempotency key, the run id plus the call id, in the store. Step four asks the policy. Step five counts.'));
P.push(G.code('python',SN('harness/loop.py','        # 3. Has this exact write','\n\n        # 6.')));
P.push(G.p('The policy is small on purpose. Reads run. Writes run only if an approver function says yes, and the default approver says no.'));
P.push(G.code('python',SN('harness/policy.py','def nobody(',null).trimEnd()));
P.push(G.p('<strong>Running the tool.</strong> The call runs on a worker thread with a bounded wait. A failure the tool marks as transient is retried with backoff and jitter. Anything else becomes a one-line error for the model, and the full exception goes on the trace.'));
P.push(G.code('python',SN('harness/loop.py','def _run_with_retries(','\n\n\ndef _unanswered')));
P.push(G.p('<strong>Result size and memory of writes.</strong> A result over the limit is cut, with a note telling the model how much is missing. A write is recorded under its key.'));
P.push(G.code('python',SN('harness/loop.py','        # 7. Keep the result','\n\n\ndef _run_with_retries')));
P.push(G.p('<strong>The store.</strong> The conversation is saved to SQLite after every model reply and every tool result. When a run starts, the harness loads it and looks for tool calls that were requested and never answered. A restart continues from there.'));
P.push(G.code('python',SN('harness/loop.py','def _unanswered(','\n\n\ndef _compact')));
P.push(G.p('<strong>The sandbox.</strong> Code the model wrote never runs in the agent\'s process. It runs in a child with an empty environment and limits on memory, CPU time and file size, or in a container with no network.'));
P.push(G.code('python',SN('harness/sandbox.py','def _limits(','\n\n\ndef run_python')));
P.push(G.p('<strong>Tracing.</strong> The harness emits three kinds of OpenTelemetry span, named as the GenAI semantic conventions describe: <code>invoke_agent</code> for the run, <code>chat</code> for each model call and <code>execute_tool</code> for each tool call, with <code>error.type</code> set when a step refuses. Those conventions are still marked as in development, so expect the names to move.'));
})();
