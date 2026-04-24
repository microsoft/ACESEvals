from __future__ import annotations

from logging import getLogger
from time import time
from typing import TYPE_CHECKING, Any

from shortuuid import uuid

from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.model._chat_message import ChatMessageSystem
from inspect_ai.model._generate_config import (
    GenerateConfig,
    ResponseSchema,
)
from inspect_ai.model._openai_convert import messages_from_openai
from inspect_ai.model._providers.providers import validate_openai_client
from inspect_ai.tool._tool_choice import ToolChoice, ToolFunction
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.tool._tool_params import ToolParams
from inspect_ai.util._json import JSONSchema

from .util import (
    apply_message_ids,
    bridge_generate,
    clear_generation_params,
    resolve_generate_config,
    resolve_inspect_model,
)

if TYPE_CHECKING:
    from openai.types.chat import (
        ChatCompletion,
        ChatCompletionToolChoiceOptionParam,
        ChatCompletionToolParam,
    )


logger = getLogger(__name__)


async def inspect_completions_api_request(
    json_data: dict[str, Any],
    headers: dict[str, str] | None,
    bridge: AgentBridge,
) -> "ChatCompletion":
    validate_openai_client("agent bridge")

    from openai.types.chat import (
        ChatCompletion,
        ChatCompletionMessageParam,
    )

    from inspect_ai.model._openai import (
        openai_chat_choices,
        openai_completion_usage,
    )

    bridge_model_name = str(json_data["model"])
    model = resolve_inspect_model(bridge_model_name, bridge.model_aliases, bridge.model)
    model_name = model.api.model_name

    # convert openai messages to inspect messages
    openai_messages: list[ChatCompletionMessageParam] = json_data["messages"]
    messages = await messages_from_openai(openai_messages, model_name)

    # extract generate config (hoist instructions into system_message)
    config = generate_config_from_openai_completions(json_data)
    if not bridge.forward_generation_config:
        clear_generation_params(config)
    config.extra_headers = headers
    if config.system_message is not None:
        messages.insert(0, ChatMessageSystem(content=config.system_message))
        config.system_message = None

    # try to maintain id stability
    apply_message_ids(bridge, messages)

    # read openai tools and tool choice
    openai_tools: list[ChatCompletionToolParam] = json_data.get("tools", [])
    tools = tools_from_openai_tools(openai_tools)
    openai_tool_choice: ChatCompletionToolChoiceOptionParam | None = json_data.get(
        "tool_choice", None
    )
    tool_choice = tool_choice_from_openai_tool_choice(openai_tool_choice)

    # give inspect-level config priority over agent default config
    config = resolve_generate_config(model, config)

    # if there is a bridge filter give it a shot first
    output, c_message = await bridge_generate(
        bridge, model, messages, tools, tool_choice, config
    )
    if c_message is not None:
        messages.append(c_message)

    # update state if we have more messages than the last generation
    bridge._track_state(messages, output)

    # inspect completion to openai completion
    return ChatCompletion(
        id=uuid(),
        created=int(time()),
        object="chat.completion",
        choices=openai_chat_choices(output.choices),
        model=model_name,
        usage=openai_completion_usage(output.usage) if output.usage else None,
    )


def tool_choice_from_openai_tool_choice(
    tool_choice: "ChatCompletionToolChoiceOptionParam" | None,
) -> ToolChoice | None:
    inspect_tool_choice: ToolChoice | None = None
    if tool_choice is not None:
        match tool_choice:
            case "auto" | "none":
                inspect_tool_choice = tool_choice
            case "required":
                inspect_tool_choice = "any"
            case _:
                assert tool_choice["type"] == "function", (
                    '"custom" tool calls are not supported'
                )
                inspect_tool_choice = ToolFunction(name=tool_choice["function"]["name"])
    return inspect_tool_choice


def tools_from_openai_tools(tools: "list[ChatCompletionToolParam]") -> list[ToolInfo]:
    inspect_tools: list[ToolInfo] = []
    for tool in tools:
        assert tool["type"] == "function", '"custom" tool calls are not supported'
        function = tool["function"].copy()
        inspect_tools.append(
            ToolInfo(
                name=function["name"],
                description=function["description"],
                parameters=ToolParams.model_validate(function["parameters"]),
            )
        )
    return inspect_tools


