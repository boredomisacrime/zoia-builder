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

# ---------------------------------------------------------------------------
# Option → Block activation rules
#
# The ZOIA firmware uses module options to determine how many blocks (params,
# I/O jacks) a module has.  If the binary says "record = new_sample" but
# doesn't include the audio_in and record blocks, the firmware reads garbage.
#
# Two rule formats per option:
#   list  → "any nonzero value activates these blocks"
#   dict  → {value_index: [blocks], ...}  for value-specific activation
# ---------------------------------------------------------------------------

_OPTION_BLOCK_RULES = {
    # [0] SV Filter
    0: {
        "hipass_output": {1: ["hipass_output"]},
        "bandpass_output": {1: ["bandpass_output"]},
    },
    # [2] Audio Output
    2: {
        "gain_control": ["gain"],
    },
    # [4] Sequencer (count rules handle steps/tracks; toggles here)
    4: {
        "restart_jack": ["queue_start"],
        "key_input": ["key_input_note", "key_input_gate"],
    },
    # [5] LFO
    5: {
        "input": {1: ["tap_control"], 2: ["tap_control"]},
        "swing_control": ["swing_amount"],
        "phase_input": ["phase_input"],
        "phase_reset": ["phase_reset"],
    },
    # [6] ADSR
    6: {
        "retrigger_input": ["retrigger"],
        "initial_delay": ["delay"],
        "hold_attack_decay": ["hold_attack_decay"],
        "hold_sustain_release": ["hold_sustain_release"],
    },
    # [7] VCA
    7: {
        "channels": {1: ["audio_in_2", "audio_out_2"]},
    },
    # [12] Env Follower
    12: {
        "rise_fall_time": ["rise_time", "fall_time"],
    },
    # [13] Delay Line
    13: {
        "tap_tempo_in": ["modulation_in", "tap_tempo_in"],
    },
    # [14] Oscillator
    14: {
        "fm_in": ["fm_input"],
        "duty_cycle": ["duty_cycle"],
    },
    # [19] Slew Limiter
    19: {
        "control": {1: ["rising_lag", "falling_lag"]},
    },
    # [23] Compressor
    23: {
        "attack_ctrl": ["attack"],
        "release_ctrl": ["release"],
        "ratio_ctrl": ["ratio"],
        "channels": {1: ["audio_in_R", "audio_out_R"]},
        "sidechain": {1: ["sidechain_in"]},
    },
    # [24] Multi Filter — shelf/bell shapes need the gain block
    24: {
        "filter_shape": {1: ["gain"], 2: ["gain"], 4: ["gain"]},
    },
    # [28] Quantizer
    28: {
        "key_scale_jacks": ["key", "scale"],
    },
    # [29] Phaser
    29: {
        "channels": {1: ["audio_out_R"], 2: ["audio_in_R", "audio_out_R"]},
        "control": {1: ["tap_tempo_in"], 2: ["control_in"]},
    },
    # [30] Looper
    30: {
        "length_edit": ["start_position", "loop_length"],
        "play_reverse": ["reverse_playback"],
        "overdub": ["reset"],
        "stop_play_button": ["stop_play"],
    },
    # [36] Onset Detector
    36: {
        "sensitivity": ["sensitivity"],
    },
    # [37] Rhythm
    37: {
        "done_ctrl": ["done_out"],
    },
    # [39] Random
    39: {
        "new_val_on_trig": ["trigger_in"],
    },
    # [40] Gate
    40: {
        "attack_ctrl": ["attack"],
        "release_ctrl": ["release"],
        "channels": {1: ["audio_in_R", "audio_out_R"]},
        "sidechain": {1: ["sidechain_in"]},
    },
    # [41] Tremolo
    41: {
        "channels": {1: ["audio_out_R"], 2: ["audio_in_R", "audio_out_R"]},
        "control": {1: ["tap_tempo_in"], 2: ["direct"]},
    },
    # [42] Tone Control
    42: {
        "channels": {1: ["audio_in_R", "audio_out_R"]},
        "num_mid_bands": {1: ["mid_gain_2", "mid_freq_2"]},
    },
    # [43] Delay w/Mod
    43: {
        "channels": {1: ["audio_out_R"], 2: ["audio_in_R", "audio_out_R"]},
        "control": {1: ["tap_tempo_in"]},
    },
    # [47] CV Loop
    47: {
        "length_edit": ["start_position", "stop_position"],
    },
    # [48] CV Filter
    48: {
        "control": {1: ["rise_constant", "fall_constant"]},
    },
    # [49] Clock Divider
    49: {
        "input": {1: ["modifier"]},
    },
    # [53] Stereo Spread
    53: {
        "method": {1: ["audio_in_2", "side_gain"]},
    },
    # [56] UI Button
    56: {
        "cv_output": ["cv_output"],
    },
    # [57] Audio Panner
    57: {
        "channels": {1: ["audio_in_R"]},
    },
    # [60] Midi Note Out
    60: {
        "velocity_output": ["velocity_out"],
    },
    # [64] Audio Balance
    64: {
        "stereo": {1: ["audio_in_1_R", "audio_in_2_R", "audio_output_R"]},
    },
    # [67] Ghostverb
    67: {
        "channels": {1: ["audio_out_R"], 2: ["audio_in_R", "audio_out_R"]},
    },
    # [68] Cabinet Sim
    68: {
        "channels": {1: ["audio_in_R", "audio_out_R"]},
    },
    # [69] Flanger
    69: {
        "channels": {1: ["audio_out_R"], 2: ["audio_in_R", "audio_out_R"]},
        "control": {1: ["tap_tempo_in"], 2: ["direct"]},
    },
    # [70] Chorus
    70: {
        "channels": {1: ["audio_out_R"], 2: ["audio_in_R", "audio_out_R"]},
        "control": {1: ["tap_tempo_in"], 2: ["direct"]},
    },
    # [71] Vibrato
    71: {
        "channels": {1: ["audio_out_R"], 2: ["audio_in_R", "audio_out_R"]},
        "control": {1: ["tap_tempo_in"], 2: ["direct"]},
    },
    # [72] Env Filter
    72: {
        "channels": {1: ["audio_out_R"], 2: ["audio_in_R", "audio_out_R"]},
    },
    # [73] Ring Modulator
    73: {
        "ext_audio_in": ["ext_in"],
        "duty_cycle": ["duty_cycle"],
    },
    # [75] Ping Pong Delay
    75: {
        "channels": {1: ["audio_in_R"]},
        "control": {1: ["tap_tempo_in"]},
    },
    # [79] Reverb Lite
    79: {
        "channels": {1: ["audio_out_R"], 2: ["audio_in_R", "audio_out_R"]},
    },
    # [81] Pixel
    81: {
        "control": {1: ["audio_in"]},
    },
    # [82] Midi Clock In
    82: {
        "clock_out": ["clock_out"],
        "run_out": ["run_out"],
        "divider": ["reset_out"],
    },
    # [83] Granular
    83: {
        "channels": {1: ["audio_in_R", "audio_out_R"]},
    },
    # [84] Midi Clock Out
    84: {
        "position": ["send_position", "song_position"],
    },
    # [85] Tap to CV
    85: {
        "range": ["min_time", "max_time"],
    },
    # [102] Sampler
    102: {
        "record": ["audio_in_L", "audio_in_R", "record"],
        "reverse_button": ["direction"],
        "cv_outputs": ["position_cv_out", "loop_end_cv_out"],
    },
    # [103] Device Control
    103: {
        "control": {1: ["aux"], 2: ["aux", "performance"]},
    },
    # [106] Reverse Delay
    106: {
        "channels": {1: ["audio_in_R", "audio_out_R"]},
        "control": {1: ["tap_tempo_in", "tap_ratio"]},
    },
    # [107] Univibe
    107: {
        "channels": {1: ["audio_out_R"], 2: ["audio_in_R", "audio_out_R"]},
        "control": {1: ["tap_tempo_in"], 2: ["direct"]},
    },
}

