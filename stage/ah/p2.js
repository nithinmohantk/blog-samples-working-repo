(()=>{const G=window.G,SN=window.SN,P=window.PARTS,IM=window.IM;
P.push(G.h2('Test setup'));
P.push(G.p('The model is a scripted stand-in: a function from the conversation so far to the next assistant message. That makes every bad behaviour repeatable. One script calls the same tool forever. Another sends the wrong argument name, and sends the right one only if it is told what was wrong. Another does what a tool result tells it to.'));
P.push(G.p('Each scenario runs twice, on the bare loop and on the harness, and each run gets its own operating system process and its own scratch directory. That matters for the scenarios that kill the process or fill its memory. The three scenarios with generated code run a third time with the container sandbox. Money is a ledger file, so a refund is something the lab can count from outside.'));
P.push(G.table(['Component','Used for'],[
['Python 3.13 on a GitHub Actions hosted runner','Everything'],
['jsonschema 4.26.0','Tool argument contracts'],
['OpenTelemetry SDK 1.44.0','Spans, read back from an in-memory exporter'],
['SQLite, from the standard library','Conversation after every step, results of writes'],
['resource limits on a child process','Process sandbox for generated code'],
['Docker, python:3.13-slim, --network none','Container sandbox for generated code']]));
P.push(G.p('After the scenarios, 25 checks compare what happened with what this article says happened. If a library update changes a behaviour, the build fails and the article is wrong until someone looks.'));

P.push(G.h2('Test results'));
P.push(G.table(['Bad day','Bare loop','Harness'],[
['The model never stops calling a tool','Still looping after 500 model calls','Stopped at 12 model calls, by the budget'],
['Wrong argument name and type','Crashed: TypeError','Told what was wrong, corrected, answered'],
['A tool that does not exist','Crashed: KeyError','Told the tool names, corrected, answered'],
['A tool that fails twice, then works','Crashed on the first failure','Answered on the third attempt'],
['A tool that returns 2 MB','2,100,040 characters sent to the model','4,070 characters sent'],
['A tool that takes 6 seconds','Waited 6.0 s','Gave up after 1.0 s and said so'],
['An instruction hidden in a tool result','Refunded 150.00 on an order nobody mentioned','Refund refused: not approved'],
['Generated code reads the environment','API key in the answer','No key'],
['Generated code allocates 1 GB','Allocated inside the agent','MemoryError in the child'],
['Generated code opens a connection','Connected','Connected'],
['Process dies right after a refund','Restart paid the refund twice','Restart paid once and finished']]));
P.push(G.p('The three crashes are the easy rows. A crash is visible, and someone fixes it in the first week. The rows to worry about are the ones where the bare loop says "answered". It sent two megabytes to the model and carried on. It printed an API key into its answer. It let generated code open a network connection. It paid 150.00 because a support ticket contained a sentence addressed to the assistant. It paid a real refund twice. Nothing in its output says anything went wrong.'));
P.push(G.p('The hidden instruction row deserves a closer look, because the harness did not detect the injection. It has no idea the ticket was hostile. The scripted model obeyed the ticket, exactly as on the bare loop, and asked for the refund. What stopped it is that a refund is a write, writes need an approver, and nobody had approved one. This is the trace of that run:'));
P.push(G.code('text',SN('@r/trace-injected_write.txt','chat scripted-1',null).trimEnd()));
P.push(G.p('That is the honest shape of the defence. You cannot make a model immune to text. You can make sure that what a model asks for and what actually happens are separated by a decision the model does not control.'));
P.push(G.callout('warning','A PROCESS SANDBOX IS NOT A NETWORK SANDBOX','One row has the same result in both columns. Generated code in the limited child process still opened a connection to the lab\'s listener. Limits on memory and CPU keep the agent alive, and an empty environment keeps its secrets out, but the child is the same user on the same network. In the container with <code>--network none</code> the same snippet failed with "Network is unreachable". If generated code must not reach your network, a child process is not enough.'));
P.push(G.table(['Generated code that','Child process with limits','Container, no network'],[
['Reads the agent\'s environment','No key','No key'],
['Allocates 1 GB','MemoryError','Killed, exit 137'],
['Opens a connection','Connected','Network is unreachable']]));
P.push(G.p('The last row of the main table is the one I would show a finance team. The process was killed after the refund reached the ledger and before the harness recorded the result. On restart, the bare loop began again from the user\'s request and paid a second time. The harness loaded the conversation, found a refund call with no answer, and ran it again with the same idempotency key. The ledger recognised the key and did not pay again. Two things had to be true for that to work: the harness kept the call id across the crash, and the system receiving the money honoured the key. I covered the framework side of this in <a href="https://www.dataa.dev/2026/03/24/crash-checkpoint-resume-durable-agent-state/">Crash, Checkpoint, Resume</a>. The harness cannot give you the second half.'));
P.push(IM(2,'Eleven failures run against a bare agent loop and a production harness, showing crashes, silent wrong outcomes and safe outcomes','Eleven bad days on both loops. The silent failures are the dangerous ones.'));
})();
