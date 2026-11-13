eval(localStorage.art_H); const G=window.G,p=G.p,h2=G.h2; const snip=window.snip;
const parts=[
h2('Three rules in the price list'),
p(`Three rules decide most of what an agent session costs, and two of them are new since the GPT-5 models.`),
G.ul([
`<strong>Cache reads cost a tenth of the input price.</strong> This is as before.`,
`<strong>Cache writes cost 1.25 times the input price.</strong> On these models a token written to the cache is billed at the write rate in place of the input rate. In the default mode the service places a cache breakpoint at the end of the latest message, so the new part of every request is a write. Earlier models had no write charge.`,
`<strong>A request with more than 272,000 input tokens costs double.</strong> Input and cache rates are multiplied by two and output by one and a half, and the multiplier applies to the whole request, not to the part above the line. The context window is 1,050,000 tokens; the price list changes at about a quarter of it.`]),
p(`The cost of one request, with those rules, is a few lines.`),
snip('python','model','    def request(self, model: str, uncached: int, read: int, written: int, output: int, processing: str = "standard") -> float:','        return (input_cost + output_cost) * self.processing[processing] / 1_000_000'),
snip('text','r_run','== 1. One request: 100,000 tokens in, 5,000 out','ok    200,000 tokens on Sol, written once and read once, cost $0.54; sent twice without caching they cost $0.80'),
p(`Two consequences follow. A prompt that is written to the cache and never read again costs 25% more than if caching had not been involved. For a one-off request with a large prompt, the API's explicit cache mode with no breakpoint set avoids the write. And as soon as a prompt is read once, caching is ahead: written once and read once costs 1.35 times the input price against 2. Caching only loses when more than 78% of prompt tokens are writes, which an agent loop is nowhere near.`),
snip('text','r_run','== 2. The step at 272,000 input tokens','ok    one thousand more tokens of context takes the request from $0.1174 to $0.2152'),
p(`The second rule is a step, not a slope. A thousand tokens of extra context nearly doubles the price of that request and of every later request in the session.`),
h2('What an agent session costs'),
p(`An agent loop sends the whole conversation with every step: the instructions and tool definitions, then every tool call and result so far. The sample models that as a fixed base and a context that grows by a constant amount per step. With caching, each step reads what the previous step sent and writes what is new.`),
snip('python','model','    history = 0\n    cached = 0','    return Session(result)'),
p(`The session used here has a 30,000-token base and 60 steps, each adding 5,000 tokens of tool output and 1,000 tokens of the model's own output. Those numbers are assumptions, chosen to resemble a long working session; change them in the sample to match what your own usage reports.`),
snip('text','r_run','== 3. An agent session','ok    for each model: caching beats no caching, and compaction beats running through the step'),
window.IM('2','A modelled 60-step session on Sol, and one feature routed five ways. The token counts are assumptions.'),
p(`Three things stand out.`),
G.ul([
`<strong>Caching is most of the bill.</strong> The same session costs $39.42 on Sol with no caching and $5.74 with it. An agent loop is the best case for a prompt cache, because each request repeats the one before. Anything that breaks the prefix, such as a tool list that changes between steps or a timestamp near the top, moves the session back toward the first figure.`,
`<strong>The step arrives late and stays.</strong> The context passes 272,000 tokens at step 41, and the last twenty steps each cost about double. They are a third of the steps and well over half of the cached session's cost.`,
`<strong>Compaction pays for itself.</strong> Summarising the history once the context passes 240,000 tokens keeps every request under the step. The summary is charged as a request of its own, and what follows it has to be written to the cache again. The session still falls from $5.74 to $3.38.`]),
p(`The proportions are the same for all three models, because Sol's prices are exactly a fifth of Astra's and Luna's a hundredth. The same session is $28.71 on Astra and 29 cents on Luna.`),
G.callout('warning','WHAT THE MODEL LEAVES OUT',`Compaction loses detail, and a session that forgets something it needed will spend steps finding it again; the sample prices the summary and not that. It also assumes steps follow each other within the cache lifetime, which starts at 30 minutes and is renewed by each read. A session left overnight starts cold and writes everything again. And it assumes the same number of tokens whichever model runs a step.`),
h2('Routing one piece of work'),
p(`To compare routings, take one feature as a planning session of 10 steps, six worker sessions of 25 steps and a review of 5 steps over a large diff, and price it with each part on a chosen model.`),
snip('python','tests','def feature(planner: str, worker: str, reviewer: str) -> float:','            + agent_session(prices, reviewer, **review).cost)'),
snip('text','r_run','== 4. One piece of work split across models','more than the planning and the six workers together'),
p(`Sending the workers to Luna and keeping Sol for the plan takes the feature from $8.15 to between $1.33 and $3.38, depending on who reviews. In the mixed route the Astra review is three quarters of the total. That is the line to look at before deciding that every change deserves the most capable reviewer: it may be right for a change to a payment path or a clinical rule, and wasteful for a dependency bump.`),
p(`These are token prices. A worker model that takes twice as many steps, or produces a change that fails review and has to be redone, costs more than the table shows, and the engineer's time costs more than any of it. The routing is a hypothesis to test on your own tasks, with the cheap arithmetic done first.`)
];
G.save(2,parts)