# Count-based rules: (first_option_value, default_count, [[blocks_per_increment]])
# n_extra = max(0, option_index + first_value - default_count)
# activated = flatten(blocks_per_increment[:n_extra])

_OPTION_COUNT_RULES = {
    # [4] Sequencer
    4: {
        "number_of_steps": (1, 4, [[f"step_{i}"] for i in range(5, 33)]),
        "num_of_tracks": (1, 1, [[f"out_track_{i}"] for i in range(2, 9)]),
    },
    # [16] Keyboard
    16: {
        "#_of_notes": (1, 1, [[f"note_{i}"] for i in range(2, 41)]),
    },
    # [22] Multiplier
    22: {
        "num_inputs": (2, 2, [[f"cv_input_{i}"] for i in range(3, 9)]),
    },
    # [31] In Switch
    31: {
        "num_inputs": (1, 1, [[f"cv_input_{i}"] for i in range(2, 17)]),
    },
    # [32] Out Switch
    32: {
        "num_outputs": (1, 1, [[f"cv_output_{i}"] for i in range(2, 17)]),
    },
    # [33] Audio In Switch
    33: {
        "num_inputs": (1, 1, [[f"audio_input_{i}"] for i in range(2, 17)]),
    },
    # [34] Audio Out Switch
    34: {
        "num_outputs": (1, 1, [[f"audio_output_{i}"] for i in range(2, 17)]),
    },
    # [104] CV Mixer (each channel adds input + attenuation)
    104: {
        "num_channels": (1, 2, [[f"cv_in_{i}", f"atten_{i}"] for i in range(3, 9)]),
    },
    # [105] Logic Gate
    105: {
        "num_of_inputs": (2, 2, [[f"in_{i}"] for i in range(3, 39)]),
        "threshold": (0, 0, [["threshold"]]),
    },
}


