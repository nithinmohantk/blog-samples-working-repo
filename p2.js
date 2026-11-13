const G=window.G,p=G.p,h2=G.h2,snip=window.snip; const out=(a,b)=>{const t=window.SN('run',a,b);window.SNIPS.push(['run',t]);return G.code('text',t)};
const parts=[
h2('The token endpoint: every check, in order'),
p(`This is the whole of client authentication. The order matters as much as the checks.`),
snip('csharp','token','    private async Task<(ClientRegistration? Client, string Claimed, string? Failure)> AuthenticateAsync','        return (client, issuer, null);\n    }'),
p(`Three decisions in that method are the ones most often got wrong.`),
G.ul([
`<strong>The algorithm comes from a fixed list.</strong> A verifier that does whatever the <code>alg</code> header says can be handed a token marked <code>none</code>, or one marked as HMAC and "signed" with the client's public key, which is public. Both are in the test list below.`,
`<strong>The key comes from the registration.</strong> The assertion may carry a <code>jku</code> header naming a key set URL. If the server fetched whatever URL the token named, anyone could sign as any client. It must match the registered URL or the request is refused, without a fetch.`,
`<strong>The signature is verified before the replay cache is touched.</strong> If <code>jti</code> values were recorded first, an unauthenticated caller could fill the cache, or burn a real client's identifiers before it used them.`]),
p(`Every failure returns the same thing to the caller: HTTP 401 and <code>invalid_client</code>, with no description. The reason goes to the audit log. These are the twenty-two requests the test sends, with the response and the audit line for each.`),
out('  refused 401 invalid_client         an assertion signed','             audit: invalid_scope: nothing in \'system/Observation.rs\' is within the registered \'system/Patient.rs\''),
p(`The last three are scope errors, and they do carry a description, because by then the client has proved who it is and needs to know what to fix.`),
h2('Scopes: what may be asked for'),
p(`A v2 system scope is a resource type, or <code>*</code>, and a subset of the letters <code>cruds</code> in that order: create, read, update, delete, search. Two properties surprise people who come from the older <code>read</code> and <code>write</code> scopes. Writing does not imply reading, so a loader with <code>Observation.cu</code> cannot read back what it wrote. And reading does not imply searching, so a service with <code>Patient.r</code> can fetch a patient it knows the id of and cannot go looking for others.`),
p(`A request is granted the part of it that lies within the registration. A request with nothing inside the registration is an error.`),
snip('csharp','scope','    public ScopeSet GrantFrom','        return granted;\n    }'),
p(`Against a client registered for <code>system/Patient.rs system/Observation.rs</code>:`),
out('  asked system/Patient.rs  ','  asked openid                                       -> not a v2 system scope'),
p(`The fifth row deserves a second look. A request for <code>system/*.rs</code> from a client registered for two resource types is granted nothing. It would be easy to grant "the two types you do have", and it would be wrong: a wildcard is a request for every type that exists now or is added later, and a token carrying it would be honoured for all of them.`),
h2('Key rotation, and how long a removed key lives'),
p(`With a key set URL the client rotates keys without telling anyone: it publishes the new key beside the old one, starts signing with the new one, and later removes the old one. The server's side of that is a cache with two rules.`),
snip('csharp','token','    public async Task<JsonObject?> GetAsync','System.Text.Json.JsonException) { return null; }\n    }'),
p(`An unknown key ID is a reason to fetch the key set again, since the client may have rotated. It is also something any caller can produce at will, so a refetch is allowed at most once in ten seconds per client. From the run:`),
out('== key rotation','ok    once the cache lifetime the client asked for has passed, the removed key is refused'),
p(`The fourth check is the operational fact to take away. Removing a key from the published set does not revoke it. The server goes on accepting it until its cached copy expires, which is as long as the client's own <code>Cache-Control</code> header said. In the test that is 300 seconds. If a private key is believed stolen, removing it from the key set is the slow path; the fast path is disabling the client's registration at the token endpoint, and that needs to be a documented procedure with a named owner.`)
];
G.save(2,parts)
