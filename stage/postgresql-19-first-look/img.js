(()=>{const K=window.svgKit;const {head,foot,text}=K;
const C={ok:['#12351F','#3FB950','#B7F5C4'],bad:['#3A1616','#F85149','#FFC9C5'],warn:['#3A2E12','#D29922','#FFE2A8'],blue:['#0B2A4A','#0073BB','#7CC4FF']};
let a=head('PostgreSQL 19 beside 18, ','measured','','The same statements on PostgreSQL 19.0 and 18.7, one machine, generated data. Run of 23 November 2026.');
const cards=[
['REPACK (CONCURRENTLY)','Writes that finished while a 746 MB table was rewritten',['VACUUM FULL','5'],['REPACK (CONCURRENTLY)','414']],
['NOT IN (subquery)','5,000 rows checked against 300,000, columns NOT NULL',['18.7','74.2 s'],['19.0','29 ms']],
['Foreign key checks','1,000,000 rows inserted, each checked against a parent',['18.7','5.7 s'],['19.0','2.7 s']],
['ON CONFLICT DO SELECT','WAL written by 5,000 get-or-create calls on an existing row',['DO UPDATE','850 kB'],['DO SELECT','22 kB']],
['WAIT FOR LSN','Stale reads on a standby that applies 200 ms late',['Read at once','199 of 200'],['Wait first','0 of 200']],
['Logical decoding','Create a logical slot at wal_level = replica',['18.7','Error'],['19.0','Works, no restart']]];
cards.forEach((c,i)=>{const col=i%3,row=Math.floor(i/3);const x=48+col*432,y=126+row*262,w=416,h=246;
 a+='<rect x="'+x+'" y="'+y+'" width="'+w+'" height="'+h+'" rx="10" fill="#16243A" stroke="#2A3E5C" stroke-width="1.5"/>';
 a+=text(x+20,y+38,c[0],{size:21,bold:true,fill:'#FFFFFF'});
 const words=c[1].split(' ');let l1='',l2='';words.forEach(wd=>{if((l1+' '+wd).length<=44&&!l2)l1=(l1+' '+wd).trim();else l2=(l2+' '+wd).trim()});
 a+=text(x+20,y+66,l1,{size:15,fill:'#C7D3E3'})+(l2?text(x+20,y+87,l2,{size:15,fill:'#C7D3E3'}):'');
 [[c[2],C.bad,0],[c[3],C.ok,1]].forEach(([v,k,j])=>{const bx=x+20+j*192,by=y+106;
  a+='<rect x="'+bx+'" y="'+by+'" width="184" height="120" rx="8" fill="'+k[0]+'" stroke="'+k[1]+'" stroke-width="1.5"/>';
  a+=text(bx+92,by+34,v[0],{size:v[0].length>18?13:15,bold:true,fill:'#DCE6F2',anchor:'middle'});
  a+=text(bx+92,by+84,v[1],{size:v[1].length>12?19:(v[1].length>7?26:34),bold:true,fill:k[2],anchor:'middle'})})});
a+=foot('Timings compare two versions on one hosted runner. They are not a benchmark of absolute performance.');
a=a.replace('y="706"','y="676"');

let b=head('Before the upgrade to ','PostgreSQL 19','','What changes without being asked, and what stops an upgrade. From the release notes; the first column was read from both servers.');
b+='<rect x="48" y="126" width="620" height="50" rx="8" fill="#0B2A4A" stroke="#0073BB" stroke-width="2"/>'+text(358,158,'Defaults that change',{size:20,bold:true,fill:'#7CC4FF',anchor:'middle'});
b+='<rect x="708" y="126" width="620" height="50" rx="8" fill="#3A1616" stroke="#F85149" stroke-width="2"/>'+text(1018,158,'Removed or refused',{size:20,bold:true,fill:'#FFC9C5',anchor:'middle'});
const L=[['jit','on','off','Analytical workloads must turn it on'],['default_toast_compression','pglz','lz4','Faster writes, about a quarter more disk here'],['max_locks_per_transaction','64','128','Double your own value to keep its capacity'],['io_workers','3','removed','Now io_min_workers 2, io_max_workers 8'],['md5 passwords','quiet','warning','On every successful login']];
L.forEach((r,i)=>{const y=190+i*92;b+='<rect x="48" y="'+y+'" width="620" height="80" rx="8" fill="#16243A" stroke="#2A3E5C" stroke-width="1.5"/>'+text(68,y+33,r[0],{size:18,bold:true,fill:'#FFFFFF'})+text(68,y+60,r[3],{size:15,fill:'#C7D3E3'})+text(500,y+46,r[1],{size:18,bold:true,fill:'#A9BBD1',anchor:'end'})+text(522,y+46,'→',{size:18,fill:'#A9BBD1',anchor:'middle'})+text(544,y+46,r[2],{size:20,bold:true,fill:'#FFB84D'})});
const R=[['RADIUS authentication','Removed. Change the pg_hba.conf line first'],['btree_gist indexes on inet, cidr','pg_upgrade refuses the cluster'],['Names with a line break','Roles, databases, tablespaces: pg_upgrade refuses'],['MULE_INTERNAL encoding','Removed. Dump and restore in another encoding'],['standard_conforming_strings = off','Forced on. Old dumps made with it off will not load']];
R.forEach((r,i)=>{const y=190+i*92;b+='<rect x="708" y="'+y+'" width="620" height="80" rx="8" fill="#16243A" stroke="#2A3E5C" stroke-width="1.5"/>'+text(728,y+33,r[0],{size:18,bold:true,fill:'#FFFFFF'})+text(728,y+60,r[1],{size:15,fill:'#C7D3E3'})});
b+=text(48,676,'After pg_upgrade: reindex full text search and pg_trgm indexes when the database uses the ICU or builtin locale provider.',{size:16,fill:'#DCE6F2'});
b+=foot('sql/upgrade-checks.sql in the sample finds each of these on a running PostgreSQL 18 server.');
window.SVG_A=a;window.SVG_B=b;})();
