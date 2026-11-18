# One agent, three frameworks

Sample for the dataa.dev article "[One Agent, Three Frameworks: What Agent Framework, LangGraph and ADK Do When the Model Misbehaves](https://www.dataa.dev/2026/11/14/one-agent-three-frameworks-agent-framework-langgraph-adk/)".

The same support agent, with the same two tools, built with Microsoft Agent Framework, LangGraph and Google ADK
(ADK twice: through its native Gemini client and through its LiteLLM adapter). All four talk to a scripted
stand-in on localhost that speaks OpenAI Chat Completions and the Gemini API. The stand-in plays the part of a
model that behaves, and then of one that does not: it calls a tool that does not exist, sends the wrong types,
repeats a refund, returns errors, and never stops.

No model is called and no request leaves the machine. What is recorded is what each framework does with its
default settings, and then with a few lines of configuration that make the four behave alike.

| Path | What it is |
| --- | --- |
| `lab/tools.py` | The two tools, as plain Python functions, and a ledger of every execution |
| `lab/frameworks.py` | The four builders, default and hardened |
| `lab/standin.py` | The scripted stand-in for both wire protocols |
| `lab/run.py` | The scenarios, the output and the checks |
| `requirements.txt` | The framework versions used |

## Run

    ./ci.sh out

It takes about six minutes, most of it the scenario in which the model never stops.
