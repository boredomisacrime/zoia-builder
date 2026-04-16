"""
Stage 1 (design) of the two-stage patch pipeline.

The AI now does two calls:
  1. design_patch(...)  — produces a prose plan + clarifying questions (no JSON schema)
  2. encode_plan(...)   — converts that plan into strict JSON that patch_builder understands

The plan is a small JSON object the designer emits internally; the "plan text" that
gets shown to the user is a rendered prose version.

This module also exposes:
  - refine_plan(...)          — take an existing plan + a tweak request, produce a new plan
  - suggest_improvements(...) — propose 3 short remix ideas for an existing plan
  - parse_tuning(...)         — turn "F# A# C# F A# C#" into a list of semitones for the AI
"""

from __future__ import annotations

import json
import re
from typing import Callable, Iterable


# ---------------------------------------------------------------------------
# Public data shapes
# ---------------------------------------------------------------------------

class DesignPlan(dict):
    """A plan dict with the following known keys (all optional except the first two):

    - name (str)                — short patch name (max 16 chars)
    - summary (str)             — one-paragraph description of the effect
    - signal_flow (list[str])   — ordered audio path lines, e.g.
        "Audio Input.output_L -> Audio Mixer.audio_in_1_L (live dry)"
    - modules (list[dict])      — [{type, purpose, page?}]
    - cv_routing (list[str])    — CV cable descriptions ("LFO.output -> Reverb.decay")
    - controls (list[str])      — stompswitch / pushbutton / expression mapping lines
    - pages (list[str])         — names for each page
    - questions (list[dict])    — [{id, question, options?}]  (optional answers list)
    - confidence (float)        — 0..1, how confident the AI is that the ask is unambiguous
    - notes (str)               — free-text caveats or tips
    """


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_NOTE_TO_SEMI = {n: i for i, n in enumerate(_NOTE_NAMES)}
# Enharmonics
for _flat, _sharp in [("Db", "C#"), ("Eb", "D#"), ("Gb", "F#"), ("Ab", "G#"), ("Bb", "A#")]:
    _NOTE_TO_SEMI[_flat] = _NOTE_TO_SEMI[_sharp]


def parse_tuning(tuning: str) -> list[str]:
    """Turn "F#A#C#F A# C#" or "F# A# C# F A# C#" into ['F#', 'A#', 'C#', 'F', 'A#', 'C#'].

    Returns an empty list if nothing parseable.
    """
    if not tuning:
        return []
    # Match note tokens like "F#", "Bb", "A", regardless of spacing
    tokens = re.findall(r"[A-G][#b]?", tuning.strip())
    valid = [t for t in tokens if t in _NOTE_TO_SEMI]
    return valid


def tuning_to_pitch_hint(tuning: str) -> str:
    """Produce a short prompt hint describing which notes/semitones an arpeggiator
    or sequencer should lean on based on the user's tuning."""
    notes = parse_tuning(tuning)
    if not notes:
        return ""
    unique = []
    for n in notes:
        if n not in unique:
            unique.append(n)
    semitones = sorted(set(_NOTE_TO_SEMI[n] for n in unique))
    return (
        f"The user plays in tuning {' '.join(notes)}. "
        f"Any arpeggiator, sequencer, harmonizer or pitch-shift modules should prefer "
        f"notes from {{{', '.join(unique)}}} and octaves of them "
        f"(semitones {semitones} modulo 12). "
        f"Scales that fit: the user's own chord voicings on these strings plus the minor pentatonic rooted on the lowest string. "
        f"Avoid fixed chromatic arpeggios — they will clash."
    )


def format_profile_block(profile: dict | None) -> str:
    """Render a compact TASTE PROFILE block for prompts. Empty string if no profile."""
    if not profile:
        return ""
    lines = []
    artists = (profile.get("artists") or "").strip()
    genres = (profile.get("genres") or "").strip()
    instrument = (profile.get("instrument") or "").strip()
    tuning = (profile.get("tuning") or "").strip()
    playing = (profile.get("playing_style") or "").strip()
    rig = (profile.get("rig") or "").strip()
    expression = profile.get("expression_pedal")
    midi = profile.get("midi")
    wetness = profile.get("wetness")
    avoid = (profile.get("avoid") or "").strip()
    stompswitch_comfort = (profile.get("stompswitch_comfort") or "").strip()

    if artists:
        lines.append(f"- Artists / references: {artists}")
    if genres:
        lines.append(f"- Genres / moods: {genres}")
    if instrument or tuning:
        parts = []
        if instrument:
            parts.append(instrument)
        if tuning:
            parts.append(f"tuning {tuning}")
        lines.append(f"- Instrument: {', '.join(parts)}")
    if playing:
        lines.append(f"- Playing style: {playing}")
    if rig:
        lines.append(f"- Rig: {rig}")
    if expression is True:
        lines.append("- Expression pedal available: yes")
    elif expression is False:
        lines.append("- Expression pedal available: no (do not rely on expression)")
    if midi is True:
        lines.append("- MIDI available: yes")
    elif midi is False:
        lines.append("- MIDI available: no")
    if stompswitch_comfort:
        lines.append(f"- Stompswitch comfort: {stompswitch_comfort}")
    if isinstance(wetness, (int, float)):
        lines.append(f"- Wet/dry leaning: {int(wetness)}% wet")
    if avoid:
        lines.append(f"- Avoid: {avoid}")

    tuning_hint = tuning_to_pitch_hint(tuning)
    if tuning_hint:
        lines.append(f"- Tuning guidance for pitched modules: {tuning_hint}")

    if not lines:
        return ""

    return "TASTE PROFILE (use this to shape the patch, not as a hard constraint)\n" + "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Prompt-side rendering
