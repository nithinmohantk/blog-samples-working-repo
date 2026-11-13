const G=window.G,p=G.p,h2=G.h2,snip=window.snip; const out=(a,b)=>{const t=window.SN('run',a,b);window.SNIPS.push(['run',t]);return G.code('text',t)};
const parts=[
h2('The gateway: what a request needs'),
p(`A valid token with <code>system/Patient.rs</code> arrives with <code>GET Patient?_revinclude=Observation:subject</code>. The path says Patient. The token says Patient. A gateway that compares the two forwards the request, and the FHIR server returns the patients together with every Observation that refers to them.`),
p(`That is the central problem of scope enforcement on FHIR. The resource type in the path is the type the search starts from. Search parameters can pull in other types, or answer questions about them, and each of those needs its own permission.`),
window.IM('2','What the gateway requires for eight request shapes. The third and fourth rows are the ones a path-based rule gets wrong.'),
snip('csharp','classifier','    private static string? SearchNeeds','        return null;\n    }'),
p(`The classifier turns a request into the list of permissions it needs, or refuses it. These are the twenty-six shapes in the test, with what each needs.`),
out('  GET    Patient/123 ','refused: a POST to the base must be a batch or transaction Bundle'),
p(`Some of the refusals are design decisions, and each has a reason.`),
G.ul([
`<strong>An <code>_include</code> must name its target type.</strong> <code>Patient:general-practitioner</code> can return a Practitioner, an Organization or a PractitionerRole. The gateway cannot grant permission for a type it cannot name, so the client has to say which one it wants.`,
`<strong>A chained search must name its type and go one level deep.</strong> <code>Observation?subject:Patient.family=Byrne</code> is a search of patients by name, answered through observations, and needs <code>Patient.s</code>.`,
`<strong>Operations are not exposed.</strong> <code>$everything</code> returns a patient's whole record across every resource type. An operation should be allowed one at a time, with its own rule, not by default.`,
`<strong>A transaction is judged by its entries.</strong> The guide says batches and transactions should be validated on the requests inside them. The gateway requires every entry's permission and refuses the whole Bundle if one is missing.`,
`<strong>A conditional update or delete needs search as well.</strong> It finds its target by a query before it writes.`]),
p(`Then the same clients against HAPI FHIR, through the gateway:`),
out('== the gateway, in front of a FHIR server','ok    a request to another host through the same HttpClient carries no token'),
p(`The line without an "ok" in the middle is the control experiment. The test sends the <code>_revinclude</code> search straight to HAPI, bypassing the gateway, and HAPI returns the three observations. The server is behaving correctly; it was asked a valid question. Deciding who may ask it is not its job in this architecture, which is why the network rule matters as much as the code: if the FHIR server can be reached directly, none of the above applies.`),
G.callout('warning','PRIVACY',`A scope that looks narrow on paper can be wide in practice. Before approving a registration, ask what the client could retrieve with that scope through <code>_include</code>, <code>_revinclude</code>, <code>_has</code>, chained parameters and operations, not only through the resource type it names. Under data protection law the test is what the client can access, not what it was meant to.`),
G.mer(G.MF+`
flowchart TD
    R["FHIR request"] --> T{"Token valid, for this<br/>server, not expired?"}
    T -- "no" --> U["401 with a Bearer challenge"]
    T -- "yes" --> C["Work out every permission<br/>the request needs"]
    C --> X{"Is the request shape<br/>one the gateway exposes?"}
    X -- "no" --> F1["403 with the reason"]
    X -- "yes" --> S{"Does the token grant<br/>all of them?"}
    S -- "no" --> F2["403 naming the<br/>missing scope"]
    S -- "yes" --> W["Forward without the token,<br/>rewrite addresses in the reply"]
    style U fill:#FEF2F2,stroke:#D13212,stroke-width:2px,color:#991B1B
    style F1 fill:#FEF2F2,stroke:#D13212,stroke-width:2px,color:#991B1B
    style F2 fill:#FEF2F2,stroke:#D13212,stroke-width:2px,color:#991B1B
    style W fill:#F0FFF4,stroke:#1D8102,stroke-width:2px,color:#145202
    style C fill:#FFF3E0,stroke:#FF9900,stroke-width:2px,color:#232F3E`),
h2('Paging links are capabilities'),
p(`A paged search returns a link to the next page. On HAPI FHIR that link is the base URL with a <code>_getpages</code> parameter holding a search identifier. It names no resource type, so there is nothing in it to check a scope against, and whoever holds the link can fetch the page. A client with a valid token for something else entirely could replay a link it was never given.`),
p(`The gateway closes that in two steps. When it returns a search result it rewrites the server's internal address to the public one and adds a page token: a keyed hash of the client ID, the token's scope and the search identifier. When a paging request comes back, the page token must match the caller.`),
snip('csharp','gateway','        // A next-page link is only good for','            await ForwardAsync(http, method, $"?{paging}", null, (clientId, rawScope));\n            return;\n        }'),
p(`In the run, the client that ran the search follows its next link. A different client with <code>system/*.cruds</code>, the widest scope there is, is refused the same link, and so is anyone who strips the page token off.`),
h2('The client over time'),
out('== the client over time','ok    after the server restarts with a new signing key, the cached token gets 401 and the handler recovers with one new token'),
p(`The token endpoint in the sample creates its signing key when it starts and keeps it in memory. A restart therefore invalidates every token in circulation. With five-minute tokens and a client that retries once on 401, the cost of that is one extra token request per client, as the last line shows. That trade is available only because the tokens are short-lived.`),
h2('A second client, in Python'),
p(`Agreement between a client and a server written by the same person proves little, since both can share a misunderstanding. The build therefore runs a second client written in Python with PyJWT. It signs with RS384 where the .NET tests mostly use ES384, and it verifies the server's access token with a different library.`),
snip('python','python','def assertion(','headers={"kid": key_id, "typ": "JWT"})'),
out('  ok    discovery offers private_key_jwt with RS384','  8 of 8 checks passed')
];
G.save(3,parts)
