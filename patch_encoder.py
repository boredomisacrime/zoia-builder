"""
Standalone ZOIA binary patch encoder.
Ported from zoia_lib (https://github.com/meanmedianmoge/zoia_lib) by meanmedianmoge.
Original code is GPL-3.0 licensed.

Takes a structured patch dict and produces a valid .bin file that the ZOIA pedal can read.
"""

import json
import math
import os
import struct

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

with open(os.path.join(_DATA_DIR, "ModuleIndex.json")) as _f:
    MODULE_INDEX = json.load(_f)

COLOR_NAME_TO_ID = {
    "Blue": 1, "Green": 2, "Red": 3, "Yellow": 4, "Aqua": 5,
    "Magenta": 6, "White": 7, "Orange": 8, "Lima": 9, "Surf": 10,
    "Sky": 11, "Purple": 12, "Pink": 13, "Peach": 14, "Mango": 15,
}


def encode_patch(pch, output_path=None):
    """
    Encode a patch dict into ZOIA binary format.

    pch: dict matching the structure produced by PatchBinary.parse_data() —
         must have keys: name, modules, connections, pages, starred, colors, meta
    output_path: optional file path to write the .bin to

    Returns the binary data as a bytearray.
    """
    file_array = bytearray()
    farray = bytearray()

    patch_name = _encode_text(pch["name"], 16)
    module_count = _encode_value(pch["meta"]["n_modules"], 4)

    modules_array = bytearray()
    colors_array = bytearray()

    for module in pch["modules"]:
        module_array = bytearray()

        module_size = _encode_value(module["size"], 4)
        module_type = _encode_value(module["mod_idx"], 4)
        module_version = _encode_value(module["version"], 4)
        module_page = _encode_value(module["page"], 4)

        color_id = module.get("header_color_id")
        if color_id is None:
            color_id = COLOR_NAME_TO_ID.get(module.get("color", "Blue"), 1)
        module_color = _encode_value(color_id, 4)

        module_position = _encode_value(min(module["position"]), 4)
        params_count = module.get("params", len(module.get("parameters", {})))
        module_params_count = _encode_value(params_count, 4)
        module_size_bytes = _encode_value(module.get("size_of_saveable_data", 0), 4)

        module_options = bytearray()
        options_list = _get_options_bytes(module)
        options_padding = 8 - len(options_list)
        for option_byte in options_list:
            module_options.extend(_encode_byte(option_byte, 1))
        if options_padding > 0:
            module_options.extend(_encode_byte(0, options_padding))

        module_params = bytearray()
        params_raw = module.get("parameters_raw")
        if isinstance(params_raw, list) and len(params_raw) >= params_count:
            for value in params_raw[:params_count]:
                module_params.extend(_encode_value(int(value), 4))
        else:
            param_names = _get_param_order(module, params_count)
            for param in param_names:
                param_val = module.get("parameters", {}).get(param)
                if param_val is None:
                    module_params.extend(_encode_value(0, 4))
                else:
                    module_params.extend(_encode_value(int(round(param_val * 65535, 0)), 4))
            for _ in range(params_count - len(param_names)):
                module_params.extend(_encode_value(0, 4))

        module_saved_data = _get_saved_data_bytes(module, params_count)

        module_name = _encode_text(module.get("name", ""), 16)

        module_array.extend(module_size)
        module_array.extend(module_type)
        module_array.extend(module_version)
        module_array.extend(module_page)
        module_array.extend(module_color)
        module_array.extend(module_position)
        module_array.extend(module_params_count)
        module_array.extend(module_size_bytes)
        module_array.extend(module_options)
        module_array.extend(module_params)
        module_array.extend(module_saved_data)
        module_array.extend(module_name)

        modules_array.extend(module_array)

    connections_array = bytearray()
    connections_array.extend(_encode_value(pch["meta"]["n_connections"], 4))

    for module, color_id in _iter_colors(pch):
        if isinstance(color_id, str):
            color_value = COLOR_NAME_TO_ID.get(color_id, 1)
        else:
            color_value = color_id
        colors_array.extend(_encode_value(color_value, 4))

    for conn in pch["connections"]:
        connection_array = bytearray()
        if "strength_raw" in conn:
            src_mod = conn.get("source_raw", 0)
            src_blk = conn.get("source_block_raw", 0)
            dst_mod = conn.get("dest_raw", 0)
            dst_blk = conn.get("dest_block_raw", 0)
            strength = conn.get("strength_raw", 0)
        else:
            src = conn["source"].split(".")
            dst = conn["destination"].split(".")
            src_mod, src_blk = int(src[0]), int(src[1])
            dst_mod, dst_blk = int(dst[0]), int(dst[1])
            strength = int(round(conn["strength"] * 100, 0))

        connection_array.extend(_encode_value(int(src_mod), 4))
        connection_array.extend(_encode_value(int(src_blk), 4))
        connection_array.extend(_encode_value(int(dst_mod), 4))
        connection_array.extend(_encode_value(int(dst_blk), 4))
        connection_array.extend(_encode_value(int(strength), 4))
        connections_array.extend(connection_array)

    pages_array = bytearray()
    pages_count = pch.get("pages_count", pch["meta"]["n_pages"])
    pages_array.extend(_encode_value(pages_count, 4))
    for page in pch["pages"][:pages_count]:
        pages_array.extend(_encode_text(page, 16))

    starred_array = bytearray()
    starred_array.extend(_encode_value(pch["meta"]["n_starred"], 4))
    for sp in pch.get("starred", []):
        starred_array.extend(_encode_value(sp["module"], 2))
        if sp.get("midi_cc") == "None" or sp.get("midi_cc") is None:
            starred_array.extend(_encode_value(sp["block"], 2))
        else:
            cc = 128 * (sp["midi_cc"] + 1) + sp["block"]
            starred_array.extend(_encode_value(cc, 2))

    farray.extend(patch_name)
    farray.extend(module_count)
    farray.extend(modules_array)
    farray.extend(connections_array)
    farray.extend(pages_array)
    farray.extend(starred_array)
    farray.extend(colors_array)

    patch_size_array = _encode_value(int(len(farray) / 4 + 1), 4)
    file_array.extend(patch_size_array)
    file_array.extend(farray)

    padding_length = 32764 - len(farray)
    if padding_length > 0:
        file_array.extend(bytearray(b"\x00" * padding_length))

    if output_path:
        with open(output_path, "w+b") as f:
            f.write(file_array)

    return file_array


