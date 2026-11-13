eval(localStorage.art_H); const G=window.G,p=G.p,h2=G.h2; const I=k=>JSON.parse(localStorage['ev_img'+k]);
window.IM=(k,cap)=>G.img('ZZ'+k,I(k).alt,cap).split('ZZ'+k+'_ID').join(String(I(k).id)).split('ZZ'+k+'_URL').join(I(k).url);
window.SN=(k,a,b)=>{const t=localStorage['ev_code_'+k];const i=t.indexOf(a);const j=t.indexOf(b,i);if(i<0||j<0)throw new Error('marker '+k+' '+(i<0?a:b).slice(0,40));return t.slice(i,j+b.length)};
window.SNIPS=[]; window.snip=(lang,k,a,b)=>{const t=window.SN(k,a,b);window.SNIPS.push([k,t]);return G.code(lang,t)}; const snip=window.snip;
const src=(u,t)=>`<a href="${u}" target="_blank" rel="noopener">${t}</a>`;
const CL='https://platform.openai.com/docs/changelog', MA='https://platform.openai.com/docs/models/gpt-6-astra', MS='https://platform.openai.com/docs/models/gpt-6-sol', ML='https://platform.openai.com/docs/models/gpt-6-luna', AZ='https://azure.microsoft.com/en-us/blog/gpt-6-astra-sol-and-luna-for-production-agents-in-microsoft-foundry/', GH='https://github.blog/changelog/2026-09-22-openais-gpt-6-sol-and-gpt-6-luna-now-available', CM='https://community.openai.com/t/announcing-gpt-6-sol-and-gpt-6-luna-in-the-api-codex-and-chatgpt/1399925', NM='https://9to5mac.com/2026/09/22/openai-upgrading-chatgpt-and-codex-with-two-more-gpt-6-models/', DC='https://www.datacamp.com/blog/gpt-6-astra', R153='https://github.com/openai/codex/releases/tag/rust-v0.153.0', R156='https://github.com/openai/codex/releases/tag/rust-v0.156.0';
const parts=[
p(`On Tuesday OpenAI released GPT-6 Sol and GPT-6 Luna, nearly three weeks after GPT-6 Astra. With that the GPT-6 family has a model at each price point, and all three are in Codex, in the API, in Microsoft Foundry and in GitHub Copilot. For a team that uses a coding agent every day, the question has changed. It is no longer which model to use. It is which model to use for which part of the work, because the three differ in price by a factor of a hundred and Codex can now be told to use different ones for planning, for delegated steps and for review.`),
p(`This article sets out what has been published about the three models, with a source beside each figure. It then does two things an architect can check: it works out from the price list what an agent session costs and what changes that cost, and it gives a Codex configuration that assigns one model to each kind of work, validated against the configuration schema in the Codex repository. The February article on <a href="${localStorage.ev_link_codex52}">GPT-5.2-Codex</a> and the June article on <a href="${localStorage.ev_link_caching}">prompt caching economics</a> cover the ground before this release; several rules have changed since.`),
G.callout('info','SCOPE',`Facts about the models come from OpenAI's changelog and model pages, Microsoft's and GitHub's announcements, and the Codex release notes, each linked where it is used. Benchmark figures are OpenAI's own, quoted from press coverage of its launch posts, and are marked as such. The cost figures are arithmetic on list prices for modelled sessions whose token counts are assumptions. No model was called and the Codex CLI was not run, so nothing here measures how well any of the three models writes code.`),
h2('The timeline'),
G.table(['Date','What happened','Source'],[
['9 July 2026','GPT-5.6 family released, with explicit prompt caching controls',src(CL,'OpenAI API changelog')],
['3 September','GPT-6 Astra released. Reasoning effort can be changed mid-conversation without losing the cached prefix. Codex CLI 0.153.0 ships the same day',src(CL,'OpenAI API changelog')+', '+src(R153,'Codex release notes')],
['8 September','Prompt Cache Diagnostics generally available in the Responses API',src(CL,'OpenAI API changelog')],
['22 September','GPT-6 Sol and GPT-6 Luna released in the API, Codex and ChatGPT. Generally available in Microsoft Foundry and rolling out in GitHub Copilot the same day. Codex CLI 0.156.0',src(CM,'OpenAI announcement')+', '+src(AZ,'Microsoft')+', '+src(GH,'GitHub')+', '+src(R156,'Codex release notes')],
['25 September','Fix for an image-encoding bug that degraded image understanding in Sol and Luna',src(CL,'OpenAI API changelog')]]),
h2('What has been published'),
G.table(['Property','Astra','Sol','Luna','Source'],[
['Positioning','Most capable, for the most demanding work','Complex coding and agentic workflows','Most efficient, for focused high-volume tasks',src(MA,'model')+' '+src(MS,'pages')+' '+src(ML,'(OpenAI)')],
['Input, per million tokens','$10.00','$2.00','$0.10',src(AZ,'Microsoft Foundry announcement')],
['Cache read','$1.00','$0.20','$0.01',src(AZ,'Microsoft Foundry announcement')],
['Cache write','$12.50','$2.50','$0.125',src(AZ,'Microsoft Foundry announcement')],
['Output','$50.00','$10.00','$0.50',src(AZ,'Microsoft Foundry announcement')],
['Context window and output','1,050,000 and 128,000 tokens','the same','the same','OpenAI model pages'],
['Long-context rule','Over 272,000 input tokens: input and cache at 2x, output at 1.5x, for the whole request','the same','the same','OpenAI model pages'],
['Reasoning effort','low to max','none to max, default medium','none to max, default medium','OpenAI model pages'],
['Input and output','Text and images in, text out','the same','the same','OpenAI model pages'],
['Knowledge cutoff','30 April 2026','20 April 2026','18 May 2026','OpenAI model pages'],
['Processing options','Batch and Flex at half price, Fast mode at double','the same','the same','OpenAI model pages'],
['Codex','All three are selectable. Sol and Luna for Plus, Pro, Business, Enterprise and Edu; Enterprise administrators enable them','','',src(CM,'OpenAI announcement')+', '+src(NM,'9to5Mac')],
['GitHub Copilot','Released earlier','Pro+, Max, Business, Enterprise','Pro and above; usage-based billing',src(GH,'GitHub changelog')],
['Microsoft Foundry','Standard and Provisioned','Standard, Provisioned and Priority; generally available','Standard; generally available',src(AZ,'Microsoft Foundry announcement')]]),
p(`OpenAI says the Sol and Luna prices are half the promotional prices of their GPT-5.6 counterparts and that the cut is permanent, made possible by cheaper caching and inference. It also says both use fewer tokens for the same work than the GPT-5.6 models of their class.`),
p(`On quality there are only OpenAI's own numbers so far, and they are about more than coding. As reported from its launch posts: Astra scores 72.6% on OSWorld 2.0, 57.7% on Terminal-Bench 4.0 and 74.1% on DeepSWE v1.1 (${src(DC,'DataCamp')}); Sol at its highest effort scores 60.5% on OSWorld 2.0, and OpenAI describes Astra as still its best model for computer use (${src(NM,'9to5Mac')}). None of these says how each model does on your repository. A community run on the announcement thread had all three of a small set of coding tasks passing on both Sol and Luna, with Luna at a tenth of Sol's cost or less; treat it as an anecdote and run your own.`),
window.IM('1','The three models, their list prices, and the Codex setting that assigns each one.'),
h2('Architecture: where the model is chosen'),
p(`A coding agent does not make one kind of request. In a single piece of work it plans, runs many small steps (read a file, run a test, apply an edit), may hand parts to subagents, and at the end reviews what changed. Codex exposes a separate setting for each of those, so the choice of model is a routing decision, made in configuration.`),
G.mer(G.MF+`
flowchart TD
    T["A task for Codex"] --> P["Plan<br/>model, plan_mode_reasoning_effort"]
    P --> M["Main session<br/>model, model_reasoning_effort"]
    M --> S["Subagents for delegated steps<br/>agents.default_subagent_model"]
    S --> M
    M --> R["Review of the change<br/>review_model"]
    R --> H["Human approval<br/>and the usual pull-request gates"]
    style M fill:#FFF3E0,stroke:#FF9900,stroke-width:2px,color:#232F3E
    style S fill:#F0FFF4,stroke:#1D8102,stroke-width:2px,color:#145202
    style R fill:#F3E8FF,stroke:#7C3AED,stroke-width:2px,color:#4C1D95
    style H fill:#EBF8FF,stroke:#0073BB,stroke-width:2px,color:#004C74`),
G.table(['Option','Advantages','Disadvantages and risks','Cost and operations'],[
['One model for everything, the most capable','Nothing to tune. Best chance on hard problems','Pays the top price for reading files and running tests. Usage limits are reached sooner','Highest by a wide margin'],
['One mid-range model for everything','Simple. A sound default','No extra scrutiny at review. Bulk work still costs more than it needs to','A fifth of the first option at list prices'],
['A model per role','Each step is priced for what it needs. An independent, stronger reviewer','More configuration to own. A weak worker can produce plausible, wrong changes that the review must catch','Lowest for the same work, if the work still gets done'],
['The cheapest model for everything','Very low cost, high limits','Most likely to fail on multi-step reasoning. Failures cost engineer time, which is not on the token bill','Lowest on paper']])
];
G.save(1,parts)
