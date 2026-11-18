(()=>{const K=window.svgKit;const {head,foot,text}=K;
const C={ok:['#12351F','#3FB950','#B7F5C4'],bad:['#3A1616','#F85149','#FFC9C5'],warn:['#3A2E12','#D29922','#FFE2A8'],same:['#1B2F4B','#34507A','#DCE6F2'],hi:['#2A1F0A','#FF9900','#FFB84D']};
let a=head('One Blazor UI, ','two AG-UI servers','','The same wire tests and browser steps against a hand-built endpoint and Agent Framework hosting.');
a+='<rect x="48" y="128" width="330" height="52" rx="8" fill="#16243A" stroke="#2A3E5C" stroke-width="1.5"/>'+text(64,161,'Scenario',{size:17,bold:true,fill:'#FFFFFF'});
a+='<rect x="390" y="128" width="462" height="52" rx="8" fill="#0B2A4A" stroke="#0073BB" stroke-width="2"/>'+text(621,161,'Hand-built on AGUI.Server',{size:18,bold:true,fill:'#7CC4FF',anchor:'middle'});
a+='<rect x="864" y="128" width="464" height="52" rx="8" fill="#24173F" stroke="#A371F7" stroke-width="2"/>'+text(1096,161,'Agent Framework MapAGUIServer',{size:18,bold:true,fill:'#D2B8FF',anchor:'middle'});
const rows=[['Text, tools, state, Stop',['Same events','same'],['Same events','same']],
['Honest approval',['Paid once','ok'],['Paid once, with session store and wrapper','ok']],
['Same approval again',['HTTP 409','ok'],['HTTP 200, plain reply, not paid again','warn']],
['Forged: never proposed',['HTTP 409, nothing paid','ok'],['HTTP 200, nothing paid','warn']],
['Forged: call changed',['HTTP 409, nothing paid','ok'],['HTTP 200, proposed refund paid','warn']],
['Stream, one order question',['1,430 bytes','ok'],['4,901 bytes, no switch found','bad']],
['Browser steps',['9 of 9','ok'],['9 of 9','ok']]];
rows.forEach((r,j)=>{const y=192+j*70;
 a+='<rect x="48" y="'+y+'" width="330" height="58" rx="8" fill="#16243A" stroke="#2A3E5C" stroke-width="1.5"/>'+text(64,y+36,r[0],{size:17,bold:true,fill:'#FFFFFF'});
 [[390,462,r[1]],[864,464,r[2]]].forEach(c=>{const k=C[c[2][1]];a+='<rect x="'+c[0]+'" y="'+y+'" width="'+c[1]+'" height="58" rx="8" fill="'+k[0]+'" stroke="'+k[1]+'" stroke-width="1.5"/>'+text(c[0]+c[1]/2,y+36,c[2][0],{size:16,bold:true,fill:k[2],anchor:'middle'})})});
a+=foot('Scripted stand-in model; Agent Framework hosting 1.28.0-preview.261106.1; GitHub Actions run 44363641369.');
let b=head('Agent Framework AG-UI hosting: ','settings matrix','','Three switches, eight combinations, five conversations each. One row pays an honest approval and blocks both forgeries.');
const cols=[['Session store',150],['Binding',120],['New only',120],['Honest approval',200],['Never proposed',210],['Call changed',230],['Model saw, turn 2',190]];
let x=48;const xs=[];cols.forEach(c=>{xs.push(x);b+='<rect x="'+x+'" y="128" width="'+c[1]+'" height="50" rx="8" fill="#16243A" stroke="#2A3E5C" stroke-width="1.5"/>'+text(x+c[1]/2,159,c[0],{size:15,bold:true,fill:'#FFFFFF',anchor:'middle'});x+=c[1]+10});
const M=[['Off','On','Off',['Run error','bad'],['Run error','bad'],['Run error','bad'],['3 of 3','same']],
['Off','Off','Off',['Paid','ok'],['Forged refund paid','bad'],['Forged refund paid','bad'],['3 of 3','same']],
['On','On','Off',['Run error','bad'],['Run error','bad'],['Run error','bad'],['5, duplicated','bad']],
['On','Off','Off',['Run error','bad'],['Forged refund paid','bad'],['Run error','bad'],['5, duplicated','bad']],
['On','On','On',['Paid','ok'],['Nothing paid','ok'],['Proposed refund paid','ok'],['3 of 3','same']],
['On','Off','On',['Paid','ok'],['Forged refund paid','bad'],['Forged refund paid','bad'],['3 of 3','same']],
['Off','On','On',['Nothing paid','bad'],['Nothing paid','ok'],['Nothing paid','ok'],['1, history lost','bad']],
['Off','Off','On',['Paid','ok'],['Forged refund paid','bad'],['Forged refund paid','bad'],['1, history lost','bad']]];
M.forEach((r,j)=>{const y=188+j*61;const hi=j===4;
 r.forEach((cell,i)=>{const w=cols[i][1];let k,t;if(typeof cell==='string'){k=cell==='On'?C.hi:C.same;t=cell}else{k=C[cell[1]];t=cell[0]}
  b+='<rect x="'+xs[i]+'" y="'+y+'" width="'+w+'" height="51" rx="8" fill="'+k[0]+'" stroke="'+k[1]+'" stroke-width="1.5"/>'+text(xs[i]+w/2,y+32,t,{size:15,bold:true,fill:k[2],anchor:'middle'})});
 if(hi)b+='<rect x="42" y="'+(y-5)+'" width="1292" height="61" rx="11" fill="none" stroke="#FF9900" stroke-width="3"/>'});
b+=foot('Honest approval on row 7 is dropped, not refused. Hosting 1.28.0-preview.261106.1; run 44363641369.');
window.SVG_A=a;window.SVG_B=b;})();
