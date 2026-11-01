"""llm.py: the Gemini client, its warm-up, and the streaming call the graph's agent node uses.

The prompt and tool declarations are built in backend/graph; this file only talks to Gemini.
"""

from typing import AsyncIterator

from google import genai
from google.genai import types

try:
    from config import GEMINI_API_KEY, GEMINI_MODEL
except (ImportError, ModuleNotFoundError):
    from backend.config import GEMINI_API_KEY, GEMINI_MODEL


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client

    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)

    return _client

async def warm_llm() -> None:
    try:
        await _get_client().aio.models.generate_content(
            model=GEMINI_MODEL,
            contents="Hi",
            config=types.GenerateContentConfig(max_output_tokens=5),
        )
    except Exception as err:
        print(f"[llm] warm-up failed: {err}")


async def stream_text(
    prompt: str,
    system_instruction: str,
    tools: list[dict] | None = None,
) -> AsyncIterator[str | dict]:
    """Yield Gemini output as it arrives. Used by the graph's agent node.

    Text parts are yielded as str; tool calls as {"name": ..., "args": {...}} dict.
    tools are declarations {name, description, parameters (JSON schema)}; 
    """
    tool_config = {}
    if tools:
        tool_config = {
            "tools": [types.Tool(function_declarations=[
                types.FunctionDeclaration(name=t["name"], description=t["description"], parameters_json_schema=t["parameters"])
                for t in tools
            ])],
            "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
        }
    stream = await _get_client().aio.models.generate_content_stream(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.3,
            max_output_tokens=150,
            **tool_config,
        ),
    )
    async for chunk in stream:
        # Extract candidate content
        candidates = chunk.candidates
    
        if not candidates:
            continue
    
        content = candidates[0].content
        if not content:
            continue
    
        # Process individual response parts
        for part in content.parts or []:
    
            if part.function_call:
                yield {
                    "name": part.function_call.name,
                    "args": dict(part.function_call.args or {}),
                }
    
            elif part.text and not part.thought:
                yield part.text
