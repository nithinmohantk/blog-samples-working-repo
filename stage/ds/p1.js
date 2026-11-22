(()=>{const G=window.G,SN=window.SN,P=window.PARTS,IM=window.IM;
const A1='<a href="https://www.dataa.dev/2026/11/18/building-an-agentic-ui-with-blazor-and-dotnet-11/">Building an Agentic UI with Blazor and .NET 11</a>';
const A3='<a href="https://www.dataa.dev/2026/12/02/agentic-ui-blazor-webassembly-authentication/">the WebAssembly article</a>';
P.push(G.p('The production checklist in '+A1+' had one line I left alone: "Decide what a refresh means. The conversation here lives in the circuit. A reload loses it, and a pending approval with it." This article is that decision, made and tested.'));
P.push(G.p('The Blazor AI components preview has a hook for it. A UI agent can be given a conversation thread, an object it reports each turn to, and it can rebuild its blocks from that thread later. I put a SQLite journal behind the hook, gave every conversation an address, and then spent a pipeline run trying to lose the page: reload, restart the web app, restart the agent service, open a second tab, reload halfway through an answer.'));
P.push(G.p('Messages and tool cards came back, after one repair. Four other things did not come back by themselves, and one of them fails in the worst way a UI can: an approval that was waiting is shown again with its buttons, the Approve button turns the label to "Approved", and nothing is sent. No request, no refund, no error.'));

P.push(G.h2('The problem'));
P.push(G.p('A chat page holds more state than it looks. For this order desk there are five things a reload can lose, and they live in three different places:'));
P.push(G.ul([
'<strong>The transcript</strong>: what was asked, what the tools returned, what the agent said. It lives in the UI agent, in the memory of the web app.',
'<strong>A turn in progress</strong>: an answer that is still arriving. It lives in an HTTP response that is being read.',
'<strong>A pending approval, as shown</strong>: the block with the Approve and Reject buttons. UI agent again.',
'<strong>A pending approval, as owed</strong>: the server\'s record that it proposed this exact refund and is waiting. It lives in the agent service, which has its own memory and its own restarts.',
'<strong>Shared state</strong>: the draft reply and the signature the user typed. UI agent, as a separate object.']));
P.push(G.p('The agent service in this series is stateless on purpose. Every request carries the whole conversation, which is what lets it scale without a conversation store. So "persist the conversation" is a job for the side that holds it, the web app, and "persist the pending approval" is a second job on the other side. They fail separately, and a design that fixes one makes the other visible.'));

P.push(G.h2('Architecture'));
P.push(G.mer(G.MF+`
flowchart TD
    B["Browser tab at /c/{id}:<br>the address is the conversation"] --> U["UI agent in the web app:<br>blocks, status, shared state"]
    U -- "each request and<br>each update as it arrives" --> R["TurnRecorder:<br>provisional rows"]
    U -- "the finished turn,<br>in one transaction" --> J["JournalThread:<br>final rows and end mark"]
    R --> S["conversations.db:<br>journal and state rows"]
    J --> S
    U -- "AG-UI, whole conversation<br>on every request" --> A["Agent service:<br>stateless about the conversation"]
    A --> P["approvals.db:<br>one row per pending approval"]
    A --> L["Ledger file:<br>one refund per order"]
    style B fill:#EBF8FF,stroke:#0073BB,stroke-width:2px,color:#004C74
    style U fill:#FFF3E0,stroke:#FF9900,stroke-width:2px,color:#232F3E
    style R fill:#FFF3E0,stroke:#FF9900,stroke-width:2px,color:#232F3E
    style J fill:#FFF3E0,stroke:#FF9900,stroke-width:2px,color:#232F3E
    style A fill:#F3E8FF,stroke:#7C3AED,stroke-width:2px,color:#4C1D95
    style S fill:#F0FFF4,stroke:#1D8102,stroke-width:2px,color:#145202
    style P fill:#F0FFF4,stroke:#1D8102,stroke-width:2px,color:#145202
    style L fill:#F0FFF4,stroke:#1D8102,stroke-width:2px,color:#145202`));
P.push(G.p('The conversation is named in the address. Opening the site makes a random 128-bit id and moves to <code>/c/{id}</code>, so a reload, a bookmark and a second tab all open the same conversation without a cookie or a lookup:'));
P.push(G.code('razor',SN('src/Desk.Web/Components/Pages/Home.razor','@code {')));
P.push(G.p('Everything the web app keeps goes into one SQLite file with two tables: a journal of updates per conversation, and one row of shared state per conversation. The agent service keeps its pending approvals in a second file, and the payment stand-in keeps its refunds in a third, as a real payment system would keep them somewhere of its own.'));
P.push(IM(1,'Table of six things a reload can lose in an agentic UI, what the preview restore gives for each, and what the sample adds: transcript and tool cards, a pending approval block, shared state, a turn in progress, a stopped turn, and the pending approval on the agent service','What the preview restores by itself, and what had to be added.'));
P.push(G.callout('warning','NO SIGN-IN IN THIS SAMPLE','Whoever has the address has the conversation. That is acceptable for a lab and for nothing else. Tie each conversation to a person before real data goes in; '+A3+' shows how the agent service learns who is calling, and the same identity belongs on the journal.'));

P.push(G.h2('The journal'));
P.push(G.p('The hook is an interface in the preview, <code>IConversationThread</code>, set through <code>UIAgentOptions.Thread</code>. It is null by default and the package ships no implementation, so the first step was to find out what the agent does with one. I wrapped a list in a class that logs every call. The contract turned out to be small: the agent calls <code>AppendUserMessage</code>, then <code>AppendUpdate</code> for each streamed update, then <code>CompleteTurn</code>, and it calls <code>GetUpdates</code> once, when asked to restore.'));
P.push(G.p('The logging showed one more thing, which shaped the rest of the design. All of those calls arrive together, after the turn is over. While an answer is streaming, the thread hears nothing. The journal thread therefore collects a turn and stores it in one transaction:'));
P.push(G.code('csharp',SN('src/Desk.Web/Conversations/JournalThread.cs','    public void AppendUserMessage(ChatMessage message)','    public IReadOnlyList<ChatResponseUpdate> GetUpdates()')));
P.push(G.p('Updates are stored as JSON with the serializer options of <code>Microsoft.Extensions.AI</code>, plus the content types AG-UI registers for interrupts. Text, tool calls, tool results and approval requests all survive the round trip with their types. Two things do not. The raw AG-UI event attached to each update is not serialised, which matters for shared state later. And a tool result changes type.'));
P.push(G.code('csharp',SN('src/Desk.Web/Conversations/JournalThread.cs','    /// <summary>\n    /// A tool result is typed as object.','\n\n    private static JsonSerializerOptions CreateJson()')));
P.push(G.p('I found this in the browser, not in a test. The first reload of a conversation with an order card in it threw a <code>JsonException</code> inside the generated tool-block handler, the exception ended the Blazor circuit, and the page was dead. Live, the result of <code>get_order</code> is a .NET string holding JSON. After a round trip through storage it is a <code>JsonElement</code> that holds a string, and the generated code tries to read an order straight out of it. Putting the string back on load fixes it. The restore call is also wrapped now, because stored data is input and input can be wrong.'));
P.push(G.p('Compaction is the last detail. An answer arrives one word per update, so a literal journal has one row per word. When the turn ends, consecutive text updates of the same message are merged into one.'));
})();
