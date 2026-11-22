(()=>{const K=window.svgKit;const {head,foot,text}=K;
const C={ok:['#12351F','#3FB950','#B7F5C4'],bad:['#3A1616','#F85149','#FFC9C5'],warn:['#3A2E12','#D29922','#FFE2A8'],same:['#1B2F4B','#34507A','#DCE6F2'],hi:['#2A1F0A','#FF9900','#FFB84D']};
let a=head('After a reload: ','what comes back by itself','','Blazor AI components preview with a conversation thread behind the UI agent. Six things a page can lose.');
const hx=[48,400,872],hw=[340,460,456];
[['What the page had','#16243A','#2A3E5C','#FFFFFF'],['From the preview\'s restore','#0B2A4A','#0073BB','#7CC4FF'],['What the sample adds','#2A1F0A','#FF9900','#FFB84D']].forEach((h,i)=>{a+='<rect x="'+hx[i]+'" y="126" width="'+hw[i]+'" height="48" rx="8" fill="'+h[1]+'" stroke="'+h[2]+'" stroke-width="2"/>'+text(hx[i]+hw[i]/2,157,h[0],{size:18,bold:true,fill:h[3],anchor:'middle'})});
const rows=[['Messages and tool cards',['Restored, once tool results are repaired','warn'],'Put the JSON string back on load'],
['Approval block, still waiting',['Shown, but Approve sends nothing','bad'],'Own buttons: send the answer as a message'],
['Shared state (the draft reply)',['Not restored','bad'],'One state row beside the journal'],
['An answer still arriving',['Not on disk: thread told at turn end','bad'],'Recorder writes each update as it arrives'],
['A turn the user stopped',['Never reported to the thread','bad'],'Recorder rows stay in the conversation'],
['The server\'s pending approval',['Lost when the agent service restarts','bad'],'Approvals in SQLite, taken in one statement']];
rows.forEach((r,j)=>{const y=186+j*84;const k=C[r[1][1]];
 a+='<rect x="'+hx[0]+'" y="'+y+'" width="'+hw[0]+'" height="72" rx="8" fill="#16243A" stroke="#2A3E5C" stroke-width="1.5"/>'+text(hx[0]+18,y+43,r[0],{size:17,bold:true,fill:'#FFFFFF'});
 a+='<rect x="'+hx[1]+'" y="'+y+'" width="'+hw[1]+'" height="72" rx="8" fill="'+k[0]+'" stroke="'+k[1]+'" stroke-width="1.5"/>'+text(hx[1]+hw[1]/2,y+43,r[1][0],{size:16,bold:true,fill:k[2],anchor:'middle'});
 a+='<rect x="'+hx[2]+'" y="'+y+'" width="'+hw[2]+'" height="72" rx="8" fill="#12351F" stroke="#3FB950" stroke-width="1.5"/>'+text(hx[2]+hw[2]/2,y+43,r[2],{size:16,bold:true,fill:'#B7F5C4',anchor:'middle'})});
a+=foot('Components.AI 0.1.0-preview.1.26466.103, scripted model. GitHub Actions run 45009252873.');
let b=head('A persisted conversation: ','what it costs','','One SQLite journal in the web app, a stateless agent service, order-lookup turns with a scripted model.');
b+=text(48,150,'JOURNAL FOR THREE TURNS',{size:15,bold:true,fill:'#FFB84D'});
[['One row per streamed word','65 rows','12,266 characters','same'],['Compacted when the turn ends','20 rows','3,317 characters','ok']].forEach((c,i)=>{const x=48+i*648,k=C[c[3]];
 b+='<rect x="'+x+'" y="166" width="632" height="96" rx="10" fill="'+k[0]+'" stroke="'+k[1]+'" stroke-width="1.5"/>'+text(x+24,y0(205),c[0],{size:18,bold:true,fill:'#FFFFFF'})+text(x+24,238,c[1]+', '+c[2],{size:22,bold:true,fill:k[2]})});
function y0(v){return v}
b+=text(48,306,'AS THE CONVERSATION GROWS',{size:15,bold:true,fill:'#FFB84D'});
const cx=[48,330,596,862,1128],cw=[270,254,254,254,200];
['Turns','Journal on disk','Open and restore','Messages resent','Request size'].forEach((h,i)=>{b+='<rect x="'+cx[i]+'" y="322" width="'+cw[i]+'" height="46" rx="8" fill="#16243A" stroke="#2A3E5C" stroke-width="1.5"/>'+text(cx[i]+cw[i]/2,352,h,{size:16,bold:true,fill:'#FFFFFF',anchor:'middle'})});
[['10','70 rows, 11.9 KiB','1 ms','37','6.2 KiB'],['50','350 rows, 59.4 KiB','3 ms','197','32.7 KiB'],['100','700 rows, 118.9 KiB','5 ms','397','65.9 KiB']].forEach((r,j)=>{const y=380+j*74;
 r.forEach((cell,i)=>{const k=i>=3?C.warn:(i===2?C.ok:C.same);b+='<rect x="'+cx[i]+'" y="'+y+'" width="'+cw[i]+'" height="62" rx="8" fill="'+k[0]+'" stroke="'+k[1]+'" stroke-width="1.5"/>'+text(cx[i]+cw[i]/2,y+39,cell,{size:19,bold:true,fill:k[2],anchor:'middle'})})});
b+=text(48,634,'Restore is cheap. The stateless agent service is what grows: every question carries the whole conversation,',{size:17,fill:'#DCE6F2'});
b+=text(48,660,'and with a real model every resent message is input tokens.',{size:17,fill:'#DCE6F2'});
b+=foot('In-memory test server, local disk. GitHub Actions run 45009252873, commit 7546397.');
window.SVG_A=a;window.SVG_B=b;})();
