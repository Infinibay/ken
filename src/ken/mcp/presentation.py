"""Adapt domain functions at the MCP/CLI tool boundary, not inside the domain."""
from __future__ import annotations

import inspect
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Literal, get_type_hints

from ken.presentation import render_compact, search_previews

OutputFormat = Literal["compact", "json"]


def present_tool(fn: Callable[..., Any], *, root: Callable[[], Path | None]) -> Callable[..., Any]:
    """Publish one shared optional output control while preserving domain calls."""
    signature = inspect.signature(fn)
    hints = get_type_hints(fn)
    if "output_format" in signature.parameters:
        raise ValueError("output_format is owned by the presentation boundary")

    def present(result: Any, output_format: str, kwargs: dict[str, Any]) -> Any:
        if output_format == "json" or kwargs.get("response_format") in {"evidence", "legacy"}:
            return result
        project = root()
        if fn.__name__ == "ken_find" and kwargs.get("scope", "files") in {"files", "symbols"} and isinstance(result, list) and project is not None:
            result = search_previews(result, project)
        return render_compact(result, tool_name=fn.__name__,
                              diagnostics=bool(kwargs.get("full") or kwargs.get("explain")))

    def validate(output_format: str) -> None:
        if output_format not in ("compact", "json"):
            raise ValueError("output_format must be compact or json")

    if inspect.iscoroutinefunction(fn):
        @wraps(fn)
        async def call_async(*args: Any, output_format: OutputFormat = "compact", **kwargs: Any) -> Any:
            validate(output_format)
            return present(await fn(*args, **kwargs), output_format, kwargs)
    else:
        @wraps(fn)
        def call_sync(*args: Any, output_format: OutputFormat = "compact", **kwargs: Any) -> Any:
            validate(output_format)
            return present(fn(*args, **kwargs), output_format, kwargs)

    wrapped: Callable[..., Any] = call_async if inspect.iscoroutinefunction(fn) else call_sync
    parameters = [p.replace(annotation=hints.get(p.name, p.annotation))
                  for p in signature.parameters.values()]
    parameters.append(inspect.Parameter("output_format", inspect.Parameter.KEYWORD_ONLY,
                                       default="compact", annotation=OutputFormat))
    # The SDK and Ken's CLI registry both inspect the same resolved signature.
    # Any avoids an inferred dict output schema for default plain text.
    setattr(wrapped, "__signature__", signature.replace(parameters=parameters, return_annotation=Any))
    wrapped.__annotations__ = hints | {"output_format": OutputFormat, "return": Any}
    wrapped.__doc__ = (fn.__doc__ or "") + (
        '\n\nReturns compact text by default: locations, names, numbered source and relevant status. '
        'output_format="json" preserves native result data; full/explain includes diagnostics.')
    return wrapped
