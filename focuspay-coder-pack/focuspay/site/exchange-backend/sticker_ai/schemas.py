"""Strict response schemas for image providers (no free-form trust)."""
from __future__ import annotations

from typing import Any


class SchemaError(ValueError):
    pass


def _require_str(d: dict[str, Any], key: str, *, max_len: int) -> str:
    if key not in d:
        raise SchemaError(f"missing_{key}")
    v = d[key]
    if not isinstance(v, str):
        raise SchemaError(f"type_{key}")
    if len(v) > max_len:
        raise SchemaError(f"len_{key}")
    return v


def _require_int(d: dict[str, Any], key: str, *, min_v: int, max_v: int) -> int:
    if key not in d:
        raise SchemaError(f"missing_{key}")
    v = d[key]
    if not isinstance(v, int) or isinstance(v, bool):
        raise SchemaError(f"type_{key}")
    if v < min_v or v > max_v:
        raise SchemaError(f"range_{key}")
    return v


def parse_generate_response(data: Any, *, max_variants: int = 4) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise SchemaError("root_not_object")
    model_id = _require_str(data, "model_id", max_len=120)
    variants = data.get("variants")
    if not isinstance(variants, list) or not variants:
        raise SchemaError("variants_invalid")
    if len(variants) > max_variants:
        raise SchemaError("variants_too_many")
    out_variants: list[dict[str, Any]] = []
    for i, item in enumerate(variants):
        if not isinstance(item, dict):
            raise SchemaError(f"variant_{i}_not_object")
        asset_key = _require_str(item, "asset_key", max_len=512)
        width = _require_int(item, "width", min_v=64, max_v=1024)
        height = _require_int(item, "height", min_v=64, max_v=1024)
        seed = item.get("seed")
        if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool)):
            raise SchemaError(f"variant_{i}_seed")
        out_variants.append(
            {
                "asset_key": asset_key,
                "width": width,
                "height": height,
                "seed": seed,
            }
        )
    return {"model_id": model_id, "variants": out_variants}


def parse_edit_response(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise SchemaError("root_not_object")
    model_id = _require_str(data, "model_id", max_len=120)
    asset_key = _require_str(data, "asset_key", max_len=512)
    width = _require_int(data, "width", min_v=64, max_v=1024)
    height = _require_int(data, "height", min_v=64, max_v=1024)
    return {
        "model_id": model_id,
        "asset_key": asset_key,
        "width": width,
        "height": height,
    }
