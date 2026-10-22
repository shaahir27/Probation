"""Compile the supported JSON Schema surface into strict Pydantic validators.

Unsupported constraints fail before HTTP. Production jobs use closed explicit models;
the generic diagnostic interface also supports intentionally open JSON objects.
"""

import json
import math
from decimal import Decimal
from functools import lru_cache, reduce
from operator import getitem, or_
from types import GenericAlias
from typing import Annotated, Any, Literal, cast

from pydantic import (
    AfterValidator,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    TypeAdapter,
    ValidationError,
    create_model,
)


class UnsupportedSchema(ValueError):
    """The supplied schema cannot be enforced by this implementation."""


ANNOTATIONS = {"title", "description", "default", "$schema", "$id", "examples"}
SUPPORTED = ANNOTATIONS | {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "enum",
    "const",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
    "uniqueItems",
    "anyOf",
    "$defs",
    "$ref",
}


def _json_only(value: Any) -> Any:
    """Reject non-JSON/non-finite values, including undeclared extra object fields."""
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) is list:
        for item in value:
            _json_only(item)
        return value
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _json_only(item)
        return value
    raise ValueError("Expected finite JSON data")


def _matches_literal(value: Any, allowed: list[Any]) -> Any:
    if not any(
        value == item
        and (
            type(value) is type(item)
            or (type(value) in {int, float} and type(item) in {int, float})
        )
        for item in allowed
    ):
        raise ValueError("Value outside enum")
    return value


def _limit(value: Any, *, positive: bool = False) -> int:
    if type(value) is not int or value < int(positive):
        raise UnsupportedSchema("Invalid length/item bound")
    return value


def _number(value: Any) -> int | float:
    if type(value) not in {int, float} or (type(value) is float and not math.isfinite(value)):
        raise UnsupportedSchema("Invalid numeric constraint")
    return cast(int | float, value)


def _union(items: list[Any]) -> Any:
    if not items:
        raise UnsupportedSchema("Empty union")
    return reduce(or_, items)


def _annotated(base: Any, *metadata: Any) -> Any:
    """Construct dynamic Pydantic annotations without static type-alias assertions."""
    return getitem(Annotated, (base, *metadata))


