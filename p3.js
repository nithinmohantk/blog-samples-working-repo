eval(localStorage.art_H); const G=window.G,p=G.p,h2=G.h2; const snip=window.snip;
const RUN='https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/43499033902';
const REPO='https://github.com/nithinmohantk/blog-samples-working-repo/tree/main/gpt6-codex-model-routing';
const src=(u,t)=>`<a href="${u}" target="_blank" rel="noopener">${t}</a>`;
const parts=[
h2('A Codex configuration with a model per role'),
p(`Codex reads <code>~/.codex/config.toml</code>. The file below gives the main session to Sol, plans at a higher reasoning effort, sends subagents to Luna, reviews with Astra, and compacts before the price step.`),
snip('toml','cfg','model = "gpt-6-sol"','max_concurrent_threads_per_session = 4'),
p(`Profiles cover the cases where the default is wrong. In this version of the CLI a profile is a separate file beside the main one, named after the profile, and selected with <code>--profile</code>. Two of the three:`),
snip('toml','cfg_deep','# ~/.codex/deep.config.toml','model_reasoning_effort = "high"'),
snip('toml','cfg_ci','# ~/.codex/ci.config.toml','service_tier = "flex"'),
p(`The first draft of this configuration put the profiles in <code>[profiles.deep]</code> tables inside <code>config.toml</code>. The JSON schema in the Codex repository accepts that, and validation against the schema passed. The CLI does not:`),
snip('text','r_legacy','Error loading config.toml: --profile `deep` cannot be used','and remove the legacy profile selector/table.'),
G.callout('warning','A SCHEMA CHECK IS NOT A RUN',`The schema still describes the older profile tables, so a file can validate and then be refused. Validate configuration by loading it in the version of the tool you deploy. The sample keeps the schema check, records that the schema accepts the legacy form, and relies on the run below for the rest.`),
h2('What Codex sends: a run against a local stand-in'),
p(`To see what those settings do, the sample runs Codex CLI 0.157.1 in a pipeline with a model provider that points at a small server on the same machine. The server speaks the streaming Responses API and plays a script: run this shell command, then this one, then say done. It records every request the CLI makes and reports token usage counted from the request itself. Codex executes the scripted commands in its read-only sandbox in a throwaway repository. No model is involved, and the key the CLI is given is not a real one.`),
snip('bash','runsh','  # The example configuration from the article, plus a provider that points at the stand-in.','wire_api = "responses"\\n\' "$(cat "$work/port")"; } > "$home/config.toml"'),
G.mer(G.MS+`
sequenceDiagram
    participant C as Codex CLI
    participant S as Local stand-in
    participant X as Sandbox
    C->>S: POST /v1/responses (stream)
    S-->>C: Scripted step: run "cat NOTES.md"
    C->>X: Run the command, read-only
    X-->>C: Output
    C->>S: Same request plus the call and its output
    S-->>C: Next scripted step, or "done"`),
p(`Seven scenarios were run: the default configuration over six shell steps, the two profiles, a spawned subagent, a review, the same six steps with the compaction limit lowered to 20,000 tokens, and the legacy profile table. These are the six-step run's requests. The columns are the request number, the agent, the model and effort the CLI asked for, what the stand-in replied with, the tokens taken by tool declarations, the number of items in the request, its total tokens, and whether every earlier item was sent again unchanged.`),
snip('text','r_h','      1   main    gpt-6-sol  medium    shell           5,225            7         11,081','34,304                     True'),
snip('text','r_h','== checks on what the CLI sent','12 of 12 checks passed'),
p(`What the run shows, in the order it matters to the cost model above:`),
G.ul([
`<strong>The loop is append-only.</strong> Each request repeats every earlier item byte for byte and adds two, the tool call and its output, with the same cache key throughout. That is the shape prompt caching rewards, and it is what the session model assumed.`,
`<strong>The fixed overhead is about 11,000 tokens</strong> before the agent has read anything: 5,200 of tool declarations and the rest instructions and environment. That is for an empty configuration. Project instructions, skills and MCP servers add to it, and every subagent pays its own: the spawned one started at 14,836 tokens.`,
`<strong>The routing settings do what they say.</strong> The default sends <code>gpt-6-sol</code> at medium effort; <code>--profile deep</code> sends <code>gpt-6-astra</code> at high; <code>--profile ci</code> sends Sol at low effort on the flex tier; a subagent spawned without a model goes to <code>gpt-6-luna</code> at low effort; <code>codex exec review</code> goes to <code>gpt-6-astra</code>.`,
`<strong>Compaction is a separate, different request.</strong> When a reply reported more tokens than the limit, the CLI sent the whole conversation again with an empty tool list and asked for a summary. Because that request does not begin like the ones before it, the prefix rule says it cannot be read from the cache, which is why the cost model charges it in full. The next request was 11,240 tokens against 20,476 before; its first two items, 9,179 tokens of tool declarations and main instructions, were identical to the first request's, and the rest were new or re-created.`,
`<strong>Tools are not where older clients put them.</strong> With these models the CLI declares tools in an input item, not in the top-level <code>tools</code> field, and offers one freeform tool that takes JavaScript and reaches the shell through it. A proxy or gateway that inspects the <code>tools</code> field to enforce policy will see nothing.`]),
p(`Codex prints its own caution when it compacts:`),
snip('text','r_compact','context compacted','keep threads small and targeted.'),
p(`The limits of this run are the limits of a script. The stand-in's token counts are its own, made with the <code>o200k_base</code> encoding, and stand in for what the service would report. Whether the service's cache treats re-created items with new identifiers as a changed prefix cannot be seen from the client side. And a scripted reply says nothing about what a real model would choose to do.`),
h2('Calling the models from your own code'),
p(`A team building its own agent on the Responses API has the same levers, without Codex to pull them.`),
G.table(['Lever','What to do'],[
['Cache mode','Leave the default for loops. For one-off requests with a large prompt, use explicit mode with no breakpoint to avoid a write that will never be read'],
['Prefix stability','Keep instructions and tool definitions identical between steps. Restrict tools with <code>tool_choice</code> instead of removing them from the list'],
['Reasoning effort','On Astra, change effort mid-conversation by appending a <code>configuration_update</code> item instead of changing the top-level setting, which would break the cached prefix'],
['Context size','Compact before 272,000 input tokens. Alert on any request that crosses it'],
['Measurement','Log <code>cached_tokens</code> and <code>cache_write_tokens</code> from every response. Prompt Cache Diagnostics explains misses'],
['Processing tier','Flex or Batch at half price for work nobody is waiting on; Fast at double only where latency is worth it']]),
h2('Security and governance'),
G.table(['Concern','What applies'],[
['Capability classification','OpenAI classifies Astra as reaching its Critical cybersecurity threshold. At launch it assists with secure code review and patching and refuses to write proof-of-concept exploits ('+src('https://www.datacamp.com/blog/gpt-6-astra','reported by DataCamp from the launch post')+')'],
['Safety pauses','An extra safety check can pause work. In Codex the user is asked to review; in the API the task stops. A pipeline that calls Astra must treat a stopped task as an expected outcome and not retry blindly'],
['Who approves','<code>approvals_reviewer</code> decides whether escalations go to a person or to Codex\'s automatic reviewer. The sample keeps a person. Decide this per repository, and keep it a person for anything regulated'],
['Sandbox','<code>workspace-write</code> for interactive work, <code>read-only</code> with no approvals for unattended runs; the run above executed its commands under <code>read-only</code>. Codex 0.156.0 closed several sandbox isolation gaps, which is a reason to stay current'],
['Subagents','Fan-out multiplies spend and actions, and each subagent starts with its own overhead. Cap concurrent threads, and give workers the narrowest tools'],
['Gateways and proxies','Codex declares tools inside the request input for these models. A control that reads only the top-level <code>tools</code> field no longer sees them'],
['Enablement','In ChatGPT Enterprise an administrator enables the models. In Copilot Business and Enterprise, new models are on by default unless that default has been turned off; check which applies to you'],
['Data residency','In Foundry, EU Data Zone deployments are priced 20% above global and US Data Zone 10%. Choose the deployment type before the model'],
['Generated changes','Untrusted until reviewed and tested. A stronger review model is an extra check, not a replacement for the pull-request gates'],
['Clinical and regulated code','Keep a named human reviewer on any change to decision logic. A model\'s review does not discharge a clinical safety or change-control obligation']]),
h2('Cost'),
G.table(['Item','Figure','Note'],[
['Sol against Astra','One fifth, on every line of the price list','Luna is one hundredth'],
['A modelled 60-step session on Sol','$39.42 uncached, $5.74 cached, $3.93 cached and compacted','Assumed token counts'],
['Fixed overhead per Codex session','About 11,000 tokens per request before any work; 14,800 for a subagent','Observed in the run, empty configuration'],
['The price step','A request at 273,000 input tokens costs 83% more than one at 272,000','$0.2152 against $0.1174 on Sol'],
['One feature, all on Sol','$8.15','Plan, six workers, review'],
['The same, Luna workers','$1.33 with a Sol review, $3.38 with an Astra review','If the workers succeed'],
['Flex or Batch','Half of the above','For unattended work'],
['EU Data Zone in Foundry','20% more','From Microsoft\'s price table']]),
p(`Seat-based plans hide these figures behind usage limits, and they still apply: a session that crosses the step or loses its cache uses the allowance faster.`),
h2('Decision framework'),
G.table(['Situation','Choose','Reason'],[
['Default for a team starting with GPT-6 in Codex','Sol for the main session','OpenAI and GitHub both position it for agentic coding, at a fifth of Astra'],
['Delegated, narrow steps: search, mechanical edits, summaries','Luna for subagents','A hundredth of the price; measure the failure rate before relying on it'],
['Review of high-risk changes','Astra as <code>review_model</code>','An independent, stronger check where a miss is expensive'],
['Review of routine changes','Sol','The Astra review was 76% of the modelled bill'],
['Hard design or debugging session','Astra through a profile','Pay for it when the problem needs it, not by default'],
['Unattended pipeline runs','Sol, low effort, read-only sandbox, Flex','Cheap, bounded, and nothing to approve'],
['Any long session','Compaction below 272,000 tokens','The step doubles the price of everything after it. Each compaction is a full-price request, so not too low either'],
['A decision that depends on quality','Your own tasks, run on each model','The published numbers are the vendor\'s, on other work']]),
h2('Key takeaways'),
G.ul([
`GPT-6 Astra, Sol and Luna share a 1,050,000-token window and differ in price by exactly 5 and 100 times: $10, $2 and $0.10 per million input tokens, $50, $10 and $0.50 for output.`,
`Two pricing rules are new. Cache writes are billed at 1.25 times the input price, and any request over 272,000 input tokens is billed at double for input and one and a half times for output, on the whole request.`,
`In a modelled 60-step session on Sol, caching took the cost from $39.42 to $5.74 and compaction below the step took it to $3.93. Protect the cached prefix and compact early.`,
`Codex has a separate setting for the main model, planning effort, subagents and review. Run against a local stand-in, CLI 0.157.1 sent Sol for the main session, Luna for a spawned subagent and Astra for a review, and refused a profile written the older way that the schema still accepts.`,
`Routing workers to Luna cut the modelled cost of a feature by 59 to 84%, and one Astra review cost more than everything else together. Decide which changes earn that review.`]),
p(`If you have run the same tasks through Sol and Luna as Codex subagents, I would like to know how often Luna's work survived review. Leave a comment.`),
G.callout('note','HOW THIS WAS CHECKED',`The facts in the tables were read from OpenAI's API changelog and model pages, Microsoft's Foundry announcement, GitHub's changelog, the Codex release notes for 0.153.0 and 0.156.0 and Microsoft's Codex documentation; benchmark and safety statements attributed to OpenAI's launch posts were read in press coverage, linked beside them, because the posts themselves could not be retrieved. Everything else ran in GitHub Actions. The cost model passed 21 checks against hand calculation and the configuration schema at tag <code>rust-v0.157.1</code>. Codex CLI 0.157.1, installed from npm, was then run in seven scenarios against a local stand-in for the Responses API, and 12 checks on the recorded requests passed: models, efforts and service tier per setting, the append-only loop, the subagent, the review, compaction at a lowered limit and the refusal of the legacy profile table. The stand-in plays a script and counts tokens itself; the scripted commands were run by Codex in its read-only sandbox in a throwaway repository. Not run: any request to a GPT-6 model, the interactive interface, plan mode, MCP servers, and the profiles' behaviour beyond the first requests. The session shapes in the cost model are assumptions. Nothing here measures code quality, task success, latency or the service's real cache behaviour. <a href="${RUN}" target="_blank" rel="noopener">The run is here</a>.`),
G.callout('tip','GET THE CODE',`The price list, the cost model, the Codex configuration, the stand-in server and the harness that drives the CLI are in <a href="${REPO}" target="_blank" rel="noopener">gpt6-codex-model-routing</a> in the samples repository. <code>./ci.sh out</code> runs everything with Python, Node.js and no account; the harness installs the Codex CLI from npm and gives it a provider that exists only on your machine. Change the session shapes in <code>tests/run.py</code> to your own numbers before drawing conclusions.`).replace('class="callout callout-tip"','class="callout callout-tip sample-code-link"'),
h2('Glossary'),
G.box([
G.term('Codex','OpenAI\'s coding agent: a CLI, an IDE extension, a desktop app and a cloud service that run a model in a loop with tools.'),
G.term('Agent loop','Repeated requests in which the model calls a tool, receives the result and decides the next step, carrying the conversation each time.'),
G.term('Subagent','A separate agent session started by the main one to do a delegated part of the work.'),
G.term('Reasoning effort','A setting that controls how much the model reasons before answering; more effort means more output tokens.'),
G.term('Prompt cache','The provider\'s store of recently processed prompt prefixes. Reading from it is cheap; on these models, writing to it costs more than ordinary input.'),
G.term('Cache breakpoint','The point in a prompt up to which the content is written to, or read from, the cache.'),
G.term('Compaction','Replacing the earlier part of a long conversation with a summary so that it fits and costs less.'),
G.term('Long-context pricing','Higher rates applied to a whole request when its input exceeds a threshold, here 272,000 tokens.'),
G.term('Profile','A named set of Codex settings selected for one run with a command-line option.'),
G.term('Flex and Batch','Slower processing options at half the standard price.'),
G.term('OSWorld, Terminal-Bench, DeepSWE','Benchmarks of computer use, of agent work in a terminal and of software-engineering tasks.')]),
h2('References &amp; Further Reading'),
G.box([
G.ref('https://platform.openai.com/docs/changelog','OpenAI API changelog','Release dates for GPT-5.6, GPT-6 Astra, Sol and Luna, and the caching features'),
G.ref('https://platform.openai.com/docs/models/gpt-6-astra','GPT-6 Astra model page','Limits, prices, long-context rule, reasoning effort'),
G.ref('https://platform.openai.com/docs/models/gpt-6-sol','GPT-6 Sol model page','The same for Sol'),
G.ref('https://platform.openai.com/docs/models/gpt-6-luna','GPT-6 Luna model page','The same for Luna'),
G.ref('https://platform.openai.com/docs/guides/prompt-caching','Prompt caching guide','Cache writes and reads, breakpoints, explicit mode, lifetime'),
G.ref('https://community.openai.com/t/announcing-gpt-6-sol-and-gpt-6-luna-in-the-api-codex-and-chatgpt/1399925','Announcing GPT-6 Sol and GPT-6 Luna in the API, Codex and ChatGPT','OpenAI developer community, 22 September 2026'),
G.ref('https://azure.microsoft.com/en-us/blog/gpt-6-astra-sol-and-luna-for-production-agents-in-microsoft-foundry/','GPT-6 Astra, Sol and Luna for production agents in Microsoft Foundry','Microsoft, 22 September 2026: availability, price table, deployment types'),
G.ref('https://github.blog/changelog/2026-09-22-openais-gpt-6-sol-and-gpt-6-luna-now-available','OpenAI\'s GPT-6 Sol and GPT-6 Luna now available','GitHub changelog: Copilot plans, surfaces and policy'),
G.ref('https://github.com/openai/codex/releases/tag/rust-v0.156.0','Codex CLI 0.156.0 release notes','Reasoning effort, subagents, usage dashboard, sandbox fixes'),
G.ref('https://github.com/openai/codex/releases/tag/rust-v0.153.0','Codex CLI 0.153.0 release notes','Experimental context management'),
G.ref('https://github.com/openai/codex/blob/rust-v0.157.1/codex-rs/core/config.schema.json','Codex configuration schema, 0.157.1','The file the example configuration was validated against'),
G.ref('https://www.npmjs.com/package/@openai/codex','@openai/codex on npm','The CLI package the harness installs, at version 0.157.1'),
G.ref('https://learn.microsoft.com/azure/ai-foundry/openai/how-to/codex','Codex with Azure OpenAI in Microsoft Foundry','Microsoft: provider configuration and validated CLI versions'),
G.ref('https://9to5mac.com/2026/09/22/openai-upgrading-chatgpt-and-codex-with-two-more-gpt-6-models/','OpenAI upgrading ChatGPT and Codex with two more GPT-6 models','9to5Mac: availability and OpenAI\'s reported benchmark figures'),
G.ref('https://www.datacamp.com/blog/gpt-6-astra','GPT-6 Astra: features, benchmarks and pricing','DataCamp: OpenAI\'s reported benchmarks and safeguards for Astra'),
G.ref(REPO,'Sample code for this article','Price list, cost model, Codex configuration, stand-in and harness')])
];
G.save(3,parts)
