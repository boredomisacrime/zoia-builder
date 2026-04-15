import io
import os
import json
import re
import base64
import requests as http_requests
from flask import Flask, render_template, request, jsonify, Response
from PyPDF2 import PdfReader
from zoia_knowledge import (
    ZOIA_SYSTEM_PROMPT,
    get_structured_prompt,
    minimalism_rules_for_description,
)
from patch_builder import build_patch, validate_patch, BuildError
from patch_encoder import encode_patch

app = Flask(__name__)

OLLAMA_URL = "http://localhost:11434"
PREFERRED_MODELS = ["gemma4:26b", "gemma3:12b", "llama3.2:latest"]
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.0-flash"


def ollama_available():
    try:
        resp = http_requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        models = {m["name"] for m in resp.json().get("models", [])}
        for m in PREFERRED_MODELS:
            if m in models:
                return m
    except Exception:
        pass
    return None


def get_backend():
    model = ollama_available()
    if model:
        return "ollama", model
    if GEMINI_API_KEY:
        return "gemini", GEMINI_MODEL
    return None, None


def stream_ollama(description, model, system_prompt=ZOIA_SYSTEM_PROMPT):
    resp = http_requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": model,
            "stream": True,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": description},
            ],
        },
        stream=True,
        timeout=300,
    )
    resp.raise_for_status()
    for line in resp.iter_lines():
        if line:
            chunk = json.loads(line)
            text = chunk.get("message", {}).get("content", "")
            if text:
                yield text


def stream_gemini(description, system_prompt=ZOIA_SYSTEM_PROMPT):
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}"
        f":streamGenerateContent?alt=sse&key={GEMINI_API_KEY}"
    )
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": [{"text": description}]}],
    }
    resp = http_requests.post(url, json=payload, stream=True, timeout=300)
    resp.raise_for_status()

    for line in resp.iter_lines():
        if not line:
            continue
        decoded = line.decode("utf-8", errors="replace")
        if not decoded.startswith("data: "):
            continue
        try:
            chunk = json.loads(decoded[6:])
            parts = chunk.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            for part in parts:
                text = part.get("text", "")
                if text:
                    yield text
        except (json.JSONDecodeError, IndexError, KeyError):
            continue


def generate_full_response(description, backend, model, system_prompt):
    """Collect a full (non-streaming) response from the AI."""
    chunks = []
    if backend == "ollama":
        for text in stream_ollama(description, model, system_prompt):
            chunks.append(text)
    else:
        for text in stream_gemini(description, system_prompt):
            chunks.append(text)
    return "".join(chunks)