def _get_options_bytes(module):
    options_binary = module.get("options_binary", {})
    if isinstance(options_binary, (list, tuple)):
        return list(options_binary)[:8]

    mod_idx = str(module.get("mod_idx", 0))
    try:
        options_def = MODULE_INDEX[mod_idx]["options"]
    except (KeyError, TypeError):
        options_def = None

    if isinstance(options_def, dict):
        options_order = list(options_def)
    elif isinstance(options_def, list):
        options_order = options_def
    else:
        options_order = list(options_binary)

    return [options_binary.get(opt, 0) for opt in options_order][:8]


def _get_param_order(module, params_count=None):
    mod_idx = module.get("mod_idx")
    try:
        defaults = MODULE_INDEX[str(mod_idx)].get("param_defaults", {})
    except (KeyError, TypeError):
        defaults = {}

    if isinstance(defaults, dict) and defaults:
        items = list(defaults.items())
        if any(isinstance(meta, dict) and "order" in meta for _, meta in items):
            items.sort(
                key=lambda item: item[1].get("order", 0) if isinstance(item[1], dict) else 0
            )
        ordered = [name for name, _ in items]

        blocks = module.get("blocks", {})
        if isinstance(blocks, dict) and blocks:
            ordered = [name for name in ordered if blocks.get(name, {}).get("isParam")]
        return ordered[:params_count] if params_count is not None else ordered

    blocks = module.get("blocks", {})
    if isinstance(blocks, dict):
        params = [(name, meta) for name, meta in blocks.items() if meta.get("isParam")]
        if not params:
            return []
        params.sort(key=lambda item: item[1].get("position", 0))
        return [name for name, _ in params][:params_count]

    params = list(module.get("parameters", {}).keys())
    return params[:params_count] if params_count is not None else params


def _get_saved_data_bytes(module, params_count):
    size_words = module.get("size", 0)
    if not size_words:
        return bytearray()

    data_words = size_words - 4 - 10 - params_count
    if data_words <= 0:
        return bytearray()

    expected_len = data_words * 4
    saved_data = module.get("saved_data", [])
    raw = bytearray(saved_data) if saved_data else bytearray()

    if len(raw) < expected_len:
        raw.extend(b"\x00" * (expected_len - len(raw)))
    elif len(raw) > expected_len:
        raw = raw[:expected_len]

    return raw


def _iter_colors(pch):
    colors = pch.get("colors", [])
    modules = pch.get("modules", [])
    if len(colors) == len(modules):
        for module, color_id in zip(modules, colors):
            yield module, color_id
        return
    for module in modules:
        yield module, module.get("color", "Blue")


def _encode_text(text, byte_array_length):
    if text is None:
        text = ""
    if len(text) > byte_array_length:
        text = text[:byte_array_length]
    format_string = "{}B{}x".format(len(text), byte_array_length - len(text))
    data = list(text.encode())
    return bytearray(struct.pack(format_string, *data))


def _encode_value(value, byte_array_length):
    if value == 0:
        value_bytes = 2
    else:
        value_bytes = int(math.ceil(math.log(max(value, 1), 2)) / 8)

    if value_bytes > 8:
        raise ValueError(f"Value {value} too large to encode")
    elif value_bytes > 4:
        byte_array_format = "Q"
        used_bytes = 8
    elif value_bytes > 2:
        byte_array_format = "I"
        used_bytes = 4
    else:
        byte_array_format = "H"
        used_bytes = 2

    format_string = "<{}{}x".format(byte_array_format, byte_array_length - used_bytes)
    return bytearray(struct.pack(format_string, value))


def _encode_byte(byte_val, byte_array_length):
    format_string = "B{}x".format(byte_array_length - 1)
    return bytearray(struct.pack(format_string, byte_val))
