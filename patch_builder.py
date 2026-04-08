"""
Translation layer between AI-friendly patch JSON and the encoder-ready dict
that patch_encoder.encode_patch() expects.

The AI outputs module names and block names as strings.
This module resolves them to numeric IDs and positions.
"""

import json
import os
from difflib import get_close_matches

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

with open(os.path.join(_DATA_DIR, "ModuleIndex.json")) as _f:
    _FULL_INDEX = json.load(_f)

with open(os.path.join(_DATA_DIR, "module_reference.json")) as _f:
    _MODULE_REF = json.load(_f)

_NAME_TO_ID = {name: info["id"] for name, info in _MODULE_REF.items()}
_ALL_MODULE_NAMES = list(_NAME_TO_ID.keys())


class BuildError(Exception):
    pass


def build_patch(ai_json):
    """
    Convert AI-friendly JSON into the dict format expected by encode_patch().

    ai_json: dict with keys:
        name: str
        pages: list[str]  (page names)
        modules: list[dict] each with:
            type: str           (module name, e.g. "Plate Reverb")
            page: int           (0-indexed page number)
            position: int       (grid cell, 0-39 per page)
            color: str          (color name)
            parameters: dict    (param_block_name -> float 0.0-1.0)  [optional]
            options: dict       (option_name -> value_string)         [optional]
            name: str           (custom label for this instance)      [optional]
        connections: list[dict] each with:
            from: str    ("ModuleType.block_name" or "ModuleType#N.block_name" for duplicates)
            to: str      (same format)
            strength: int (0-100, default 100)

    Returns: dict ready for patch_encoder.encode_patch()
    Raises: BuildError with human-readable message on invalid input
    """
    errors = []

    if not isinstance(ai_json, dict):
        raise BuildError("Expected a JSON object, got something else.")

    patch_name = str(ai_json.get("name", "AI Patch"))[:16]
    page_names = ai_json.get("pages", ["Main"])
    if not isinstance(page_names, list):
        page_names = ["Main"]
    ai_modules = ai_json.get("modules", [])
    ai_connections = ai_json.get("connections", [])

    if not isinstance(ai_modules, list) or not ai_modules:
        raise BuildError("No modules defined in patch (expected a 'modules' array).")
    if not isinstance(ai_connections, list):
        ai_connections = []

    # Build modules, tracking type instances for connection resolution
    modules = []
    type_counter = {}  # "Plate Reverb" -> count seen so far
    type_instance_map = {}  # "Plate Reverb" -> [0, 3, ...] module indices
    occupied = {}  # (page, cell) -> module_index for collision detection

    for i, ai_mod in enumerate(ai_modules):
        mod_type = ai_mod.get("type", "")
        resolved_name = _resolve_module_name(mod_type)
        if resolved_name is None:
            close = get_close_matches(mod_type, _ALL_MODULE_NAMES, n=1, cutoff=0.6)
            suggestion = f" Did you mean '{close[0]}'?" if close else ""
            errors.append(f"Module #{i}: '{mod_type}' not found.{suggestion}")
            continue

        mod_id = _NAME_TO_ID[resolved_name]
        mod_def = _FULL_INDEX[str(mod_id)]

        page = ai_mod.get("page", 0)
        position = ai_mod.get("position", _next_free_position(occupied, page))
        color_name = ai_mod.get("color", "Blue")
        custom_name = ai_mod.get("name", resolved_name)[:16]

        # Resolve blocks from the full index
        blocks_def = mod_def.get("blocks", {})
        default_block_count = mod_def.get("default_blocks", len(blocks_def))
        min_blocks = mod_def.get("min_blocks", default_block_count)

        # Collect block names referenced in connections targeting this module
        connected_blocks = set()
        for ai_conn in ai_connections:
            for endpoint_key in ("from", "to"):
                ep = ai_conn.get(endpoint_key, "")
                if "." in ep:
                    mod_part, blk = ep.rsplit(".", 1)
                    mod_part_clean = mod_part.split("#")[0].strip()
                    if _resolve_module_name(mod_part_clean) == resolved_name:
                        connected_blocks.add(blk.strip())

        # Determine which optional blocks to activate
        ai_params = ai_mod.get("parameters", {})
        active_blocks = {}
        block_count = 0
        for bname, binfo in sorted(blocks_def.items(), key=lambda x: x[1].get("position", 0)):
            is_default = binfo.get("isDefault", False)
            is_needed = bname in ai_params or bname in connected_blocks or is_default
            if is_needed or block_count < min_blocks:
                active_blocks[bname] = {
                    "position": block_count,
                    "isParam": binfo.get("isParam", False),
                    "isDefault": is_default,
                }
                block_count += 1

        # Resolve parameters (name -> 0.0-1.0 float)
        parameters = {}
        params_count = 0
        for bname, binfo in active_blocks.items():
            if binfo["isParam"]:
                params_count += 1
                val = ai_params.get(bname, _get_default_value(mod_def, bname))
                parameters[bname] = max(0.0, min(1.0, float(val)))

        # Resolve options
        options_binary = _resolve_options(mod_def, ai_mod.get("options", {}))

        # Module size in 4-byte words:
        # 8 header fields + 2 option words + N params + S saved_data words + 4 name words
        saved_data_size = 0
        module_size = 14 + params_count + saved_data_size

        # Grid positions occupied by this module — auto-fix overlaps
        mod_width = max(block_count, min_blocks)
        positions = list(range(position, position + mod_width))

        has_overlap = any((page, cell) in occupied for cell in positions)
        if has_overlap:
            position = _next_free_span(occupied, page, mod_width)
            positions = list(range(position, position + mod_width))

        for cell in positions:
            occupied[(page, cell)] = i

        # Track instance for connection resolution
        type_counter.setdefault(resolved_name, 0)
        instance_num = type_counter[resolved_name]
        type_counter[resolved_name] += 1
        type_instance_map.setdefault(resolved_name, [])
        type_instance_map[resolved_name].append(len(modules))

        module_dict = {
            "number": len(modules),
            "mod_idx": mod_id,
            "name": custom_name,
            "type": resolved_name,
            "version": mod_def.get("version", 1),
            "page": page,
            "position": positions,
            "color": color_name,
            "header_color_id": _color_to_id(color_name),
            "params": params_count,
            "parameters": parameters,
            "parameters_raw": [],
            "options_binary": options_binary,
            "size": module_size,
            "size_of_saveable_data": saved_data_size,
            "saved_data": [],
            "blocks": active_blocks,
            "cpu": mod_def.get("cpu", 0),
            "_instance": instance_num,
            "_type_name": resolved_name,
        }
        modules.append(module_dict)

    if errors:
        raise BuildError("\n".join(errors))

    # Resolve connections
    connections = []
    for ci, ai_conn in enumerate(ai_connections):
        try:
            src_mod_idx, src_block_pos = _resolve_connection_endpoint(
                ai_conn.get("from", ""), modules, type_instance_map
            )
            dst_mod_idx, dst_block_pos = _resolve_connection_endpoint(
                ai_conn.get("to", ""), modules, type_instance_map
            )
        except BuildError as e:
            errors.append(f"Connection #{ci}: {e}")
            continue

        connections.append({
            "source_raw": src_mod_idx,
            "source_block_raw": src_block_pos,
            "dest_raw": dst_mod_idx,
            "dest_block_raw": dst_block_pos,
            "strength_raw": ai_conn.get("strength", 100),
        })

    if errors:
        raise BuildError("\n".join(errors))

    # Assemble pages
    n_pages = max((m["page"] for m in modules), default=0) + 1
    while len(page_names) < n_pages:
        page_names.append("")
    page_names = page_names[:n_pages]

    # Build colors list (parallel to modules)
    colors = [_color_to_id(m.get("color", "Blue")) for m in modules]

    # Clean up internal keys
    for m in modules:
        m.pop("_instance", None)
        m.pop("_type_name", None)

    return {
        "name": patch_name,
        "size": 0,  # encoder calculates this
        "modules": modules,
        "connections": connections,
        "pages": page_names,
        "pages_count": n_pages,
        "starred": [],
        "colors": colors,
        "meta": {
            "n_modules": len(modules),
            "n_connections": len(connections),
            "n_pages": n_pages,
            "n_starred": 0,
        },
    }


