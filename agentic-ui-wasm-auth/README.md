# Agentic UI in Blazor WebAssembly, with authentication

Sample for the dataa.dev article "Agentic UI in Blazor WebAssembly: Sessions, Tokens and Who May Approve".
It follows [agentic-ui-blazor](../agentic-ui-blazor), where the Blazor components ran on the server.
Here they run in the browser, so the browser is the AG-UI client and every request has to prove who sent it.

All orders, customers and people are invented. The model is a scripted stand-in and sign-in is a lab page
with two buttons: nothing needs a key, an identity provider or a cloud account.

| Path | What it is |
| --- | --- |
| `src/Desk.Client` | Blazor WebAssembly app using `Microsoft.AspNetCore.Components.AI`. It calls its own host, holds no token, and sends the person to sign in again on a 401 |
| `src/Desk.Bff` | The web host: serves the app, keeps the session in an HttpOnly cookie, and forwards `/agent` to the agent service with a short-lived token for the signed-in person |
| `src/Desk.Agent` | The agent service: validates the token on every request, ties each pending approval to the person it was asked of, and gives the tools the caller's identity |
| `src/Desk.Core` | The agent pipeline, the tools, the payment stand-in, and `LabTokenIssuer`, which stands in for the identity provider's token endpoint |
| `tests/Desk.Tests` | 23 tests on in-memory servers: the agent service with good and bad tokens, then the web host in front of it |
| `e2e/run.py` | Chromium (Playwright) against the published output: eleven steps, with screenshots |
| `ci.sh` | Everything the workflow runs |

## Run

    ./ci.sh out          # .NET 11 SDK and Python 3; installs Playwright's Chromium

    # or by hand, in two terminals
    DESK_LAB=true dotnet run --project src/Desk.Agent --urls http://127.0.0.1:5111
    DESK_LAB=true AGENT_URL=http://127.0.0.1:5111 dotnet run --project src/Desk.Bff --urls http://127.0.0.1:5110

Open http://127.0.0.1:5110, sign in as Sam, and ask: `Where is order O-1001?`, `Refund order O-1003` (inside Sam's
limit of 40.00), `Refund order O-1001` (42.00, above it). Sign out, sign in as Alex, and approve the same refund.

`DESK_LAB=true` allows the session cookie over plain HTTP and adds the `/ledger`, `/wire` and `/reset` endpoints
that the browser test reads. Leave it off anywhere else.

## What is a stand-in

- **Sign-in.** `LabUsers` and the `/signin` page stand in for OpenID Connect. Replace them with `AddOpenIdConnect`; the cookie setup stays.
- **The token.** `LabTokenIssuer` signs with a fake key that is in this repository. With a real identity provider the web host asks it for a token for the agent service, and the agent service validates with `Authority` and `Audience`.
- **The model.** `ScriptedModel` makes the same decision for the same conversation every time.

## Versions

.NET SDK 11.0.100; `Microsoft.AspNetCore.Components.AI` 0.1.0-preview.1.26466.103 (experimental);
`Microsoft.AspNetCore.Components.WebAssembly` and `Microsoft.AspNetCore.Authentication.JwtBearer` 11.0.0;
`AGUI.Client`, `AGUI.Server`, `AGUI.Formatting` 1.0.1; `Microsoft.Extensions.AI` 11.0.0.