def extract_json(text):
    """Extract JSON from AI response — handles fences, preamble, trailing text, and common errors."""
    text = text.strip()

    # Strip markdown code fences
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    # Find the top-level JSON object by brace matching
    start = text.find("{")
    if start < 0:
        raise json.JSONDecodeError("No JSON object found", text, 0)

    depth = 0
    in_string = False
    escape = False
    end = start
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if depth == 0:
        text = text[start:end]
    else:
        text = text[start:]

    text = _repair_json(text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Last resort: try inserting missing commas between } { and ] [ patterns
        text = re.sub(r'(\})\s*(\{)', r'\1,\2', text)
        text = re.sub(r'(\])\s*(\[)', r'\1,\2', text)
        return json.loads(text)


def _repair_json(text):
    """Fix common AI JSON mistakes."""
    # Strip single-line comments
    text = re.sub(r'//[^\n]*', '', text)

    # Remove trailing commas before } or ]
    text = re.sub(r',\s*([}\]])', r'\1', text)

    # Insert missing commas: "}\n  {" → "},\n  {"
    text = re.sub(r'(\})\s*\n(\s*\{)', r'\1,\n\2', text)
    text = re.sub(r'(\])\s*\n(\s*\[)', r'\1,\n\2', text)

    # Fix missing comma between value and next key: 0\n "key" or "val"\n "key"
    text = re.sub(r'([^,\[\{:\s])\s*\n(\s*")', r'\1,\n\2', text)

    # Close truncated JSON
    open_braces = text.count('{') - text.count('}')
    open_brackets = text.count('[') - text.count(']')
    if open_braces > 0 or open_brackets > 0:
        # Trim back to last complete element
        last_comma = text.rfind(',')
        last_close = max(text.rfind('}'), text.rfind(']'))
        if last_comma > last_close and last_close > 0:
            text = text[:last_comma]
        elif last_close > 0:
            text = text[:last_close + 1]
        # Recount after trim
        open_braces = text.count('{') - text.count('}')
        open_brackets = text.count('[') - text.count(']')
        text += ']' * max(0, open_brackets) + '}' * max(0, open_braces)
        text = re.sub(r',\s*([}\]])', r'\1', text)

    return text


def format_patch_text(description, ai_json, encoder_dict):
    lines = []
    lines.append(f"ZOIA Patch: {ai_json.get('name', 'Untitled')}")
    lines.append("=" * 50)
    lines.append("")
    lines.append(f"Description: {description}")
    lines.append("")

    pages = ai_json.get("pages", [])
    if pages:
        lines.append(f"Pages: {', '.join(pages)}")
        lines.append("")

    lines.append("MODULES")
    lines.append("-" * 50)
    for i, mod in enumerate(ai_json.get("modules", [])):
        label = mod.get("name", mod.get("type", "?"))
        mod_type = mod.get("type", "?")
        page = mod.get("page", 0)
        pos = mod.get("position", "?")
        color = mod.get("color", "?")
        lines.append(f"  [{i}] {mod_type}" + (f' "{label}"' if label != mod_type else ""))
        lines.append(f"      Page {page}, position {pos}, color {color}")

        params = mod.get("parameters", {})
        if params:
            lines.append("      Parameters:")
            for pname, pval in params.items():
                lines.append(f"        {pname}: {pval}")

        options = mod.get("options", {})
        if options:
            lines.append("      Options:")
            for oname, oval in options.items():
                lines.append(f"        {oname}: {oval}")
        lines.append("")

    lines.append("CONNECTIONS")
    lines.append("-" * 50)
    for conn in ai_json.get("connections", []):
        src = conn.get("from", "?")
        dst = conn.get("to", "?")
        strength = conn.get("strength", 100)
        strength_str = f" ({strength}%)" if strength != 100 else ""
        lines.append(f"  {src} → {dst}{strength_str}")

    lines.append("")
    lines.append(f"Totals: {len(encoder_dict['modules'])} modules, {len(encoder_dict['connections'])} connections")
    return "\n".join(lines)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/status")
def status():
    backend, model = get_backend()
    return jsonify({"backend": backend, "model": model})


MAX_PDF_PAGES = 50
MAX_PDF_CHARS = 30_000


@app.route("/upload-pdf", methods=["POST"])
def upload_pdf():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    f = request.files["file"]
    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are supported."}), 400

    try:
        reader = PdfReader(io.BytesIO(f.read()))
        pages = reader.pages[:MAX_PDF_PAGES]
        text = "\n\n".join(page.extract_text() or "" for page in pages)
        text = text[:MAX_PDF_CHARS]
    except Exception as e:
        return jsonify({"error": f"Could not read PDF: {e}"}), 400

    if not text.strip():
        return jsonify({"error": "PDF appears to be image-only (no extractable text)."}), 400

    return jsonify({"text": text, "pages": len(pages), "chars": len(text)})


def _build_user_message(description, reference_text):
    """Combine optional reference material with the user's description."""
    if not reference_text:
        return description
    ref = reference_text[:8000]
    return (
        "--- INSPIRATION REFERENCE (another pedal/effect — adapt the concept to ZOIA modules) ---\n"
        f"{ref}\n"
        "--- END REFERENCE ---\n\n"
        "Use the reference above as creative inspiration only. "
        "Do NOT copy its hardware design literally — translate the concept "
        "into ZOIA modules, connections, and signal flow.\n\n"
        f"User request: {description}"
    )


@app.route("/build", methods=["POST"])
def build_patch_text():
    data = request.get_json()
    description = data.get("description", "").strip()
    reference_text = data.get("reference_text", "").strip()

    if not description:
        return jsonify({"error": "Please describe the effect you want to build."}), 400

    backend, model = get_backend()

    if not backend:
        return jsonify({
            "error": "No AI backend available. Either install Ollama with a model, "
                     "or set GEMINI_API_KEY (free at https://aistudio.google.com/apikey)."
        }), 503

    user_message = _build_user_message(description, reference_text)
    extra = minimalism_rules_for_description(description, for_json=False)
    if extra:
        user_message = extra + "\n\n" + user_message

    def stream():
        try:
            if backend == "ollama":
                yield from stream_ollama(user_message, model)
            else:
                yield from stream_gemini(user_message)
        except http_requests.ConnectionError:
            yield "\n\n**Can't reach the AI backend.** Check that Ollama is running, or that your API key is valid."
        except Exception as e:
            msg = str(e)
            if "429" in msg or "quota" in msg.lower():
                yield "\n\n**Rate limit hit.** The free Gemini tier has a daily cap. Try again later."
            elif "401" in msg or "403" in msg:
                yield "\n\n**API key error.** Check that your GEMINI_API_KEY is valid."
            else:
                yield f"\n\n**Error:** {msg.split(chr(10))[0]}"

    return Response(stream(), mimetype="text/plain")


def _build_correction_prompt(original_description, issues, reference_text=""):
    """Build a prompt that tells the AI what went wrong and asks for a fix."""
    issue_list = "\n".join(f"  {i+1}. {iss}" for i, iss in enumerate(issues))
    msg = (
        f"Your previous patch design has CRITICAL issues that make it non-functional:\n\n"
        f"{issue_list}\n\n"
        f"Design a COMPLETELY NEW, CORRECTED patch. Key rules:\n"
        f"- The audio signal MUST flow unbroken: Audio Input → effects → Audio Output\n"
        f"- NEVER use Sampler or Looper in the audio chain (they don't pass audio through)\n"
        f"- Use ONLY pass-through effects: Delay Line, Reverb, Chorus, Flanger, "
        f"Phaser, SV Filter, VCA, Audio Mixer, Bit Crusher, etc.\n"
        f"- CV sources (LFO, Env Follower) connect to PARAMETER blocks, never audio inputs\n"
        f"- Every module in the audio chain must have both input AND output connected\n\n"
        f"Original request: {original_description}"
    )
    if reference_text:
        ref = reference_text[:8000]
        msg = (
            f"--- INSPIRATION REFERENCE ---\n{ref}\n--- END REFERENCE ---\n\n" + msg
        )
    return msg


@app.route("/build-bin", methods=["POST"])
def build_patch_bin():
    data = request.get_json()
    description = data.get("description", "").strip()
    reference_text = data.get("reference_text", "").strip()

    if not description:
        return jsonify({"error": "Please describe the effect you want to build."}), 400

    backend, model = get_backend()

    if not backend:
        return jsonify({
            "error": "No AI backend available. Either install Ollama with a model, "
                     "or set GEMINI_API_KEY (free at https://aistudio.google.com/apikey)."
        }), 503

    structured_prompt = (
        get_structured_prompt() + minimalism_rules_for_description(description, for_json=True)
    )
    original_user_message = _build_user_message(description, reference_text)

    def sse(event, data):
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"

    def stream():
        max_attempts = 3
        last_error = None
        current_message = original_user_message
        final_issues = None

        for attempt in range(max_attempts):
            try:
                attempt_label = f" (attempt {attempt + 1}/{max_attempts})" if attempt > 0 else ""

                if attempt > 0:
                    if final_issues:
                        retry_msg = f"Redesigning patch to fix {len(final_issues)} issue(s)..."
                    else:
                        retry_msg = "Retrying..."
                    yield sse("progress", {
                        "step": "retry",
                        "message": retry_msg,
                    })

                yield sse("progress", {
                    "step": "ai",
                    "message": f"Designing patch{attempt_label}..."
                })
                raw = generate_full_response(
                    current_message, backend, model, structured_prompt
                )

                if not raw or not raw.strip():
                    raise json.JSONDecodeError("AI returned an empty response", "", 0)

                yield sse("progress", {"step": "parse", "message": "Parsing AI response..."})
                print(f"[build-bin] AI response ({len(raw)} chars): {raw[:200]}...")
                ai_json = extract_json(raw)

                yield sse("progress", {"step": "build", "message": "Building patch structure..."})
                encoder_dict = build_patch(ai_json)

                audio_fixes = encoder_dict.pop("_audio_path_auto_fixes", None)
                if audio_fixes:
                    for note in audio_fixes:
                        print(f"[build-bin] {note}")
                    yield sse("progress", {
                        "step": "auto_fix",
                        "message": "Applied audio path fix (dry pass-through) so the patch can produce sound.",
                    })

                # --- VALIDATION ---
                yield sse("progress", {"step": "validate", "message": "Validating patch..."})
                issues = validate_patch(encoder_dict)

                if issues:
                    print(f"[validate] {len(issues)} issue(s) found:")
                    for iss in issues:
                        print(f"  - {iss}")

                    if attempt < max_attempts - 1:
                        final_issues = issues
                        current_message = _build_correction_prompt(
                            description, issues, reference_text
                        )
                        continue
                    else:
                        final_issues = issues
                        yield sse("progress", {
                            "step": "validate_warn",
                            "message": (
                                f"WARNING: Patch still has {len(issues)} issue(s) "
                                f"after {max_attempts} attempts. Delivering anyway."
                            )
                        })
                else:
                    print("[validate] Patch passed all checks ✓")
                    yield sse("progress", {
                        "step": "validate_ok",
                        "message": "Patch validation passed ✓"
                    })
                    final_issues = None

                n_mods = len(encoder_dict["modules"])
                n_conns = len(encoder_dict["connections"])
                yield sse("progress", {
                    "step": "encode",
                    "message": f"Encoding binary ({n_mods} modules, {n_conns} connections)..."
                })
                binary = encode_patch(encoder_dict)

                patch_name = ai_json.get("name", "patch").replace(" ", "_").lower()
                patch_name = re.sub(r"[^a-z0-9_]", "", patch_name)[:16] or "patch"
                filename = f"{patch_name}.bin"

                b64 = base64.b64encode(binary).decode("ascii")

                patch_text = format_patch_text(description, ai_json, encoder_dict)

                if audio_fixes:
                    patch_text += "\n\nAUTO-FIX (AUDIO PATH)\n"
                    patch_text += "-" * 50 + "\n"
                    for note in audio_fixes:
                        patch_text += f"  • {note}\n"

                if final_issues:
                    patch_text += "\n\n⚠ VALIDATION WARNINGS\n"
                    patch_text += "-" * 50 + "\n"
                    for iss in final_issues:
                        patch_text += f"  • {iss}\n"

                yield sse("done", {
                    "filename": filename,
                    "data": b64,
                    "modules": n_mods,
                    "connections": n_conns,
                    "patch_text": patch_text,
                    "validation": {
                        "passed": not final_issues,
                        "issues": final_issues or [],
                        "audio_path_auto_fixes": audio_fixes or [],
                        "attempts": attempt + 1,
                    },
                })
                return

            except json.JSONDecodeError as e:
                snippet = raw[:300] if raw else "(empty)"
                last_error = (
                    f"AI returned invalid JSON (attempt {attempt + 1}/{max_attempts}). "
                    f"Parser error: {e}\n\nAI response started with:\n{snippet}"
                )
                print(f"[build-bin] JSON error: {e}")
                current_message = (
                    "IMPORTANT: Your previous response was not valid JSON. "
                    "Output ONLY a single JSON object — no comments, no trailing commas, "
                    "no markdown, no explanation. Just the raw JSON.\n\n"
                    + original_user_message
                )
            except BuildError as e:
                last_error = f"Patch build error: {e}"
                current_message = original_user_message
            except Exception as e:
                last_error = str(e)
                current_message = original_user_message

        yield sse("error", {"message": last_error})

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    backend, model = get_backend()
    if backend == "ollama":
        print(f"Backend: Ollama ({model})")
    elif backend == "gemini":
        print(f"Backend: Gemini API ({model})")
    else:
        print("WARNING: No backend available.")
        print("  Option A: Install Ollama (https://ollama.com) and pull a model")
        print("  Option B: export GEMINI_API_KEY='your-key'  (free at https://aistudio.google.com/apikey)")
        print()

    print("Starting ZOIA Patch Builder → http://127.0.0.1:8080\n")
    app.run(debug=True, host="127.0.0.1", port=8080)