def _get_option_implied_blocks(mod_id, options_binary):
    """Return the set of optional block names the firmware expects given these options."""
    implied = set()

    rules = _OPTION_BLOCK_RULES.get(mod_id, {})
    for opt_name, rule in rules.items():
        val = options_binary.get(opt_name, 0)
        if val == 0:
            continue
        if isinstance(rule, list):
            implied.update(rule)
        elif isinstance(rule, dict) and val in rule:
            implied.update(rule[val])

    for opt_name, (base, default_count, bpi) in _OPTION_COUNT_RULES.get(mod_id, {}).items():
        val = options_binary.get(opt_name, 0)
        n_extra = max(0, val + base - default_count)
        for i in range(min(n_extra, len(bpi))):
            implied.update(bpi[i])

    if mod_id == 76:
        implied.update(_audio_mixer_implied(options_binary))
    elif mod_id == 20:
        implied.update(_midi_notes_in_implied(options_binary))

    return implied


def _ensure_options_for_blocks(mod_id, options_binary, needed_blocks, blocks_def):
    """Adjust options so that every needed optional block is covered by firmware rules."""
    if not needed_blocks:
        return

    optional_needed = {b for b in needed_blocks
                       if b in blocks_def and not blocks_def[b].get("isDefault", False)}
    if not optional_needed:
        return

    rules = _OPTION_BLOCK_RULES.get(mod_id, {})
    for opt_name, rule in rules.items():
        if isinstance(rule, list):
            if optional_needed & set(rule):
                if options_binary.get(opt_name, 0) == 0:
                    options_binary[opt_name] = 1
        elif isinstance(rule, dict):
            for val in sorted(rule.keys()):
                if optional_needed & set(rule[val]):
                    if options_binary.get(opt_name, 0) < val:
                        options_binary[opt_name] = val

    for opt_name, (base, default_count, bpi) in _OPTION_COUNT_RULES.get(mod_id, {}).items():
        max_inc = 0
        for i, inc_blocks in enumerate(bpi):
            if optional_needed & set(inc_blocks):
                max_inc = i + 1
        if max_inc > 0:
            needed_idx = max_inc + default_count - base
            if options_binary.get(opt_name, 0) < needed_idx:
                options_binary[opt_name] = needed_idx

    if mod_id == 76:
        _audio_mixer_ensure_opts(options_binary, optional_needed)
    elif mod_id == 20:
        _midi_notes_in_ensure_opts(options_binary, optional_needed)


def _audio_mixer_implied(opts):
    """Audio Mixer (76): channels × stereo × panning interaction."""
    n_chan = opts.get("channels", 0) + 2
    is_stereo = opts.get("stereo", 0) != 0
    has_pan = opts.get("panning", 0) != 0
    blocks = set()
    for ch in range(3, n_chan + 1):
        blocks.add(f"audio_in_{ch}_L")
        if is_stereo:
            blocks.add(f"audio_in_{ch}_R")
        blocks.add(f"gain_{ch}")
    if is_stereo:
        blocks.add("audio_in_1_R")
        blocks.add("audio_in_2_R")
        blocks.add("audio_out_R")
    if has_pan:
        for ch in range(1, n_chan + 1):
            blocks.add(f"pan_{ch}")
    return blocks


