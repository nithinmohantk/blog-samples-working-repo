(()=>{const G=window.G,SN=window.SN,P=window.PARTS,IM=window.IM;
P.push(G.h2('Turns in progress'));
P.push(G.p('Because the thread hears about a turn only at its end, a page that goes away mid-answer leaves nothing: not the partial answer, and not the question either. The same is true of a turn the user stops with the Stop button, with a twist: the agent never reports a stopped turn to the thread, yet it keeps the stopped question in the history it sends with the next request. A journal built only from the thread would restore a conversation the model never saw.'));
P.push(G.p('So the turn is also recorded one level down, where the updates come off the wire. A delegating chat client sits between the UI agent and the AG-UI client:'));
P.push(G.code('csharp',SN('src/Desk.Web/Conversations/TurnRecorder.cs','public sealed class TurnRecorder')));
P.push(G.p('Its rows are provisional. If the turn finishes, <code>CompleteTurn</code> replaces them with the compact final rows and an end mark, in the same transaction. If the turn never finishes, they are what the next page finds, and the missing end mark is how it knows the last answer was cut short. If the request is refused before anything comes back, there was no turn, and the rows are removed.'));
P.push(G.code('csharp',SN('src/Desk.Web/Conversations/JournalThread.cs','    public void LiveStart(ChatMessage message)','    /// <summary>The request was refused before anything came back')));
P.push(G.p('Rows are numbered by the database, not by the page. My first version numbered them in the thread object, and the two-tab test failed with a primary key violation the moment the second tab wrote. Two pages on one conversation are two writers, whether or not anybody planned for that.'));

P.push(G.h2('Restore on load'));
P.push(G.p('Opening a conversation builds the thread from the journal, loads the stored state, and creates the agent around both:'));
P.push(G.code('csharp',SN('src/Desk.Web/Conversations/DeskSession.cs','    public static DeskSession Open(','\n\n    public void Dispose()')));
P.push(G.p('The shared state needs its own row because the agent\'s restore does not bring it back. The draft reply reaches the UI as a <code>STATE_SNAPSHOT</code> event, and the state mapper reads it from the update\'s raw representation, which storage drops. A subscription saves the state whenever it changes, including when the user types in the panel, and the saved value is the agent\'s starting state next time.'));
P.push(G.p('The restore itself is one call, made by a small component placed inside the agent boundary so that it can reach the context:'));
P.push(G.code('razor',SN('src/Desk.Web/Components/RestoreOnLoad.razor','@code {')));

P.push(G.h2('Restored approvals'));
P.push(G.p('After a restore the approval block is back, with its tool name, its arguments and a status of Pending. The conversation status is Idle, where the live page was AwaitingInput. That difference is the whole problem. In a live run, the agent is suspended on the block, waiting for its answer, and <code>Approve()</code> releases it. After a restore nothing is suspended. <code>Approve()</code> sets the block to Approved and there is nobody to tell.'));
P.push(IM(3,'Screenshot of the order desk after a reload with the default approval buttons: the refund_order approval block for order O-1003 shows Approved in green, with no further messages below it, while the payment ledger recorded no attempt','The default buttons on a restored approval. The label says Approved. No request was sent and nothing was paid.'));
P.push(G.p('The answer still has a route: sent as a message. The restored block exposes the original approval request, and a response created from it can be sent through the context like any user message. The AG-UI client turns it into the same <code>resume</code> entry a live approval produces. So approval blocks that came from storage get their own renderer, with buttons that do that:'));
P.push(G.code('razor',SN('src/Desk.Web/Components/RestoredApproval.razor','    private async Task AnswerAsync(bool approved)','\n\n    public void Dispose()')));
P.push(G.code('razor',SN('src/Desk.Web/Components/DeskChat.razor','                        @if (_ownApprovalButtons)','                    </ChildContent>')));
P.push(G.p('One more piece of bookkeeping follows from it. After the answer is sent and the page is reloaded again, the agent restores the old approval block as Pending once more, next to the tool call and result that followed it. The journal knows better, because it holds the response, so the renderer asks the thread whether an approval was answered and shows "Answered" in place of the buttons.'));
P.push(G.mer(G.MS+`
sequenceDiagram
    participant T as Browser tab
    participant W as Web app
    participant J as Journal
    participant A as Agent service
    T->>W: Refund order O-1003
    W->>A: Run
    A-->>W: Interrupt, approval stored in approvals.db
    W->>J: Turn with the approval request
    Note over T,W: Page reloads, or the web app restarts
    T->>W: Open /c/{id}
    W->>J: Load journal and state
    W-->>T: Conversation, approval with working buttons
    T->>W: Approve
    W->>A: Approval response as a message (resume)
    A-->>W: Refund recorded, once
    W->>J: Turn with the response and the result`));
})();
