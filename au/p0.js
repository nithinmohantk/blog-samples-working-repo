// helpers for this article
window.SRC=window.SRC||{};
window.SN=(file,start,end)=>{const t=window.SRC[file];if(!t)throw new Error('no source '+file);const a=t.indexOf(start);if(a<0)throw new Error('start not found in '+file+': '+start.slice(0,50));if(!end)return t.slice(a);const b=t.indexOf(end,a+start.length);if(b<0)throw new Error('end not found in '+file+': '+end.slice(0,50));return t.slice(a,b)};
window.IM=(k,alt,cap)=>'<!-- wp:image {"sizeSlug":"full","linkDestination":"none"} -->\n<figure class="wp-block-image size-full"><img src="IMG'+k+'_URL" alt="'+alt+'"/><figcaption class="wp-element-caption">'+cap+'</figcaption></figure>\n<!-- /wp:image -->';
window.PARTS=[];