def _audio_mixer_ensure_opts(opts, needed):
    max_ch = 2
    for b in needed:
        for ch in range(3, 9):
            if f"_{ch}_" in b or b.endswith(f"_{ch}"):
                max_ch = max(max_ch, ch)
    if max_ch > 2:
        opts["channels"] = max(opts.get("channels", 0), max_ch - 2)
    if any("_R" in b for b in needed):
        opts["stereo"] = max(opts.get("stereo", 0), 1)
    if any(b.startswith("pan_") for b in needed):
        opts["panning"] = max(opts.get("panning", 0), 1)


def _midi_notes_in_implied(opts):
    """Midi Notes In (20): #_of_outputs × velocity × trigger interaction."""
    n_out = opts.get("#_of_outputs", 0) + 1
    has_vel = opts.get("velocity_output", 0) != 0
    has_trig = opts.get("trigger_pulse", 0) != 0
    blocks = set()
    if has_vel:
        blocks.add("velocity_out_1")
    if has_trig:
        blocks.add("trigger_out_1")
    for o in range(2, n_out + 1):
        blocks.add(f"note_out_{o}")
        blocks.add(f"gate_out_{o}")
        if has_vel:
            blocks.add(f"velocity_out_{o}")
        if has_trig:
            blocks.add(f"trigger_out_{o}")
    return blocks


def _midi_notes_in_ensure_opts(opts, needed):
    max_out = 1
    for b in needed:
        for o in range(2, 9):
            if b.endswith(f"_{o}"):
                max_out = max(max_out, o)
    if max_out > 1:
        opts["#_of_outputs"] = max(opts.get("#_of_outputs", 0), max_out - 1)
    if any("velocity" in b for b in needed):
        opts["velocity_output"] = max(opts.get("velocity_output", 0), 1)
    if any("trigger" in b for b in needed):
        opts["trigger_pulse"] = max(opts.get("trigger_pulse", 0), 1)


# ---------------------------------------------------------------------------
# Module classification for validation
# ---------------------------------------------------------------------------

# Modules whose outputs are CV/trigger — never audio.
# Some (Env Follower, Onset Detector, Pitch Detector) accept audio IN but
# still output CV, so they're dead-ends in the audio graph.
_CV_ONLY_MODULE_NAMES = {
    "LFO", "ADSR", "Env Follower", "Sample and Hold", "Slew Limiter",
    "Multiplier", "Quantizer", "Onset Detector", "Rhythm", "Random",
    "Stompswitch", "Value", "CV Invert", "CV Filter", "Clock Divider",
    "Comparator", "CV Rectify", "UI Button", "Pushbutton", "Trigger",
    "Pitch Detector", "Tap to CV", "CV Delay", "CV Loop", "CV Flip Flop",
    "CV Mixer", "Logic Gate", "Steps", "Keyboard", "Sequencer", "Pixel",
    "Cport Exp/CV In", "Cport CV Out", "Expression",
    "Midi Notes In", "Midi Note Out", "Midi CC In", "Midi CC Out",
    "Midi PC Out", "Midi Clock In", "Midi Clock Out", "Midi Pitch Bend",
    "Midi Pressure", "Device Control",
}
_CV_ONLY_IDS = {_NAME_TO_ID[n] for n in _CV_ONLY_MODULE_NAMES if n in _NAME_TO_ID}

# Modules that capture audio then play it back — they do NOT pass live audio.
_CAPTURE_PLAY_NAMES = {"Sampler", "Looper"}
_CAPTURE_PLAY_IDS = {_NAME_TO_ID[n] for n in _CAPTURE_PLAY_NAMES if n in _NAME_TO_ID}

# Audio-input block name patterns (for detecting CV→audio misconnections)
_AUDIO_IN_PATTERNS = (
    "audio_in", "input_L", "input_R", "audio_input", "ext_in",
    "sidechain_in",
)