def _resolve_module_name(name):
    """Exact match first, then case-insensitive."""
    if name in _NAME_TO_ID:
        return name
    lower_map = {n.lower(): n for n in _ALL_MODULE_NAMES}
    return lower_map.get(name.lower())


def _resolve_connection_endpoint(endpoint_str, modules, type_instance_map):
    """
    Parse "ModuleType.block_name" or "ModuleType#N.block_name" into (module_index, block_position).
    N is 0-indexed instance number for duplicate module types.
    """
    if "." not in endpoint_str:
        raise BuildError(f"Invalid format '{endpoint_str}' — expected 'ModuleType.block_name'")

    module_part, block_name = endpoint_str.rsplit(".", 1)

    instance = 0
    if "#" in module_part:
        module_part, inst_str = module_part.rsplit("#", 1)
        try:
            instance = int(inst_str)
        except ValueError:
            raise BuildError(f"Invalid instance number in '{endpoint_str}'")

    resolved_name = _resolve_module_name(module_part.strip())
    if resolved_name is None:
        close = get_close_matches(module_part, _ALL_MODULE_NAMES, n=1, cutoff=0.6)
        suggestion = f" Did you mean '{close[0]}'?" if close else ""
        raise BuildError(f"Module type '{module_part}' not found.{suggestion}")

    instances = type_instance_map.get(resolved_name, [])
    if instance >= len(instances):
        raise BuildError(
            f"Instance #{instance} of '{resolved_name}' not found — "
            f"only {len(instances)} instance(s) in patch."
        )
    mod_idx = instances[instance]
    module = modules[mod_idx]

    block_name_clean = block_name.strip()
    blocks = module.get("blocks", {})
    if block_name_clean not in blocks:
        available = list(blocks.keys())
        close = get_close_matches(block_name_clean, available, n=1, cutoff=0.6)
        suggestion = f" Did you mean '{close[0]}'?" if close else f" Available: {available}"
        raise BuildError(
            f"Block '{block_name_clean}' not found on '{resolved_name}'.{suggestion}"
        )

    return mod_idx, blocks[block_name_clean]["position"]