# ---------------------------------------------------------------------------

def render_plan_as_prose(plan: dict) -> str:
    """Render a plan dict into human-readable prose for display in the UI
    and as Stage-2 input to the encoder."""
    if not plan:
        return ""

    out: list[str] = []
    name = plan.get("name") or "Untitled Patch"
    out.append(f"PATCH: {name}")
    out.append("")

    summary = plan.get("summary") or ""
    if summary:
        out.append("SUMMARY")
        out.append(summary.strip())
        out.append("")

    pages = plan.get("pages") or []
    if pages:
        out.append("PAGES")
        for i, p in enumerate(pages):
            out.append(f"  Page {i}: {p}")
        out.append("")

    modules = plan.get("modules") or []
    if modules:
        out.append("MODULES")
        for m in modules:
            if isinstance(m, dict):
                mtype = m.get("type", "?")
                purpose = m.get("purpose") or m.get("role") or ""
                page = m.get("page")
                line = f"  - {mtype}"
                if page is not None:
                    line += f" (page {page})"
                if purpose:
                    line += f": {purpose}"
                out.append(line)
            else:
                out.append(f"  - {m}")
        out.append("")

    flow = plan.get("signal_flow") or []
    if flow:
        out.append("SIGNAL FLOW")
        for line in flow:
            out.append(f"  {line}")
        out.append("")

    cv = plan.get("cv_routing") or []
    if cv:
        out.append("CV ROUTING (CV cables only — never into audio_in)")
        for line in cv:
            out.append(f"  {line}")
        out.append("")

    ctrl = plan.get("controls") or []
    if ctrl:
        out.append("CONTROLS (stompswitch / pushbutton / expression)")
        for line in ctrl:
            out.append(f"  {line}")
        out.append("")

    notes = plan.get("notes") or ""
    if notes:
        out.append("NOTES")
        out.append(notes.strip())
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def render_plan_as_mermaid(plan: dict) -> str:
    """Render the signal flow as a mermaid flowchart. Returns '' if no flow."""
    flow = plan.get("signal_flow") or []
    if not flow:
        return ""

    node_ids: dict[str, str] = {}
    edges: list[tuple[str, str, str | None]] = []

    def node_id(label: str) -> str:
        key = label.strip()
        if key not in node_ids:
            safe = re.sub(r"[^A-Za-z0-9]", "", key) or f"n{len(node_ids)}"
            # Ensure unique id
            base = safe
            i = 1
            while safe in node_ids.values():
                i += 1
                safe = f"{base}{i}"
            node_ids[key] = safe
        return node_ids[key]

    for raw in flow:
        s = str(raw).strip()
        # Accept "A -> B" or "A → B" with optional trailing label after " ("
        m = re.match(r"^(?P<src>.+?)\s*(?:->|→)\s*(?P<dst>[^(]+?)(?:\s*\((?P<label>.+)\))?$", s)
        if not m:
            continue
        src = m.group("src").strip()
        dst = m.group("dst").strip()
        label = (m.group("label") or "").strip() or None
        edges.append((src, dst, label))

    if not edges:
        return ""

    # Populate node_ids before we emit declarations
    for src, dst, _label in edges:
        node_id(src)
        node_id(dst)

    lines = ["flowchart LR"]
    for full, nid in node_ids.items():
        short = full.replace('"', "'")
        lines.append(f'    {nid}["{short}"]')
    for src, dst, label in edges:
        sid = node_ids[src.strip()]
        did = node_ids[dst.strip()]
        if label:
            clean = label.replace("|", "/").replace('"', "'")
            lines.append(f'    {sid} -->|"{clean}"| {did}')
        else:
            lines.append(f"    {sid} --> {did}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Design call (Stage 1)
# ---------------------------------------------------------------------------

def _extract_first_json(text: str) -> dict:
    """Tolerant JSON extraction from a model response that may include prose."""
    if not text:
        raise ValueError("empty response")

    fence = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in response")

    depth = 0
    in_str = False
    escape = False
    end = -1
    for i, ch in enumerate(text[start:], start):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_str:
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        raise ValueError("unterminated JSON")

    chunk = text[start:end]
    chunk = re.sub(r",\s*([}\]])", r"\1", chunk)
    chunk = re.sub(r"//[^\n]*", "", chunk)
    return json.loads(chunk)


def _normalise_plan(plan: dict) -> DesignPlan:
    """Coerce optional fields into consistent shapes."""
    out = DesignPlan()
    out["name"] = str(plan.get("name") or "New Patch")[:32]
    out["summary"] = str(plan.get("summary") or "").strip()

    def _as_list(val) -> list:
        if isinstance(val, list):
            return val
        if val in (None, ""):
            return []
        return [val]

    out["signal_flow"] = [str(x) for x in _as_list(plan.get("signal_flow"))]
    out["cv_routing"] = [str(x) for x in _as_list(plan.get("cv_routing"))]
    out["controls"] = [str(x) for x in _as_list(plan.get("controls"))]
    out["pages"] = [str(x) for x in _as_list(plan.get("pages"))]
    out["modules"] = [m for m in _as_list(plan.get("modules")) if m]
    out["notes"] = str(plan.get("notes") or "").strip()

    questions_raw = _as_list(plan.get("questions"))
    questions: list[dict] = []
    for q in questions_raw:
        if isinstance(q, str):
            questions.append({"id": f"q{len(questions)+1}", "question": q})
        elif isinstance(q, dict):
            qid = str(q.get("id") or f"q{len(questions)+1}")
            qtext = str(q.get("question") or q.get("prompt") or "").strip()
            if not qtext:
                continue
            entry = {"id": qid, "question": qtext}
            opts = q.get("options")
            if isinstance(opts, list) and opts:
                entry["options"] = [str(o).strip() for o in opts if str(o).strip()]
            questions.append(entry)
    out["questions"] = questions[:3]

    try:
        conf = float(plan.get("confidence", 0.75))
    except (TypeError, ValueError):
        conf = 0.75
    out["confidence"] = max(0.0, min(1.0, conf))

    return out


def design_patch(
    description: str,
    profile: dict | None,
    reference_text: str,
    *,
    design_system_prompt: str,
    generate_full_response: Callable[[str, str], str],
    previous_plan: dict | None = None,
    tweak: str | None = None,
) -> DesignPlan:
    """Run Stage 1. Returns a normalised DesignPlan.

    generate_full_response(user_message, system_prompt) -> raw AI text
    """
    profile_block = format_profile_block(profile)
    user_sections: list[str] = []

    if profile_block:
        user_sections.append(profile_block)

    if reference_text:
        user_sections.append(
            "--- INSPIRATION REFERENCE (adapt, don't copy literally) ---\n"
            f"{reference_text[:6000]}\n"
            "--- END REFERENCE ---"
        )

    if previous_plan:
        user_sections.append(
            "PREVIOUS PLAN (modify this — keep what works, change only what the tweak requires):\n"
            + render_plan_as_prose(previous_plan)
        )

    if tweak:
        user_sections.append(f"TWEAK REQUEST: {tweak.strip()}")

    user_sections.append(f"USER REQUEST: {description.strip()}")
    user_sections.append(
        "Return ONLY a single JSON object matching the schema defined in the system prompt. "
        "No prose outside the JSON, no code fences."
    )

    user_message = "\n\n".join(user_sections)

    raw = generate_full_response(user_message, design_system_prompt)
    try:
        plan_raw = _extract_first_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        # Fallback: retry once with a stricter nudge
        retry_raw = generate_full_response(
            "Your previous response was not valid JSON. "
            "Output ONLY a single JSON object — no markdown, no commentary.\n\n"
            + user_message,
            design_system_prompt,
        )
        plan_raw = _extract_first_json(retry_raw)

    return _normalise_plan(plan_raw)


# ---------------------------------------------------------------------------
# Improvement suggestions
# ---------------------------------------------------------------------------

_IMPROVE_PROMPT = """You are an expert ZOIA patch designer. Given the current patch plan below,
propose exactly 3 concise improvement ideas the user could apply next. Each should be a single
short sentence describing a musical tweak (e.g. "Add a tap-tempo pushbutton wired to delay time
and feedback for randomise-on-tap", "Split into stereo with a short slapback on the right",
"Swap Delay w/Mod for Ping Pong and add a shimmer tail").

Return ONLY a JSON object of the form:
{
  "suggestions": [
    {"title": "Short label", "tweak": "One-sentence change the refine step can apply"},
    {"title": "...", "tweak": "..."},
    {"title": "...", "tweak": "..."}
  ]
}

Do not include any text outside the JSON."""


def suggest_improvements(
    plan: dict,
    profile: dict | None,
    *,
    generate_full_response: Callable[[str, str], str],
) -> list[dict]:
    """Ask the model for 3 one-click remix ideas for the current plan."""
    profile_block = format_profile_block(profile)
    user = ""
    if profile_block:
        user += profile_block + "\n"
    user += "CURRENT PLAN:\n" + render_plan_as_prose(plan)

    raw = generate_full_response(user, _IMPROVE_PROMPT)
    try:
        obj = _extract_first_json(raw)
    except Exception:
        return []

    out: list[dict] = []
    for s in (obj.get("suggestions") or [])[:3]:
        if not isinstance(s, dict):
            continue
        title = str(s.get("title") or "").strip()
        tweak = str(s.get("tweak") or s.get("description") or "").strip()
        if not title or not tweak:
            continue
        out.append({"title": title[:80], "tweak": tweak[:400]})
    return out
