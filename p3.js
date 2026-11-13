eval(localStorage.art_H); const G=window.G,p=G.p,h2=G.h2; const snip=window.snip;
const parts=[
h2('The json type: validation, and what it normalises'),
p(`Until this release JSON in SQL Server was text in an <code>nvarchar</code> column with a check constraint if someone remembered to add one. The <code>json</code> type validates on write and stores a parsed binary form.`),
snip('text','r_t','[6.1] an object',"SELECT JSON_CONTAINS(@j, 'IE', '$.c');\n      ok -> 1"),
p(`The points to carry into a design review:`),
G.ul([
`<strong>It is not a byte-for-byte store.</strong> White space is removed and a repeated key silently keeps its first value. Key order, trailing zeros and a 29-digit number survived. If you must return exactly the bytes you received, for a signature or a legal record, keep the original text as well.`,
`<strong>Only objects and arrays are accepted.</strong> A bare <code>true</code> or a number is an error.`,
`<strong>A json value cannot be compared, sorted or grouped.</strong> An equality test and an <code>ORDER BY</code> both fail with error 13636, and its message rules out comparing and sorting in general. Extract a property, or cast to text.`,
`<strong>The typed extraction and containment functions worked without the preview switch.</strong> <code>JSON_VALUE</code> with <code>RETURNING</code> gives a decimal directly.`]),
h2('Storage: three column types for the same documents'),
snip('sql','jsql','CREATE TABLE dbo.OrdersN','CREATE TABLE dbo.OrdersJ (id int NOT NULL CONSTRAINT PK_OrdersJ PRIMARY KEY CLUSTERED, doc json NOT NULL);'),
snip('text','r_t','  nvarchar(max)          31.3 MB','the documents average 301 bytes as UTF-8 text'),
p(`The native type is a fifth smaller than <code>nvarchar(max)</code>, which stores two bytes per character. It is larger than the same text in a UTF-8 <code>varchar(max)</code> column, because the binary form carries structure so that a property can be found without parsing. For small documents like these, <code>json</code> is not a storage saving over UTF-8 text. What it buys is validation and cheaper access.`),
h2('Updating one property'),
p(`The type has a method, <code>modify</code>, that changes one value in place. The test updates the <code>status</code> of all 50,000 documents inside a transaction and reads how much transaction log that one statement wrote.`),
snip('sql','jsql','BEGIN TRANSACTION;\nUPDATE dbo.OrdersJ SET doc.modify','COMMIT;'),
snip('text','r_t','== 8. Changing one property','20 characters         0.2 s      6.6 MB of log'),
p(`Replacing a value with one of the same length wrote 5 MB of log; replacing it with a longer one wrote 31 MB, because each document had to be rewritten. On the <code>json</code> column, <code>modify()</code> and the older <code>JSON_MODIFY</code> function cost the same in this build. Both were two to four times faster than <code>JSON_MODIFY</code> on <code>nvarchar(max)</code>, which parses the text, changes it and writes it back. For a property that changes often, a fixed-width representation, such as a status code of constant length, keeps updates in place.`),
h2('Indexing a property inside the document'),
p(`The query is the usual one: all orders for one country, here 245 of 50,000. There are two ways to index it. The long-standing one is a computed column over the property with an ordinary index:`),
snip('sql','jsql','ALTER TABLE dbo.OrdersC ADD country','CREATE INDEX IX_OrdersC_country ON dbo.OrdersC (country);'),
p(`The new one is a JSON index over one or more paths, which was created without the preview switch:`),
snip('sql','jsql','CREATE JSON INDEX IX_OrdersJ_doc','FOR (\'$.customer.country\', \'$.status\');'),
snip('text','r_t','== 9. Finding the orders for one country','  json, doc.modify(), same length, JSON index            5.2 s     69.6 MB of log'),
window.IM('2','Query times with and without each index. The JSON index answers JSON_CONTAINS, and is not chosen for an equality test on JSON_VALUE.'),
p(`Without an index the native type scans in 95 ms against 160 ms for text, since there is nothing to parse. Either index brings the query to under 2 ms. The surprises are in the JSON index rows.`),
G.ul([
`<strong>The predicate decides whether the index is used.</strong> The query written with <code>JSON_VALUE(doc, '$.customer.country') = N'MT'</code> read exactly as many pages after the index was created as before. The same question written with <code>JSON_CONTAINS</code> used it. Forcing the index with a hint for the <code>JSON_VALUE</code> form worked and took 21 ms, about twelve times slower than the computed column.`,
`<strong>Keeping the index is expensive when an indexed property changes.</strong> The update that took 0.2 seconds and 6.6 MB of log without the index took 5.2 seconds and 69.6 MB with it.`,
`<strong>It is not small.</strong> The database grew by 13.4 MB for two paths over documents that occupy 25 MB.`]),
G.callout('tip','WHICH INDEX',`For a property you know in advance and query by equality or range, the computed column with a B-tree index is still the better tool: the optimiser uses it for the natural predicate, it is narrow, and it only changes when that property changes. The JSON index is for containment and existence questions over paths you cannot enumerate one column at a time. Check the plan, not the syntax: an index that exists and is not chosen costs writes and returns nothing.`),
h2('Moving an existing column'),
p(`An <code>nvarchar(max)</code> column holding JSON can be changed to the native type with one statement, and the statement is all-or-nothing:`),
snip('text','r_t','[10.2] change an existing nvarchar(max) column to json','The statement has been terminated.'),
p(`One invalid row fails the whole change, so find those rows first with <code>ISJSON(doc) = 0</code>. Remember the normalisation above: after the change, duplicate keys and white space are gone. The change is one way; the documentation says a <code>json</code> column cannot be altered back to a string type.`)
];
G.save(3,parts)