def _resolve_options(mod_def, ai_options):
    """Convert {"option_name": "value_string"} to {"option_name": index_int}."""
    options_def = mod_def.get("options", {})
    if not isinstance(options_def, dict):
        return {}

    result = {}
    for opt_name, opt_values in options_def.items():
        ai_val = ai_options.get(opt_name)
        if ai_val is not None and isinstance(opt_values, list):
            str_values = [str(v).lower() for v in opt_values]
            ai_val_str = str(ai_val).lower()
            if ai_val_str in str_values:
                result[opt_name] = str_values.index(ai_val_str)
            else:
                result[opt_name] = 0
        else:
            result[opt_name] = 0
    return result


def _get_default_value(mod_def, block_name):
    """Get the default parameter value (0.0-1.0) from ModuleIndex."""
    pd = mod_def.get("param_defaults", {})
    if isinstance(pd, dict) and block_name in pd:
        info = pd[block_name]
        if isinstance(info, dict):
            return info.get("value", 0.0)
    return 0.0


def _color_to_id(name):
    from patch_encoder import COLOR_NAME_TO_ID
    return COLOR_NAME_TO_ID.get(name, 1)


def _next_free_position(occupied, page):
    """Find the next unoccupied grid cell on a page."""
    for cell in range(40):
        if (page, cell) not in occupied:
            return cell
    return 0


def _next_free_span(occupied, page, width):
    """Find the next contiguous run of `width` free cells on a page."""
    for start in range(40 - width + 1):
        if all((page, start + w) not in occupied for w in range(width)):
            return start
    # Overflow to next page if current is full
    next_page = page + 1
    for start in range(40 - width + 1):
        if all((next_page, start + w) not in occupied for w in range(width)):
            return start
    return 0
