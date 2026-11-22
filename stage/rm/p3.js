(()=>{const G=window.G,SN=window.SN,P=window.PARTS,IM=window.IM;
P.push(G.h2('Cost'));
P.push(IM(2,'Scoreboard of 18 scenarios for gpt-4.1-mini and gpt-4.1-nano with runs passed out of ten, and per-call latency: gpt-4.1-mini median 221 ms to first update and 392 ms in total, gpt-4.1-nano median 670 ms and 918 ms','Every scenario, both models, with tokens and latency per conversation.'));
P.push(G.table(['','gpt-4.1-mini','gpt-4.1-nano'],[
['Conversations','180','180'],
['Model calls','395','423'],
['Input tokens','123,095','133,967'],
['Output tokens','10,135','10,421'],
['One model call, first update: median / p90','221 / 283 ms','670 / 908 ms'],
['One model call, total: median / p90','392 / 568 ms','918 / 1,198 ms'],
['Order lookup, question to first word: median','579 ms','1,546 ms'],
['Full refund with approval, in total: median','1,220 ms','2,623 ms']]));
P.push(G.p('Input tokens outnumber output tokens twelve to one. An order lookup is 588 tokens in and 34 out, across two model calls, and most of the input is the same every time: the instructions and the three tool definitions. A question with no tool call at all still costs 251 tokens in. That fixed part is the first thing to look at when the bill matters, and it is what prompt caching is for.'));
P.push(G.p('Conversations grow the bill faster than they look. The follow-up scenario, two turns, was 1,345 input tokens, because the second turn resends the first. The agent service here is stateless and the client sends the whole conversation every time, so a long conversation pays for its history on every question.'));
P.push(G.p('On latency, the surprise was the direction. The smaller model was the slower one here, about three times slower to its first update. The two deployments differ in more than the model: one is a regional Standard deployment in the same region as the test, the other a Global Standard deployment. I did not separate those effects, so read it as "measure your own deployment" and not as a statement about the models.'));
P.push(G.p('I have left prices out. The Azure pricing page did not return figures when I opened it for this article, and a number I cannot point to is worse than none. Multiply the token counts above by your own rates.'));

P.push(G.h2('Production considerations'));
P.push(G.ul([
'<strong>Decide what the model may read.</strong> The only defence that held for both models was not sending the customer\'s text. Give each tool an allow-list of fields. Free text that a customer or a third party typed needs a reason to be in a tool result.',
'<strong>If it must read it, label it, and test the label on your model.</strong> A field name and a sentence stopped the attack on one model and did nothing on the other. That result does not transfer between models or versions. Keep the scenario in your pipeline and run it when the model changes.',
'<strong>Do not count on the instructions.</strong> "Tool results are data" changed nothing in twenty runs. Instructions shape ordinary behaviour; they are not a control.',
'<strong>Put every side effect behind code.</strong> The approval wrapper, the server-side approval table and the one-refund-per-order ledger are why forty hostile proposals paid nothing. None of them depends on the model behaving.',
'<strong>Design the approval card for a tired person.</strong> Show what the user asked next to what the agent proposes, so that "asked about an order, proposed a refund" and "asked for 100, proposed 18.25" are visible at a glance.',
'<strong>Check arguments against the request.</strong> A model that changes an amount is not malicious and is still wrong. Where the user stated a number, compare it in code before the card is shown.',
'<strong>Count, and keep counting.</strong> One run of anything here would have told a different story for half the scenarios on the smaller model. Ten runs is a floor.',
'<strong>Keep the key in the agent service.</strong> The browser never sees it. Use a managed identity in place of a key where the platform offers one.']));
P.push(G.callout('compliance','WHAT GOES TO THE MODEL PROVIDER','With a real model, every tool result is sent to the model endpoint, and with a stateless agent service it is sent again with every later question. If <code>get_order</code> returns a name and an address, that is personal data leaving for the provider on each turn. Check the region and the data-handling terms of the deployment, and keep the allow-list of fields short for this reason as well.'));

P.push(G.h2('Decision framework'));
P.push(G.table(['If this is true','Do this','Why'],[
['The agent only reads and summarises','A small model is defensible','Both models passed every lookup; the smaller one\'s failures were at the edges'],
['The agent proposes actions with money or records','Use the larger model and keep the approval in code','The smaller one changed an amount ten times in ten and re-proposed a rejected refund seven times in ten'],
['Tool results contain text typed by outsiders','Leave it out, or label it and test the label','40 of 40 followed the note as an ordinary field'],
['Latency is the constraint','Measure the deployment you will use','Here the smaller model was the slower one'],
['You are choosing between two models','Run the same scenarios on both, ten times','The differences that mattered did not show in the ordinary jobs']]));
P.push(G.p('For this order desk I would run gpt-4.1-mini of these two, with customer text left out of <code>get_order</code>, and I would keep every scenario in this lab as a gate on changing the model, the instructions or the tools. I would not treat any of these counts as true of a model I have not run them on.'));

P.push(G.h2('Key takeaways'));
P.push(G.ul([
'Swapping the scripted model for a real one changed three small classes and nothing in the endpoint, the tools or the UI.',
'gpt-4.1-mini passed every ordinary and edge scenario, 140 of 140. gpt-4.1-nano passed every ordinary one and failed three edge cases in ways a user would notice.',
'Both models followed an instruction planted in an order\'s delivery note, 40 times out of 40. A warning in the instructions made no difference.',
'Labelling the text as untrusted stopped it on one model and not the other. Not sending it stopped it on both.',
'No refund was attempted before an approval in any of 360 conversations, because the approval is code and not a request to the model.',
'An approval step does not remove prompt injection. It moves the decision to a person, who needs a card that makes the mismatch obvious.',
'Run every scenario many times. A model\'s behaviour is a rate.']));

P.push(G.callout('note','HOW THIS WAS CHECKED','The model results come from one run on 22 November 2026 in Azure Cloud Shell, at commit <code>15ab2cc</code>, against two deployments on an Azure OpenAI resource in West Europe: 18 scenarios, ten runs each, 360 conversations, started 11:21 UTC and finished 11:27 UTC. The figures were copied by hand from the terminal; that terminal is the screenshot above, and the copy is in <code>examples/cloud-shell-run-2026-11-22.md</code> in the sample. The per-run file stayed in the Cloud Shell session and is not published. The eight offline tests, which need no key, passed in <a href="https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/45016798650" target="_blank" rel="noopener">GitHub Actions run 45016798650</a> on the same commit. An earlier run the same morning gave the same pass counts for the scenarios it shared, except one (6 of 10 where this run has 5). Not done: the Blazor UI was not driven in a browser with the real model, so nothing here is about how streaming feels on screen; no current flagship model and no reasoning model was tested; only one phrasing of the planted note was tried; the two deployments differ in type as well as model, and the latency difference was not separated; no temperature or other sampling setting was varied; prices were not obtained; ten runs per scenario give rates with wide error bars.'));
P.push(window.GETCODE);
P.push(G.h2('References &amp; Further Reading'));
P.push(G.box([
G.ref('https://www.dataa.dev/2026/11/18/building-an-agentic-ui-with-blazor-and-dotnet-11/','Building an Agentic UI with Blazor and .NET 11','The first article: the UI, the endpoint, the approval check and the scripted model this one replaces'),
G.ref('https://www.dataa.dev/2026/12/02/agentic-ui-blazor-webassembly-authentication/','Agentic UI in Blazor WebAssembly: Sessions, Tokens and Who May Approve a Refund','Who is calling, and whose approval it is'),
G.ref('https://genai.owasp.org/llmrisk/llm01-prompt-injection/','OWASP LLM01:2025 Prompt Injection','Indirect prompt injection, and the mitigations: human approval, least privilege, marking untrusted content'),
G.ref('https://learn.microsoft.com/azure/foundry/openai/api-version-lifecycle','Azure OpenAI in Microsoft Foundry: API version lifecycle','The v1 API: the /openai/v1/ base address and the OpenAI client with a key or a token'),
G.ref('https://learn.microsoft.com/en-us/dotnet/ai/ichatclient','Use the IChatClient interface','Chat client pipelines, function invocation and DelegatingChatClient'),
G.ref('https://github.com/nithinmohantk/blog-samples-working-repo/tree/main/agentic-ui-real-model','Sample code for this article','The model factory, the meter, the instructions, the lab with its 18 scenarios, and the results of the run')]));
})();