class BuildError(Exception):
    pass


def validate_patch(encoder_dict):
    """
    Check a built patch for issues that would cause silence or noise.
    Returns a list of human-readable issue strings (empty = patch is valid).
    """
    from collections import deque

    issues = []
    modules = encoder_dict["modules"]
    connections = encoder_dict["connections"]

    if not modules:
        return ["No modules in patch."]

    # Locate Audio Input / Output
    audio_in_idx = next(
        (i for i, m in enumerate(modules) if m["mod_idx"] == 1), None
    )
    audio_out_idx = next(
        (i for i, m in enumerate(modules) if m["mod_idx"] == 2), None
    )

    if audio_in_idx is None:
        issues.append("No Audio Input module — the patch cannot receive any signal.")
        return issues
    if audio_out_idx is None:
        issues.append("No Audio Output module — the patch cannot produce any sound.")
        return issues

    # --- Build audio-only adjacency graph ---
    # A connection is "audio" if:
    #   1. Source module is NOT a CV-only type
    #   2. Destination block is NOT a parameter
    audio_adj = {}
    _block_name_cache = {}

    def _dst_block_info(mod_idx, block_pos):
        key = (mod_idx, block_pos)
        if key not in _block_name_cache:
            for bname, binfo in modules[mod_idx]["blocks"].items():
                if binfo["position"] == block_pos:
                    _block_name_cache[key] = (bname, binfo.get("isParam", False))
                    break
            else:
                _block_name_cache[key] = (f"?pos{block_pos}", False)
        return _block_name_cache[key]

    for conn in connections:
        src_mod = conn["source_raw"]
        dst_mod = conn["dest_raw"]
        src_is_cv = modules[src_mod]["mod_idx"] in _CV_ONLY_IDS
        dst_bname, dst_is_param = _dst_block_info(dst_mod, conn["dest_block_raw"])

        # Flag CV→audio misconnections
        if src_is_cv and not dst_is_param:
            if any(dst_bname.startswith(p) for p in _AUDIO_IN_PATTERNS):
                src_type = modules[src_mod].get("type", "?")
                dst_type = modules[dst_mod].get("type", "?")
                issues.append(
                    f"CV→AUDIO: {src_type} output is connected to "
                    f"{dst_type}.{dst_bname}. CV signals in audio inputs "
                    f"create noise. Connect CV to parameter blocks instead."
                )

        # Only add to audio graph if it's an audio connection
        if not src_is_cv and not dst_is_param:
            audio_adj.setdefault(src_mod, []).append(dst_mod)

    # --- BFS: can audio reach Output from Input? ---
    visited = set()
    parent = {audio_in_idx: None}
    queue = deque([audio_in_idx])
    visited.add(audio_in_idx)

    while queue:
        current = queue.popleft()
        for neighbor in audio_adj.get(current, []):
            if neighbor not in visited:
                visited.add(neighbor)
                parent[neighbor] = current
                queue.append(neighbor)

    if audio_out_idx not in visited:
        # Find which modules ARE reachable to give a useful diagnostic
        reached = [modules[m].get("type", "?") for m in sorted(visited)]
        issues.append(
            "NO AUDIO PATH: Sound cannot travel from Audio Input to "
            "Audio Output. The patch will be completely silent. "
            "Every effect module in the chain needs both its audio input "
            "AND audio output connected. "
            f"Audio Input can reach: {', '.join(reached)}"
        )
    else:
        # Path exists — reconstruct and check for capture-and-play modules
        path = []
        node = audio_out_idx
        while node is not None:
            path.append(node)
            node = parent.get(node)
        path.reverse()

        for mod_idx in path:
            if modules[mod_idx]["mod_idx"] in _CAPTURE_PLAY_IDS:
                mod_type = modules[mod_idx].get("type", "?")
                issues.append(
                    f"CAPTURE MODULE: {mod_type} is in the live audio chain "
                    f"but does NOT pass audio through — it records first, "
                    f"then plays back on command. This breaks the signal flow. "
                    f"Use a pass-through effect instead (Delay Line, Reverb, "
                    f"Granular, Chorus, etc.)."
                )

    # --- VCA level check ---
    for i, mod in enumerate(modules):
        if mod["mod_idx"] == 7:  # VCA
            lc = mod["parameters"].get("level_control", 0.5)
            if lc < 0.01:
                issues.append(
                    f"MUTED VCA: VCA has level_control={lc:.3f}, which mutes "
                    f"all audio through it. Set to at least 0.5."
                )

    # --- Audio Output must have incoming connection ---
    has_ao_input = any(c["dest_raw"] == audio_out_idx for c in connections)
    if not has_ao_input:
        issues.append(
            "Audio Output has no incoming connections — nothing will be heard."
        )

    # --- Check connection strength ---
    for ci, conn in enumerate(connections):
        if conn["strength_raw"] < 100:
            src_type = modules[conn["source_raw"]].get("type", "?")
            dst_type = modules[conn["dest_raw"]].get("type", "?")
            dst_bname, _ = _dst_block_info(conn["dest_raw"], conn["dest_block_raw"])
            issues.append(
                f"WEAK CONNECTION: {src_type}→{dst_type}.{dst_bname} "
                f"strength is {conn['strength_raw']} (scale 0-10000). "
                f"This is less than 1% and may cause silence."
            )

    return issues


