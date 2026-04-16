"""
Harness: feed a handful of known-complex patch specs through build_patch
and confirm the encoder produces a sane binary. Also verify the
normalisation layer rescues common AI mistakes.

Run from the zoia-builder directory:
    python -m tests.test_builder_complex
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from patch_builder import build_patch, validate_patch, BuildError  # noqa: E402
from patch_encoder import encode_patch  # noqa: E402


# --- Test specs --------------------------------------------------------------

SPECS = [
    {
        "name": "minimal",
        "desc": "Simplest possible patch the encoder should never choke on.",
        "ai_json": {
            "name": "Clean",
            "pages": ["Main"],
            "modules": [
                {"type": "Audio Input", "page": 0, "position": 0},
                {"type": "Audio Output", "page": 0, "position": 38},
            ],
            "connections": [
                {"from": "Audio Input.output_L", "to": "Audio Output.input_L", "strength": 100},
            ],
        },
        "expect_issues": 0,
    },
    {
        "name": "loop-forest",
        "desc": "Three series delays blended into a mixer with reverb — classic post-rock bed.",
        "ai_json": {
            "name": "Forest",
            "modules": [
                {"type": "Delay w/Mod", "page": 0, "position": 0,
                 "parameters": {"delay_time": 0.3, "feedback": 0.55, "mix": 0.6, "mod_rate": 0.2, "mod_depth": 0.25}},
                {"type": "Delay w/Mod", "page": 0, "position": 10,
                 "parameters": {"delay_time": 0.55, "feedback": 0.5, "mix": 0.55}},
                {"type": "Delay w/Mod", "page": 0, "position": 20,
                 "parameters": {"delay_time": 0.75, "feedback": 0.45, "mix": 0.5}},
                {"type": "Reverb Lite", "page": 0, "position": 30,
                 "parameters": {"decay_time": 0.85, "mix": 0.55}},
                {"type": "Audio Mixer", "page": 1, "position": 0,
                 "options": {"channels": 4, "stereo": "mono", "panning": "off"},
                 "parameters": {"gain_1": 0.7, "gain_2": 0.7, "gain_3": 0.7, "gain_4": 0.7}},
                {"type": "LFO", "page": 1, "position": 20, "parameters": {"cv_control": 0.15}},
                {"type": "LFO", "page": 1, "position": 25, "parameters": {"cv_control": 0.22}},
                {"type": "Stompswitch", "page": 1, "position": 30,
                 "options": {"stompswitch": "left", "action": "momentary"}},
            ],
            "connections": [
                {"from": "Audio Input.output_L", "to": "Audio Mixer.audio_in_1_L", "strength": 80},
                {"from": "Audio Input.output_L", "to": "Delay w/Mod#0.audio_in_L", "strength": 100},
                {"from": "Delay w/Mod#0.audio_out_L", "to": "Delay w/Mod#1.audio_in_L", "strength": 90},
                {"from": "Delay w/Mod#1.audio_out_L", "to": "Delay w/Mod#2.audio_in_L", "strength": 90},
                {"from": "Delay w/Mod#0.audio_out_L", "to": "Audio Mixer.audio_in_2_L", "strength": 80},
                {"from": "Delay w/Mod#1.audio_out_L", "to": "Audio Mixer.audio_in_3_L", "strength": 80},
                {"from": "Delay w/Mod#2.audio_out_L", "to": "Audio Mixer.audio_in_4_L", "strength": 80},
                {"from": "Audio Mixer.audio_out_L", "to": "Reverb Lite.audio_in_L", "strength": 100},
                {"from": "Reverb Lite.audio_out_L", "to": "Audio Output.input_L", "strength": 100},
                {"from": "LFO#0.output", "to": "Delay w/Mod#0.delay_time", "strength": 25},
                {"from": "LFO#1.output", "to": "Delay w/Mod#1.delay_time", "strength": 25},
                {"from": "Stompswitch.cv_output", "to": "Delay w/Mod#0.feedback", "strength": 40},
                {"from": "Stompswitch.cv_output", "to": "Delay w/Mod#1.feedback", "strength": 40},
                {"from": "Stompswitch.cv_output", "to": "Delay w/Mod#2.feedback", "strength": 40},
            ],
        },
        "expect_issues": 0,
    },
    {
        "name": "messy-aliases",
        "desc": "Lowercased module types, loose block names, no IO modules, float strengths.",
        "ai_json": {
            "name": "Messy",
            "modules": [
                {"type": "plate reverb", "page": 0, "position": 5},
                {"type": "LFO", "page": 0},
                {"type": "LFO", "page": 0},
                {"type": "SH", "page": 0},
                {"type": "stomp", "page": 0},
            ],
            "connections": [
                {"from": "Audio Input.out", "to": "plate reverb.audio_in", "strength": 0.9},
                {"from": "plate reverb.audio_out", "to": "Audio Output.input", "strength": 1},
                {"from": "LFO.output", "to": "plate reverb.decay", "strength": 30},
                {"from": "LFO#1.out", "to": "plate reverb.mix", "strength": 0.2},
                {"from": "SH.cv_output", "to": "plate reverb.high_eq", "strength": 40},
                {"from": "stomp.cv_output", "to": "SH.trigger", "strength": 100},
            ],
        },
        "expect_issues": 0,
    },
    {
        "name": "arp-tuning-aware",
        "desc": "Sequencer-driven arpeggiator paralleled with live guitar — tuning-aware scaffold.",
        "ai_json": {
            "name": "Arpeggio",
            "modules": [
                {"type": "Sequencer", "page": 0, "position": 0,
                 "options": {"number_of_steps": 8, "num_of_tracks": 1, "behavior": "loop"},
                 "parameters": {"step_1": 0.0, "step_2": 0.083, "step_3": 0.167,
                                "step_4": 0.25, "step_5": 0.333, "step_6": 0.417,
                                "step_7": 0.5, "step_8": 0.583}},
                {"type": "LFO", "page": 0, "position": 20,
                 "parameters": {"cv_control": 0.6}},
                {"type": "Oscillator", "page": 1, "position": 0,
                 "options": {"waveform": "triangle"}},
                {"type": "Audio Mixer", "page": 1, "position": 10,
                 "options": {"channels": 2, "stereo": "mono"}},
                {"type": "Reverb Lite", "page": 1, "position": 20},
            ],
            "connections": [
                {"from": "LFO.output", "to": "Sequencer.gate_in", "strength": 100},
                {"from": "Sequencer.out_track_1", "to": "Oscillator.frequency", "strength": 100},
                {"from": "Oscillator.audio_out", "to": "Audio Mixer.audio_in_1_L", "strength": 60},
                {"from": "Audio Input.output_L", "to": "Audio Mixer.audio_in_2_L", "strength": 100},
                {"from": "Audio Mixer.audio_out_L", "to": "Reverb Lite.audio_in_L", "strength": 100},
                {"from": "Reverb Lite.audio_out_L", "to": "Audio Output.input_L", "strength": 100},
            ],
        },
        "expect_issues": 0,
    },
    {
        "name": "stereo-shimmer",
        "desc": "Stereo shimmer with pitch shifter into reverb, pre and post blend.",
        "ai_json": {
            "name": "Shimmer",
            "modules": [
                {"type": "Pitch Shifter", "page": 0, "position": 0,
                 "parameters": {"pitch_shift": 0.875}},  # +12 semitones
                {"type": "Reverb Lite", "page": 0, "position": 10,
                 "options": {"channels": "stereo"},
                 "parameters": {"decay_time": 0.95, "mix": 0.7}},
                {"type": "Audio Mixer", "page": 0, "position": 20,
                 "options": {"channels": 3, "stereo": "stereo"},
                 "parameters": {"gain_1": 0.7, "gain_2": 0.5, "gain_3": 0.6}},
            ],
            "connections": [
                {"from": "Audio Input.output_L", "to": "Audio Mixer.audio_in_1_L", "strength": 100},
                {"from": "Audio Input.output_L", "to": "Pitch Shifter.audio_in", "strength": 100},
                {"from": "Pitch Shifter.audio_out", "to": "Reverb Lite.audio_in_L", "strength": 100},
                {"from": "Pitch Shifter.audio_out", "to": "Reverb Lite.audio_in_R", "strength": 100},
                {"from": "Reverb Lite.audio_out_L", "to": "Audio Mixer.audio_in_2_L", "strength": 100},
                {"from": "Reverb Lite.audio_out_R", "to": "Audio Mixer.audio_in_2_R", "strength": 100},
                {"from": "Audio Mixer.audio_out_L", "to": "Audio Output.input_L", "strength": 100},
                {"from": "Audio Mixer.audio_out_R", "to": "Audio Output.input_R", "strength": 100},
            ],
        },
        "expect_issues": 0,
    },
    {
        "name": "sampler-parallel",
        "desc": "Sampler with live parallel path and stompswitch-triggered record.",
        "ai_json": {
            "name": "SamplerP",
            "modules": [
                {"type": "Sampler", "page": 0, "position": 0,
                 "options": {"record": "new sample", "playback": "loop"}},
                {"type": "Audio Mixer", "page": 0, "position": 20,
                 "options": {"channels": 2, "stereo": "mono"}},
                {"type": "Stompswitch", "page": 0, "position": 30,
                 "options": {"stompswitch": "left", "action": "momentary"}},
            ],
            "connections": [
                {"from": "Audio Input.output_L", "to": "Sampler.audio_in_L", "strength": 100},
                {"from": "Audio Input.output_L", "to": "Audio Mixer.audio_in_1_L", "strength": 100},
                {"from": "Sampler.audio_out_L", "to": "Audio Mixer.audio_in_2_L", "strength": 90},
                {"from": "Audio Mixer.audio_out_L", "to": "Audio Output.input_L", "strength": 100},
                {"from": "Stompswitch.cv_output", "to": "Sampler.record", "strength": 100},
            ],
        },
        "expect_issues": 0,
    },
]


def run_spec(spec):
    name = spec["name"]
    ai_json = spec["ai_json"]
    try:
        pch = build_patch(ai_json)
    except BuildError as e:
        return {"name": name, "ok": False, "stage": "build", "error": str(e)}

    issues = validate_patch(pch)
    critical = [i for i in issues if not i.startswith("WARN:")]
    soft = [i for i in issues if i.startswith("WARN:")]

    try:
        data = encode_patch(pch)
        size = len(data)
    except Exception as e:  # noqa: BLE001
        return {"name": name, "ok": False, "stage": "encode", "error": str(e),
                "critical": critical, "soft": soft}

    ok = (
        len(critical) <= spec.get("expect_issues", 0)
        and size > 0
    )
    return {
        "name": name,
        "ok": ok,
        "stage": "done",
        "size": size,
        "modules": len(pch["modules"]),
        "connections": len(pch["connections"]),
        "critical": critical,
        "soft": soft,
        "fixups": ai_json.get("_fixups", []),
    }


def main():
    results = [run_spec(s) for s in SPECS]
    pad = max(len(r["name"]) for r in results) + 2
    failed = 0
    for r in results:
        tag = "PASS" if r["ok"] else "FAIL"
        print(f"[{tag}] {r['name']:<{pad}}", end="")
        if r["ok"]:
            print(f"mods={r['modules']:>2}  conns={r['connections']:>2}  "
                  f"size={r['size']:>5}B  warn={len(r['soft']):>1}")
        else:
            print(f"stage={r['stage']}  error={r.get('error', 'issues')}")
            for c in r.get("critical", []):
                print(f"    critical: {c}")
            failed += 1
        if r.get("fixups"):
            for f in r["fixups"]:
                print(f"    fixup: {f}")
        if r["ok"] and r.get("soft"):
            for w in r["soft"]:
                print(f"    {w}")

    print()
    if failed:
        print(f"{failed}/{len(results)} specs failed.")
        sys.exit(1)
    print(f"All {len(results)} specs passed.")


if __name__ == "__main__":
    main()
