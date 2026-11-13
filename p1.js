eval(localStorage.art_H); const G=window.G,p=G.p,h2=G.h2; const I=k=>JSON.parse(localStorage['ev_img'+k]);
window.IM=(k,cap)=>G.img('ZZ'+k,I(k).alt,cap).split('ZZ'+k+'_ID').join(String(I(k).id)).split('ZZ'+k+'_URL').join(I(k).url);
window.SN=(k,a,b)=>{const t=localStorage['ev_code_'+k];const i=t.indexOf(a);const j=t.indexOf(b,i);if(i<0||j<0)throw new Error('marker '+k+' '+(i<0?a:b).slice(0,40));return t.slice(i,j+b.length)};
window.SNIPS=[]; window.snip=(lang,k,a,b)=>{const t=window.SN(k,a,b);window.SNIPS.push([k,t]);return G.code(lang,t)}; const snip=window.snip;
const src=(u,t)=>`<a href="${u}" target="_blank" rel="noopener">${t}</a>`;
const OAI_MODEL='https://platform.openai.com/docs/models/gpt-5.2-codex', OAI_POST='https://openai.com/index/introducing-gpt-5-2-codex/', MS_POST='https://techcommunity.microsoft.com/t5/microsoft-foundry-blog/announcing-gpt-5-2-codex-in-microsoft-foundry-enterprise-grade/ba-p/4485379', GH_POST='https://github.blog/changelog/2026-01-14-gpt-5-2-codex-is-now-generally-available-in-github-copilot/', GH_IDE='https://github.blog/changelog/2026-01-26-gpt-5-2-codex-is-now-available-in-visual-studio-jetbrains-ides-xcode-and-eclipse/';
const parts=[
p(`GPT-5.2-Codex is OpenAI's coding model for long, agentic work: large refactors, migrations and feature builds carried across many steps. OpenAI released it in its Codex products on 18 December 2025. On 14 January 2026 it reached the OpenAI API, became generally available through Azure OpenAI in Microsoft Foundry, and became generally available in GitHub Copilot. On 26 January Copilot extended it to Visual Studio, JetBrains IDEs, Xcode and Eclipse.`),
p(`Three properties get most of the attention: a 400,000-token context window, image input, and availability inside the Azure boundary. This article sets out what OpenAI, Microsoft and GitHub have published about each, with the source beside every figure, and then works through the question an architect has to answer before approving it for a team: how much of a repository fits in that window, what a working session costs, and what the prompt has to look like for the cost to stay down.`),
G.callout('info','SCOPE',`Facts about the model come from the vendors' own pages, linked where they are used. Where a commonly repeated figure has no vendor source, the article says so. The code is a cost model and a client for the Responses API. It was tested with the official <code>openai</code> package against a local stand-in that applies the documented caching rules. No request was sent to the model, and nothing here measures the quality of its answers.`),
h2('What has been published'),
G.table(['Property','Value','Source'],[
['Context window','400,000 tokens',src(OAI_MODEL,'OpenAI model page')+', '+src(MS_POST,'Microsoft Foundry announcement')],
['Maximum output','128,000 tokens',src(OAI_MODEL,'OpenAI model page')],
['Knowledge cutoff','31 August 2025',src(OAI_MODEL,'OpenAI model page')],
['Input and output','Text and images in, text out',src(OAI_MODEL,'OpenAI model page')],
['Reasoning effort','low, medium, high, xhigh',src(OAI_MODEL,'OpenAI model page')],
['API','Responses API; streaming, function calling and structured outputs supported; fine-tuning not supported',src(OAI_MODEL,'OpenAI model page')],
['Price per million tokens','Input $1.75, cached input $0.175, output $14.00',src(OAI_MODEL,'OpenAI model page')+', '+src(MS_POST,'Microsoft Foundry announcement')],
['Benchmarks','OpenAI states state-of-the-art results on SWE-Bench Pro and Terminal-Bench 2.0',src(OAI_POST,'OpenAI announcement')],
['Long sessions','Native context compaction, better tool calling, improved behaviour on Windows',src(OAI_POST,'OpenAI announcement')],
['Vision','Stronger reading of screenshots, technical diagrams, charts and UI surfaces',src(OAI_POST,'OpenAI announcement')],
['Languages','"50+" languages, among them Python, JavaScript and TypeScript, C#, Java, Go and Rust',src(MS_POST,'Microsoft Foundry announcement')],
['GitHub Copilot','Enterprise, Business, Pro and Pro+; an administrator must enable the model for Business and Enterprise',src(GH_POST,'GitHub changelog, 14 January')+', '+src(GH_IDE,'26 January')]]),
p(`Some figures that circulate with this model have no source in any of those pages. Neither OpenAI nor Microsoft publishes a HumanEval score for it, a first-token latency, or a tiered list of supported languages, and the benchmark claims on OpenAI's page are for SWE-Bench Pro and Terminal-Bench 2.0. There is no documented request flag that turns caching on; prompt caching is automatic and depends on how the prompt is built, which is the subject of the second half of this article. If a number matters to a decision, measure it on your own code.`),
h2('Architecture: three ways to consume the model'),
p(`The same model is reached through three different products, and they differ in who controls the prompt, where the data goes and how it is paid for.`),
G.mer(G.MF+`
flowchart TD
    D["Developer or pipeline"] --> C["Codex CLI, IDE extension or cloud<br/>with a ChatGPT plan"]
    D --> H["GitHub Copilot<br/>model picker"]
    D --> A["Your own code or agent<br/>through the Responses API"]
    A --> O["api.openai.com"]
    A --> F["Azure OpenAI in<br/>Microsoft Foundry"]
    C -. "can be pointed at" .-> F
    style A fill:#FFF3E0,stroke:#FF9900,stroke-width:2px,color:#232F3E
    style F fill:#EBF8FF,stroke:#0073BB,stroke-width:2px,color:#004C74
    style O fill:#F0FFF4,stroke:#1D8102,stroke-width:2px,color:#145202
    style H fill:#F3E8FF,stroke:#7C3AED,stroke-width:2px,color:#4C1D95`),
G.table(['Route','Advantages','Disadvantages and risks','Cost and operations'],[
['Codex products','The harness OpenAI tunes the model for: compaction, sandboxing, tool use','The prompt and context are managed for you. Data handling follows the ChatGPT plan','Per-seat plan with usage limits'],
['GitHub Copilot','Already in the IDE. Policy is set per organisation','Context selection is Copilot\'s. No control over prompt layout or caching','Per-seat plan and premium requests'],
['Responses API on api.openai.com','Full control of prompt, tools and reasoning effort','You build the harness. Data leaves for OpenAI under your API terms','Per token, as in the table above'],
['Responses API through Microsoft Foundry','Same control, inside your Azure tenant: Entra ID, private networking, Azure Policy, one bill','Deployment types and regions differ; check where processing happens for the one you choose','Per token at the same list prices']]),
p(`For interactive work the first two routes are the practical ones. The API routes matter when the model is a component: a review bot in a pipeline, a migration tool, an internal agent. That is where prompt layout and cost become the architect's problem, and the rest of this article is about them.`)
];
G.save(1,parts)
