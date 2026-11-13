eval(localStorage.art_H); const G=window.G,p=G.p,h2=G.h2; const I=k=>JSON.parse(localStorage['ev_img'+k]);
window.IM=(k,cap)=>G.img('ZZ'+k,I(k).alt,cap).split('ZZ'+k+'_ID').join(String(I(k).id)).split('ZZ'+k+'_URL').join(I(k).url);
window.SN=(k,a,b)=>{const t=localStorage['ev_code_'+k];const i=t.indexOf(a);const j=t.indexOf(b,i);if(i<0||j<0)throw new Error('marker '+k+' '+(i<0?a:b).slice(0,40));return t.slice(i,j+b.length)};
window.SNIPS=[]; window.snip=(lang,k,a,b)=>{const t=window.SN(k,a,b);window.SNIPS.push([k,t]);return G.code(lang,t)}; const snip=window.snip;
const parts=[
p(`A nightly reporting job, a laboratory feed, a demographics synchronisation: much of the traffic into a FHIR server comes from software with no person at the keyboard. There is nobody to sign in and nobody to consent. In practice these services are often given a shared API key or a client secret that never expires, with access to everything, because that is the quickest thing to set up.`),
p(`SMART Backend Services is the standard alternative. The service proves its identity by signing a short-lived statement with a private key that never leaves it. In exchange it receives an access token that lasts five minutes and names exactly which resource types it may read or write. Nothing that crosses the network is worth stealing for longer than those five minutes.`),
p(`The earlier articles in this series, starting with <a href="https://www.dataa.dev/2025/08/10/fhir-api-security-complete-guide-to-authentication-authorization-and-fapi-2-0/">FHIR API Security Part 1</a>, covered the threat landscape and sender-constrained tokens. This one implements the Backend Services profile end to end in .NET 10: the client, a local token endpoint, and a gateway that enforces scopes in front of a HAPI FHIR server. Most of the tests are about what has to be refused, because that is where implementations of this profile go wrong.`),
G.callout('info','SCOPE',`SMART App Launch 2.2.0, the current release, on FHIR R4. All data is synthetic and every key is generated when the tests start. The token endpoint here is a teaching implementation. In production that role belongs to your identity platform, and the checks listed below are what to confirm it performs.`),
h2('What the profile requires'),
p(`The specification is short, and almost every sentence in it is a test case. These are the rules the sample implements, in the words of the two relevant pages of the guide.`),
G.table(['Area','Rule'],[
['Token request','A form POST with <code>grant_type=client_credentials</code>, a <code>scope</code>, <code>client_assertion_type</code> set to the JWT bearer URN, and the signed <code>client_assertion</code>'],
['Assertion header','<code>alg</code>, <code>kid</code> and <code>typ: JWT</code> are required. A <code>jku</code>, if present, must equal the key set URL given at registration'],
['Assertion claims','<code>iss</code> and <code>sub</code> are both the client ID; <code>aud</code> is the token endpoint URL; <code>exp</code> is no more than five minutes ahead; <code>jti</code> is unique'],
['Algorithms','Clients support RS384 and ES384. A server validates at least one of them'],
['Client keys','A TLS-protected key set URL is strongly preferred; a key set handed over at registration is discouraged. The server may cache keys only as long as the client\'s <code>Cache-Control</code> allows'],
['Replay','The server checks that the <code>jti</code> has not been seen for that client within the assertion lifetime'],
['Failure','Any authentication error is answered with <code>invalid_client</code>'],
['Scopes','The server confirms the requested scope is within what the client was pre-authorised for. The granted scope may differ from the request'],
['Token response','<code>access_token</code>, <code>token_type: bearer</code>, <code>expires_in</code> and <code>scope</code>. The lifetime should not exceed 300 seconds, and refresh tokens should not be issued'],
['Transport','TLS 1.2 or later for every exchange']]),
h2('Architecture: decide twice, and keep the FHIR server out of reach'),
p(`HAPI FHIR, like most FHIR servers, will answer any request that reaches it. It has no built-in notion of a SMART scope. The design therefore has three parts and one network rule: a client library, a token endpoint, a gateway that every FHIR request passes through, and a FHIR server that accepts connections from the gateway and from nothing else.`),
window.IM('1','The client authenticates with a signature. Authorisation is decided at the token endpoint, and again at the gateway for every request.'),
p(`Authorisation is decided in two places on purpose. The token endpoint decides what a client may ever ask for, from its registration. The gateway decides whether one request fits inside the token it carries. A token is a claim about a client; only the gateway knows what a particular request will make the FHIR server do.`),
G.table(['Decision','Option','Advantages','Disadvantages'],[
['Where scopes are enforced','A gateway in front of the FHIR server (this article)','Works with any FHIR server; one place to audit; the server never sees a token','Must understand FHIR request semantics, not just paths'],
['','Inside the FHIR server, through its own interceptors or a vendor feature','Sees the real query plan and the real results','Tied to one product; harder to test in isolation'],
['','Path rules in a general API gateway','Quick to configure','Blind to search parameters, which is where the leaks are'],
['Access token format','A signed JWT, verified locally (this article)','No call to the token endpoint per request; simple to scale','Cannot be revoked before it expires, so the lifetime must be short'],
['','An opaque token with introspection','Revocable at once','A network call on every FHIR request, and a dependency on the token endpoint being up']]),
p(`The sample has no package references. Signatures use the RSA and ECDSA classes in .NET, limited to the two algorithms the profile names. That keeps every check visible in a few hundred lines, which suits an article. It is not advice to write your own token endpoint: use your identity platform and its JWT library, and use the test list here as an acceptance test for them.`),
G.mer(G.MS+`
sequenceDiagram
    participant C as Backend service
    participant T as Token endpoint
    participant G as FHIR gateway
    C->>G: GET .well-known/smart-configuration
    G-->>C: Token endpoint, algorithms, capabilities
    C->>C: Sign a one-time assertion
    C->>T: POST client_credentials with the assertion
    T->>T: Verify key, signature, audience, expiry, jti, scope
    T-->>C: Access token, 300 seconds, granted scope
    C->>G: GET Patient with Bearer token
    G->>G: Verify token, work out what the request needs
    G-->>C: 200 with data, or 403 naming the missing scope`),
h2('The client: an assertion, a cached token, one host'),
p(`The assertion is a JWT with five claims, valid here for two minutes and used once.`),
snip('csharp','client','    public async Task<string> BuildAssertionAsync','        return Jose.Compact(input, await signer.SignAsync(Encoding.ASCII.GetBytes(input), cancel));\n    }'),
p(`Signing goes through an interface with one method. That is the most important line of the client's design: the private key does not have to be in the process. A key vault, a cloud key management service or a hardware module can hold a key that cannot be exported, sign the bytes it is given and return the signature. The sample's signer holds the key in memory, which is right for a test and wrong for production.`),
snip('csharp','client','public interface IAssertionSigner','    ValueTask<byte[]> SignAsync(ReadOnlyMemory<byte> data, CancellationToken cancel);\n}'),
p(`A token is fetched once and shared. Without the gate, twenty requests starting at the same moment on a cold service would each build an assertion and each call the token endpoint.`),
snip('csharp','client','    public async Task<AccessToken> GetTokenAsync','        finally { _gate.Release(); }\n    }'),
p(`The handler that attaches the token has two rules. It sends the token to the FHIR base URL and to no other host, because a FHIR resource can contain a reference to any address and following one must not hand over a credential. And when the server answers 401, it discards the token, gets one new token and tries once more.`),
snip('csharp','client','    protected override async Task<HttpResponseMessage> SendAsync','        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token.Value);\n        return await base.SendAsync(request, cancel);\n    }'),
p(`The client also checks what it was granted. The server is allowed to grant less than was asked for, and a service that discovers this at its first 403 in the middle of a batch is harder to operate than one that fails at start-up with the two scope lists side by side.`)
];
G.save(1,parts)
