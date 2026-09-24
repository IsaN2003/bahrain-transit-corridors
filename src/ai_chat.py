"""
AI chat assistant for the corridor dashboard.

A user types a question ("What were the top routes into Saudi Arabia in 2023?"),
we send it to Claude along with a description of our data tool, and Claude
decides whether it needs numbers. If it does, it asks us to run
query_corridors() (defined in ai_tools.py) with some arguments; we run it,
send the result back, and repeat until Claude replies with a plain-text answer.
"""

import json
from dotenv import load_dotenv
from anthropic import Anthropic
from src.ai_tools import query_corridors

load_dotenv()                       # read ANTHROPIC_API_KEY from .env
MODEL = "claude-haiku-4-5-20251001"  # small, fast, cheap model; plenty for short data Q&A

# --- 1. describe the tool to Claude (this is the "menu" it reads) ---
# Claude never sees our Python code. It only sees this name, description and
# input schema, and uses them to decide when to call the tool and what
# arguments to pass. The descriptions are effectively instructions, so they
# spell out units, valid years and example values.
TOOLS = [{
    "name": "query_corridors",
    "description": (
        "Look up Bahrain vehicle re-export corridor estimates (HS chapter 87). "
        "Returns aggregated values in US$ millions. Use this for ANY question about "
        "numbers, countries, years, top routes, origins, or destinations. "
        "Figures are statistical estimates, not tracked shipments."
    ),
    # JSON Schema for the arguments; these mirror query_corridors()'s parameters
    "input_schema": {
        "type": "object",
        "properties": {
            "year": {"type": "integer",
                     "description": "Filter to one year 2021-2026; omit for all years."},
            "origin": {"type": "string",
                       "description": "Origin country (where vehicles are made), e.g. 'Japan'."},
            "dest": {"type": "string",
                     "description": "Destination country (final market), e.g. 'Saudi Arabia'."},
            # enum limits Claude to the options query_corridors() understands
            "group_by": {"type": "string",
                         "enum": ["corridor", "origin", "destination", "year"],
                         "description": "How to aggregate. Default 'corridor'."},
            "top_n": {"type": "integer", "description": "How many rows (default 10)."},
        },
        "required": [],  # every argument is optional; the function has defaults
    },
}]

# --- 2. system prompt: the standing instructions for every conversation ---
# Main goals: stop the model making up numbers (always go through the tool),
# make sure it mentions that the figures are estimates, and keep answers short
# and consistently formatted for the dashboard's chat box.
SYSTEM = (
    "You are a trade-data analyst for a dashboard on vehicle (HS 87) re-export "
    "corridors through Bahrain. Answer using ONLY the query_corridors tool to get "
    "numbers — never invent figures. Call the tool for anything involving values, "
    "countries, years, or rankings. Values are US$ millions and are STATISTICAL "
    "ESTIMATES (proportional allocation), not tracked shipments — note this when "
    "relevant. Be concise (2-4 sentences), format money like $350.9M."
)

# argument names we'll actually pass through to query_corridors(). Anything
# else the model sends (e.g. a made-up "df" or "country") is dropped, so a
# bad tool call can't crash the function with an unexpected keyword
ALLOWED = {"year", "origin", "dest", "group_by", "top_n"}


# --- 3. the conversation loop ---
def ask(question, df, history=None):
    """Run one question through Claude, letting it call the data tool as needed.

    - question: the user's latest message (plain text)
    - df:       corridor data from ai_tools.load_named_corridors(); passed in
                so it's loaded once by the app, not on every question
    - history:  the `messages` list returned by the previous ask() call, so
                follow-ups like "and in 2022?" keep their context. None = new chat
    Returns (answer_text, messages); keep `messages` and pass it back next time.
    """
    client = Anthropic()  # picks up ANTHROPIC_API_KEY from the environment
    # the API is stateless, so every request sends the whole conversation so far
    messages = (history or []) + [{"role": "user", "content": question}]

    # keep going until Claude stops asking for data and writes an answer;
    # one question can take several rounds (e.g. look up a total, then a breakdown)
    while True:
        resp = client.messages.create(
            model=MODEL, max_tokens=1024, system=SYSTEM,
            tools=TOOLS, messages=messages,
        )
        # record Claude's turn as-is (text and/or tool requests); the API
        # requires each tool result to follow the request it answers
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":            # Claude has a final answer
            # the reply is a list of content blocks; join the text ones together
            text = "".join(b.text for b in resp.content if b.type == "text")
            return text, messages

        # Claude asked to call the tool — run it and hand back the result
        # (it can request more than one call in a single turn, so loop over them)
        results = []
        for block in resp.content:
            if block.type == "tool_use":
                # block.input is the arguments dict Claude chose; keep only allowed keys
                args = {k: v for k, v in block.input.items() if k in ALLOWED}
                data = query_corridors(df, **args)
                results.append({"type": "tool_result",
                                "tool_use_id": block.id,  # links this result to Claude's request
                                "content": json.dumps(data)})
        # tool results go back in a "user" message; the loop then calls
        # Claude again so it can read the numbers and continue
        messages.append({"role": "user", "content": results})