def ensure_minimum_audio_path(encoder_dict):
    """
    If the graph has no route from Audio Input to Audio Output, append a direct
    output_L → input_L connection at full strength so the patch is not completely
    silent. The AI often wires modulation or breaks the chain between effects.

    Returns (encoder_dict, list of human-readable fix notes).
    """
    issues = validate_patch(encoder_dict)
    need_fix = any(
        "NO AUDIO PATH" in msg or "Audio Output has no incoming" in msg
        for msg in issues
    )
    if not need_fix:
        return encoder_dict, []

    modules = encoder_dict["modules"]
    fixes = []

    ai_idx = next((i for i, m in enumerate(modules) if m["mod_idx"] == 1), None)
    ao_idx = next((i for i, m in enumerate(modules) if m["mod_idx"] == 2), None)
    if ai_idx is None or ao_idx is None:
        return encoder_dict, fixes

    def _block_pos(mod_i, bname):
        blk = modules[mod_i]["blocks"].get(bname)
        if blk is None:
            raise KeyError(bname)
        return blk["position"]

    try:
        src_blk = _block_pos(ai_idx, "output_L")
        dst_blk = _block_pos(ao_idx, "input_L")
    except KeyError:
        fixes.append(
            "Could not add emergency passthrough: missing output_L or input_L blocks."
        )
        return encoder_dict, fixes

    key = (ai_idx, src_blk, ao_idx, dst_blk)
    existing = {
        (c["source_raw"], c["source_block_raw"], c["dest_raw"], c["dest_block_raw"])
        for c in encoder_dict["connections"]
    }
    if key in existing:
        return encoder_dict, fixes

    encoder_dict["connections"].append({
        "source_raw": ai_idx,
        "source_block_raw": src_blk,
        "dest_raw": ao_idx,
        "dest_block_raw": dst_blk,
        "strength_raw": 10000,
    })
    encoder_dict["meta"]["n_connections"] = len(encoder_dict["connections"])
    fixes.append(
        "AUTO-FIX: Added Audio Input.output_L → Audio Output.input_L so the patch "
        "is not silent (the AI had no complete audio path). You may hear dry signal "
        "alongside effects — adjust or remove this connection in ZOIA if needed."
    )
    return encoder_dict, fixes