def _resolve_schema_refs(
    node: Any, defs: dict[str, Any], seen: set[str] | None = None
) -> Any:
    """Inline all ``$ref`` pointers using the ``$defs`` definitions.

    The ``JSONSchema`` Pydantic model does not support ``$defs`` / ``$ref``,
    so references must be resolved before validation.  Circular references
    are broken by returning an empty ``{"type": "object"}`` sentinel.
    """
    if not isinstance(node, dict):
        return node

    if seen is None:
        seen = set()

    if "$ref" in node:
        ref: str = node["$ref"]
        # Only handle local "#/$defs/Name" references.
        prefix = "#/$defs/"
        if ref.startswith(prefix):
            name = ref[len(prefix):]
            if name in seen:
                # Circular reference – break the cycle.
                return {"type": "object"}
            if name in defs:
                from copy import deepcopy

                resolved = deepcopy(defs[name])
                return _resolve_schema_refs(resolved, defs, seen | {name})
        # Unknown $ref – return as-is (will likely be stripped by JSONSchema).
        return node

    # Recurse into standard schema keywords.
    for key in ("properties", "items", "additionalProperties"):
        if key not in node:
            continue
        val = node[key]
        if key == "properties" and isinstance(val, dict):
            node[key] = {
                k: _resolve_schema_refs(v, defs, seen) for k, v in val.items()
            }
        elif isinstance(val, dict):
            node[key] = _resolve_schema_refs(val, defs, seen)

    for kw in ("allOf", "anyOf", "oneOf"):
        if kw in node and isinstance(node[kw], list):
            node[kw] = [_resolve_schema_refs(s, defs, seen) for s in node[kw]]

    return node


def _fix_strict_json_schema(node: dict[str, Any]) -> dict[str, Any]:
    """Ensure every schema node has a 'type' key so strict mode works.

    Some Pydantic models produce ``items: {}`` or bare ``{}`` for untyped
    fields.  OpenAI structured-output strict mode rejects these.  This
    recursively patches empty or type-less sub-schemas with a permissive
    ``{"type": "object"}`` default.

    If the schema uses ``$defs`` / ``$ref``, those references are resolved
    inline first so that ``JSONSchema.model_validate()`` can handle the
    result (it does not support ``$ref``).
    """
    if not isinstance(node, dict):
        return node

    # Phase 1: resolve $ref → inline definitions.
    defs = node.pop("$defs", None) or node.pop("definitions", None) or {}
    if defs:
        from copy import deepcopy

        node = _resolve_schema_refs(deepcopy(node), defs)

    # Phase 2: patch type-less sub-schemas.
    return _patch_typeless(node)


def _patch_typeless(node: dict[str, Any]) -> dict[str, Any]:
    """Recursively add ``"type"`` to empty / type-less sub-schemas."""
    if not isinstance(node, dict):
        return node

    # Empty object → make it a permissive object type.
    if node == {}:
        return {"type": "object"}

    # If there is no 'type' and no '$ref', add a default.
    if "type" not in node and "$ref" not in node:
        node["type"] = "object"

    # Recurse into 'properties'.
    if "properties" in node and isinstance(node["properties"], dict):
        for key, val in node["properties"].items():
            if isinstance(val, dict):
                node["properties"][key] = _patch_typeless(val)

    # Recurse into 'items'.
    if "items" in node and isinstance(node["items"], dict):
        node["items"] = _patch_typeless(node["items"])

    # Recurse into composition keywords.
    for kw in ("allOf", "anyOf", "oneOf"):
        if kw in node and isinstance(node[kw], list):
            node[kw] = [
                _patch_typeless(s) if isinstance(s, dict) else s
                for s in node[kw]
            ]

    # Recurse into 'additionalProperties' when it's a schema dict.
    if "additionalProperties" in node and isinstance(
        node["additionalProperties"], dict
    ):
        node["additionalProperties"] = _patch_typeless(
            node["additionalProperties"]
        )

    return node


def generate_config_from_openai_completions(
    json_data: dict[str, Any],
) -> GenerateConfig:
    config = GenerateConfig()
    config.max_tokens = json_data.get(
        "max_completion_tokens", json_data.get("max_tokens", None)
    )

    config.top_p = json_data.get("top_p", None)
    config.temperature = json_data.get("temperature", None)
    stop = json_data.get("stop", None)
    if stop:
        config.stop_seqs = [stop] if isinstance(stop, str) else stop
    config.frequency_penalty = json_data.get("frequency_penalty", None)
    config.presence_penalty = json_data.get("presence_penalty", None)
    config.seed = json_data.get("seed", None)
    config.num_choices = json_data.get("n", None)
    config.logprobs = json_data.get("logprobs", None)
    config.top_logprobs = json_data.get("top_logprobs", None)
    config.logit_bias = json_data.get("logit_bias", None)
    config.parallel_tool_calls = json_data.get("parallel_tool_calls", None)
    config.reasoning_effort = json_data.get("reasoning_effort", None)

    # response format
    response_format: dict[str, Any] | None = json_data.get("response_format", None)
    if response_format is not None:
        json_schema: dict[str, Any] | None = response_format.get("json_schema", None)
        if json_schema is not None:
            schema_body = json_schema.get("schema", {})
            strict = json_schema.get("strict", None)
            # Sanitise the schema when strict mode is requested so that
            # empty sub-schemas (items: {}, bare {}) don't cause 400s.
            if strict:
                schema_body = _fix_strict_json_schema(schema_body)
            config.response_schema = ResponseSchema(
                name=json_schema.get("name", "schema"),
                description=json_schema.get("description", None),
                json_schema=JSONSchema.model_validate(schema_body),
                strict=strict,
            )

    return config