def _compile(node: dict[str, Any], definitions: dict[str, Any], depth: int = 0) -> Any:
    if depth > 12 or not node or set(node) - SUPPORTED:
        raise UnsupportedSchema("Empty, too deep or unsupported schema")
    node = dict(node)
    definitions = {**definitions, **node.pop("$defs", {})}
    if "$ref" in node:
        ref = node.pop("$ref")
        if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
            raise UnsupportedSchema("Only local definition references are supported")
        name = ref.removeprefix("#/$defs/")
        if name not in definitions or set(node) - ANNOTATIONS:
            raise UnsupportedSchema("Unknown reference or constrained reference sibling")
        return _compile(definitions[name], definitions, depth + 1)
    if "anyOf" in node:
        branches = node.pop("anyOf")
        if not isinstance(branches, list) or not 1 <= len(branches) <= 16:
            raise UnsupportedSchema("Invalid union")
        for branch in branches:
            if not isinstance(branch, dict) or any(
                key in node and key not in ANNOTATIONS and node[key] != value
                for key, value in branch.items()
            ):
                raise UnsupportedSchema(
                    "Conflicting anyOf siblings require an unsupported intersection"
                )
        return _union([_compile({**node, **branch}, definitions, depth + 1) for branch in branches])
    kind = node.get("type")
    if isinstance(kind, list):
        if not kind or len(kind) > 7:
            raise UnsupportedSchema("Invalid type union")
        return _union([_compile({**node, "type": item}, definitions, depth + 1) for item in kind])
    if "enum" in node or "const" in node:
        values = node.get("enum", [node.get("const")])
        if not isinstance(values, list) or not 1 <= len(values) <= 128:
            raise UnsupportedSchema("Invalid enum")
        if any(item is not None and type(item) not in {str, bool, int, float} for item in values):
            raise UnsupportedSchema("Only scalar enums are supported")
        _json_only(values)
        if "enum" in node and "const" in node:
            values = [value for value in values if _literal_equal(value, node["const"])]
            if not values:
                raise UnsupportedSchema("Empty enum/const intersection")
        enum = getitem(Literal, tuple(values))
        constrained = {key: value for key, value in node.items() if key not in {"enum", "const"}}
        if kind is None:
            if set(constrained) - ANNOTATIONS:
                raise UnsupportedSchema("Untyped constrained enum")
            return _annotated(enum, BeforeValidator(lambda value: _matches_literal(value, values)))
        base = _compile(constrained, definitions, depth + 1)
        return _annotated(base, AfterValidator(lambda value: _matches_literal(value, values)))
    if kind == "null":
        return type(None)
    if kind == "boolean":
        return StrictBool
    if kind in {"integer", "number"}:
        constraints: dict[str, Any] = {"allow_inf_nan": False} if kind == "number" else {}
        for key, field in (
            ("minimum", "ge"),
            ("maximum", "le"),
            ("exclusiveMinimum", "gt"),
            ("exclusiveMaximum", "lt"),
            ("multipleOf", "multiple_of"),
        ):
            if key in node:
                constraints[field] = _number(node[key])
        if "multiple_of" in constraints and constraints["multiple_of"] <= 0:
            raise UnsupportedSchema("multipleOf must be positive")
        number_type = StrictInt if kind == "integer" else StrictFloat
        return _annotated(number_type, Field(**constraints))
    if kind == "string":
        constraints = {}
        for key, field in (("minLength", "min_length"), ("maxLength", "max_length")):
            if key in node:
                constraints[field] = _limit(node[key])
        if "pattern" in node:
            if not isinstance(node["pattern"], str):
                raise UnsupportedSchema("Invalid pattern")
            constraints["pattern"] = node["pattern"]
        return _annotated(StrictStr, Field(**constraints))
    if kind == "array":
        item = _compile(node["items"], definitions, depth + 1) if "items" in node else JsonValue
        constraints = {}
        for key, field in (("minItems", "min_length"), ("maxItems", "max_length")):
            if key in node:
                constraints[field] = _limit(node[key])
        result = _annotated(GenericAlias(list, item), Field(**constraints))
        if "uniqueItems" in node and type(node["uniqueItems"]) is not bool:
            raise UnsupportedSchema("uniqueItems must be boolean")
        if node.get("uniqueItems"):

            def unique(values: list[Any]) -> list[Any]:
                encoded = [_json_key(value) for value in values]
                if len(set(encoded)) != len(encoded):
                    raise ValueError("Array items must be unique")
                return values

            result = _annotated(result, AfterValidator(unique))
        return result
    if kind == "object" or "properties" in node:
        properties = node.get("properties", {})
        required = node.get("required", [])
        extra = node.get("additionalProperties", True)
        if (
            not isinstance(properties, dict)
            or len(properties) > 128
            or not isinstance(required, list)
        ):
            raise UnsupportedSchema("Invalid object properties/required")
        if set(required) - set(properties) or type(extra) is not bool:
            raise UnsupportedSchema(
                "Required unknown field or unsupported additionalProperties schema"
            )
        if not properties and extra:
            return dict[str, JsonValue]
        fields: dict[str, Any] = {}
        for i, (name, child) in enumerate(properties.items()):
            annotation = _compile(child, definitions, depth + 1)
            fields[f"field_{i}"] = (
                annotation,
                Field(default=... if name in required else None, alias=name),
            )
        return create_model(
            "StrictOutput",
            __config__=ConfigDict(
                strict=True, extra="allow" if extra else "forbid", allow_inf_nan=False
            ),
            **fields,
        )
    raise UnsupportedSchema("Schema must declare a supported type or enum")


def _literal_equal(left: Any, right: Any) -> bool:
    return bool(left == right) and (
        type(left) is type(right) or (type(left) in {int, float} and type(right) in {int, float})
    )


def _json_key(value: Any) -> Any:
    """JSON equality treats 1 and 1.0 alike, but distinguishes true from 1."""
    if type(value) in {int, float}:
        return ("number", Decimal(str(value)))
    if type(value) is dict:
        return ("object", tuple((key, _json_key(item)) for key, item in sorted(value.items())))
    if type(value) is list:
        return ("array", tuple(_json_key(item) for item in value))
    return (type(value).__name__, value)


@lru_cache(maxsize=256)
def _adapter(encoded: str) -> TypeAdapter[Any]:
    try:
        return TypeAdapter(_compile(json.loads(encoded), {}))
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        raise UnsupportedSchema("Schema cannot be enforced") from exc


def compile_schema(schema: dict[str, Any]) -> TypeAdapter[Any]:
    """Compile once by exact schema bytes; no six-decimal ledger rounding is applied."""
    try:
        encoded = json.dumps(schema, sort_keys=True, allow_nan=False)
        return _adapter(encoded)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise UnsupportedSchema("Invalid/unsupported output schema") from exc


def validate_json_schema(data: Any, schema: dict[str, Any]) -> tuple[bool, str | None]:
    """Compatibility API backed entirely by strict Pydantic validation."""
    try:
        _json_only(data)
        compile_schema(schema).validate_python(data, strict=True)
        return True, None
    except ValidationError as exc:
        return False, "; ".join(
            error["type"] for error in exc.errors(include_input=False, include_context=False)
        )
    except (TypeError, ValueError, OverflowError, RecursionError):
        return False, "Invalid schema or non-finite/non-JSON output"