def ensure_dry_parallel_delay_line(encoder_dict):
    """
    The Delay Line module has NO dry signal and NO mix control (see ZOIA docs).
    Input → Delay Line → Output gives *only* delayed audio; at some settings that can
    be inaudible or unlike what players expect. Bypass still passes dry signal, so
    engaged vs bypass sounds broken.

    If the patch contains Delay Line (mod 13) and there is no direct
    Audio Input → Audio Output connection, add output_L → input_L in parallel.
    """
    modules = encoder_dict["modules"]
    fixes = []

    if not any(m["mod_idx"] == 13 for m in modules):
        return encoder_dict, fixes

    ai_idx = next((i for i, m in enumerate(modules) if m["mod_idx"] == 1), None)
    ao_idx = next((i for i, m in enumerate(modules) if m["mod_idx"] == 2), None)
    if ai_idx is None or ao_idx is None:
        return encoder_dict, fixes

    def has_direct_io():
        for c in encoder_dict["connections"]:
            if c["source_raw"] == ai_idx and c["dest_raw"] == ao_idx:
                return True
        return False

    if has_direct_io():
        return encoder_dict, fixes

    try:
        src_blk = modules[ai_idx]["blocks"]["output_L"]["position"]
        dst_blk = modules[ao_idx]["blocks"]["input_L"]["position"]
    except KeyError:
        return encoder_dict, fixes

    key = (ai_idx, src_blk, ao_idx, dst_blk)
    existing = {
        (c["source_raw"], c["source_block_raw"], c["dest_raw"], c["dest_block_raw"])
        for c in encoder_dict["connections"]
    }
    if key in existing:
        return encoder_dict, fixes

    encoder_dict["connections"].append({
        "source_raw": ai_idx,
        "source_block_raw": src_blk,
        "dest_raw": ao_idx,
        "dest_block_raw": dst_blk,
        "strength_raw": 10000,
    })
    encoder_dict["meta"]["n_connections"] = len(encoder_dict["connections"])
    fixes.append(
        "AUTO-FIX: Delay Line has no dry/mix — added Audio Input.output_L → "
        "Audio Output.input_L in parallel (dry + delayed). Prefer Delay w/Mod or "
        "Ping Pong Delay for a built-in mix knob."
    )
    return encoder_dict, fixes


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

        ai_params = ai_mod.get("parameters", {})

        # --- Option ↔ Block synchronisation ---
        # The ZOIA firmware uses option bytes to decide how many blocks a
        # module has.  We must ensure the blocks we encode match exactly
        # what the firmware will expect.
        #
        # 1. Default blocks — always active
        # 2. AI-referenced optional blocks (params & connections)
        # 3. REVERSE: set options that accommodate the AI-referenced blocks
        # 4. FORWARD: activate all blocks that the options now imply
        # 5. Union = complete, consistent block set

        default_names = {
            bname for bname, binfo in blocks_def.items()
            if binfo.get("isDefault", False)
        }

        ai_referenced = set()
        for bname in blocks_def:
            if bname not in default_names:
                if bname in ai_params or bname in connected_blocks:
                    ai_referenced.add(bname)

        options_binary = _resolve_options(mod_def, ai_mod.get("options", {}))

        # Mono guitar + wrong L/R I/O option = silence when the patch is engaged.
        # Stereo keeps both physical outputs fed from the L chain (typical mono rig).
        if mod_id in (1, 2) and isinstance(options_binary, dict):
            options_binary["channels"] = 0  # stereo

        _ensure_options_for_blocks(mod_id, options_binary, ai_referenced, blocks_def)

        option_implied = _get_option_implied_blocks(mod_id, options_binary)
        # Only include option-implied blocks that actually exist in the module
        option_implied &= set(blocks_def.keys())

        active_names = default_names | ai_referenced | option_implied

        # Use CANONICAL block positions from ModuleIndex (not sequential re-indexing).
        # ZOIA firmware addresses blocks by their canonical position numbers
        # (e.g. Delay w/Mod: audio_in_L=0, delay_time=2, …, audio_out_L=8).
        # Sequential re-indexing (0,1,2,…) caused connections to land on the wrong
        # blocks — e.g. audio_out_L (canonical 8) written as 6 → ZOIA reads mod_depth.
        active_blocks = {}
        block_count = 0
        for bname, binfo in sorted(blocks_def.items(), key=lambda x: x[1].get("position", 0)):
            if bname in active_names:
                active_blocks[bname] = {
                    "position": binfo.get("position", block_count),  # canonical
                    "isParam": binfo.get("isParam", False),
                    "isDefault": binfo.get("isDefault", False),
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
            "version": mod_def.get("version", 0),
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
            "strength_raw": ai_conn.get("strength", 100) * 100,
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

    encoder_dict = {
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

    audio_fixes = []
    encoder_dict, f1 = ensure_minimum_audio_path(encoder_dict)
    audio_fixes.extend(f1)
    encoder_dict, f2 = ensure_dry_parallel_delay_line(encoder_dict)
    audio_fixes.extend(f2)
    if audio_fixes:
        encoder_dict["_audio_path_auto_fixes"] = audio_fixes

    return encoder_dict


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
