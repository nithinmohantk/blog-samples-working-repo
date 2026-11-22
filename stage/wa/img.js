(()=>{const K=window.svgKit;const {head,foot,text}=K;
const C={ok:['#12351F','#3FB950','#B7F5C4'],bad:['#3A1616','#F85149','#FFC9C5'],warn:['#3A2E12','#D29922','#FFE2A8'],same:['#1B2F4B','#34507A','#DCE6F2'],hi:['#2A1F0A','#FF9900','#FFB84D']};
let a=head('Agentic UI in WebAssembly: ','who checks what','','One refund request passes four places. Each holds something different and refuses in its own way.');
const cols=[['Browser','Blazor WebAssembly app','#0B2A4A','#0073BB','#7CC4FF'],['Web host','Cookie session, forwarder','#2A1F0A','#FF9900','#FFB84D'],['Agent service','AG-UI endpoint','#24173F','#A371F7','#D2B8FF'],['Refund tool','Where money moves','#12351F','#3FB950','#B7F5C4']];
const rows=[['HOLDS',[['HttpOnly session cookie','No token, nothing in storage'],['The session','Key to sign a 2-minute token'],['Pending approvals,','each tied to a person'],['The ledger:','one refund per order']]],
['CHECKS',[['Nothing that counts:','its code is public'],['Cookie, X-Desk-Client header,','JSON content type'],['Token signature, audience, expiry,','role, approval owner and call'],['The approver\'s limit','and the order total']]],
['REFUSES WITH',[['Sends the person','to sign in on a 401'],['302 to sign-in,','401 or 400'],['401, 403 or 409,','before any event is sent'],['A "refused" result;','the agent explains it']]]];
const x0=190,w=278,g=12;
cols.forEach((c,i)=>{const x=x0+i*(w+g);a+='<rect x="'+x+'" y="128" width="'+w+'" height="76" rx="10" fill="'+c[2]+'" stroke="'+c[3]+'" stroke-width="2"/>'+text(x+w/2,160,c[0],{size:20,bold:true,fill:c[4],anchor:'middle'})+text(x+w/2,186,c[1],{size:14,fill:'#C7D3E3',anchor:'middle'});
 if(i<3)a+='<line x1="'+(x+w-2)+'" y1="166" x2="'+(x+w+g+2)+'" y2="166" stroke="#C7D3E3" stroke-width="2" marker-end="url(#ah)"/>'});
rows.forEach((r,j)=>{const y=222+j*150;a+='<rect x="48" y="'+y+'" width="130" height="136" rx="10" fill="#16243A" stroke="#2A3E5C" stroke-width="1.5"/>'+text(113,y+74,r[0],{size:15,bold:true,fill:'#FFFFFF',anchor:'middle'});
 r[1].forEach((cell,i)=>{const x=x0+i*(w+g);a+='<rect x="'+x+'" y="'+y+'" width="'+w+'" height="136" rx="10" fill="#1B2F4B" stroke="#34507A" stroke-width="1.5"/>'+text(x+w/2,y+62,cell[0],{size:16,bold:true,fill:'#FFFFFF',anchor:'middle'})+text(x+w/2,y+88,cell[1],{size:15,fill:'#C7D3E3',anchor:'middle'})})});
a+=foot('Sign-in and the token issuer are lab stand-ins. Scripted model. GitHub Actions run 45003297156.');
let b=head('Ten requests, ','and what happened to each','','23 tests on in-memory servers and 11 browser steps against the published WebAssembly app.');
const R=[['Open the app with no session','302 to the sign-in page','ok'],
['POST /agent with no session','401','ok'],
['Session, but no X-Desk-Client header','400','ok'],
['Agent service: no token, expired, wrong audience, wrong key, unsigned, edited','401, six of six','ok'],
['Valid token, role with no desk access','403','ok'],
['Alex answers an approval that was asked of Sam','403, still pending for Sam','ok'],
['Sam forges an approval, server check on','409, nothing paid','ok'],
['Sam forges 42.00, server check off','200, tool refused: above limit','warn'],
['Sam forges 18.25, server check off','200, refund paid','bad'],
['Token expires 3 s into a 23.5 s answer','Stream ran to the end','warn']];
R.forEach((r,j)=>{const y=126+j*56;const k=C[r[2]];
 b+='<rect x="48" y="'+y+'" width="800" height="48" rx="8" fill="#16243A" stroke="#2A3E5C" stroke-width="1.5"/>'+text(66,y+31,r[0],{size:16,bold:true,fill:'#FFFFFF'});
 b+='<rect x="860" y="'+y+'" width="468" height="48" rx="8" fill="'+k[0]+'" stroke="'+k[1]+'" stroke-width="1.5"/>'+text(1094,y+31,r[1],{size:16,bold:true,fill:k[2],anchor:'middle'})});
b+=foot('Scripted model, invented orders and people. GitHub Actions run 45003297156, commit d895d20.');
window.SVG_A=a;window.SVG_B=b;})();
