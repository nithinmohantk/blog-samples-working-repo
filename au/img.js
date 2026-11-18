(()=>{const K=window.svgKit;const {head,foot,text}=K;
let a=head('AG-UI on the wire: ','six scenarios','','Event sequences recorded by the wire tests. HTTP POST in, Server-Sent Events out.');
const C={run:['#1B2F4B','#34507A','#DCE6F2'],text:['#0B2A4A','#0073BB','#7CC4FF'],tool:['#2A1F0A','#FF9900','#FFB84D'],state:['#24173F','#A371F7','#D2B8FF'],ok:['#12351F','#3FB950','#B7F5C4'],stop:['#3A1616','#F85149','#FFC9C5'],wait:['#3A2E12','#D29922','#FFE2A8']};
const rows=[['Text',[['RUN_STARTED','run'],['TEXT ×27','text'],['RUN_FINISHED','ok']]],
['Backend tool',[['RUN_STARTED','run'],['TOOL_CALL','tool'],['TOOL_RESULT','tool'],['TEXT','text'],['RUN_FINISHED','ok']]],
['Approval, run 1',[['RUN_STARTED','run'],['TOOL_CALL','tool'],['RUN_FINISHED: interrupt','wait']]],
['Approval, run 2',[['resume in request','wait'],['RUN_STARTED','run'],['TOOL_CALL','tool'],['TOOL_RESULT','tool'],['TEXT','text'],['RUN_FINISHED','ok']]],
['Shared state',[['RUN_STARTED','run'],['TOOL_CALL','tool'],['TOOL_RESULT','tool'],['STATE_SNAPSHOT','state'],['TEXT','text'],['RUN_FINISHED','ok']]],
['Stopped by user',[['RUN_STARTED','run'],['TEXT ×3','text'],['stream ends, no RUN_FINISHED','stop']]]];
rows.forEach((r,j)=>{const y=150+j*82;
 a+='<rect x="48" y="'+y+'" width="210" height="66" rx="8" fill="#16243A" stroke="#2A3E5C" stroke-width="1.5"/>'+text(64,y+40,r[0],{size:17,bold:true,fill:'#FFFFFF'});
 let x=274;r[1].forEach(e=>{const c=C[e[1]];const w=Math.max(120,e[0].length*9.4+28);
  a+='<rect x="'+x+'" y="'+(y+9)+'" width="'+w+'" height="48" rx="8" fill="'+c[0]+'" stroke="'+c[1]+'" stroke-width="1.5"/>'+text(x+w/2,y+39,e[0],{size:14,bold:true,fill:c[2],anchor:'middle'});x+=w+10})});
a+=foot('Scripted stand-in model; AGUI.Server 1.0.1 on .NET 11; GitHub Actions run 44300093955.');
let b=head('Four layers of tests, ','no model key','','The UI depends on IChatClient, so the model can be swapped for a scripted one at every layer.');
const L=[['1','Agent alone','IChatClient pipeline called directly','7 tests','tool logic, approval behaviour, payment rules, one refund per key','ok'],
['2','Agent over AG-UI','AGUIChatClient and raw requests, in-memory server','14 tests','event order, resume, state round trip, cancel, forged approvals, stream size','state'],
['3','Blazor component','bUnit renders the chat; type, click, read markup','5 tests','tool card, Approve and Reject, disabled input','text'],
['4','Browser','Playwright drives Chromium against both services','9 steps','real circuit, state panel, Stop, browser never calls the agent','tool']];
L.forEach((l,i)=>{const y=148+i*112;const c=C[l[5]];
 b+='<rect x="48" y="'+y+'" width="1280" height="96" rx="10" fill="#16243A" stroke="#2A3E5C" stroke-width="1.5"/>';
 b+='<rect x="48" y="'+y+'" width="76" height="96" rx="10" fill="'+c[0]+'" stroke="'+c[1]+'" stroke-width="2"/>'+text(86,y+60,l[0],{size:34,bold:true,fill:c[2],anchor:'middle'});
 b+=text(146,y+40,l[1],{size:21,bold:true,fill:'#FFFFFF'})+text(146,y+70,l[2],{size:15,fill:'#8CA3C2'});
 b+='<rect x="610" y="'+(y+24)+'" width="120" height="48" rx="8" fill="'+c[0]+'" stroke="'+c[1]+'" stroke-width="1.5"/>'+text(670,y+55,l[3],{size:17,bold:true,fill:c[2],anchor:'middle'});
 b+=text(752,y+40,'Catches',{size:13,fill:'#8CA3C2'})+text(752,y+66,l[4],{size:15,fill:'#DCE6F2'})});
b+=foot('26 tests and 9 browser steps passed in GitHub Actions run 44300093955.');
window.SVG_A=a;window.SVG_B=b;})();
