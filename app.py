import os
import json
import re
import base64
import requests as http_requests
from flask import Flask, render_template, request, jsonify, Response
from zoia_knowledge import ZOIA_SYSTEM_PROMPT, get_structured_prompt
from patch_builder import build_patch, BuildError
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
    """Extract JSON from AI response, handling markdown code fences."""
    text = text.strip()
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    return json.loads(text)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/status")
def status():
    backend, model = get_backend()
    return jsonify({"backend": backend, "model": model})


@app.route("/build", methods=["POST"])
def build_patch_text():
    data = request.get_json()
    description = data.get("description", "").strip()

    if not description:
        return jsonify({"error": "Please describe the effect you want to build."}), 400

    backend, model = get_backend()

    if not backend:
        return jsonify({
            "error": "No AI backend available. Either install Ollama with a model, "
                     "or set GEMINI_API_KEY (free at https://aistudio.google.com/apikey)."
        }), 503

    def stream():
        try:
            if backend == "ollama":
                yield from stream_ollama(description, model)
            else:
                yield from stream_gemini(description)
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


@app.route("/build-bin", methods=["POST"])
def build_patch_bin():
    data = request.get_json()
    description = data.get("description", "").strip()

    if not description:
        return jsonify({"error": "Please describe the effect you want to build."}), 400

    backend, model = get_backend()

    if not backend:
        return jsonify({
            "error": "No AI backend available. Either install Ollama with a model, "
                     "or set GEMINI_API_KEY (free at https://aistudio.google.com/apikey)."
        }), 503

    structured_prompt = get_structured_prompt()

    def sse(event, data):
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"

    def stream():
        max_attempts = 2
        last_error = None

        for attempt in range(max_attempts):
            try:
                if attempt > 0:
                    yield sse("progress", {"step": "retry", "message": "Retrying..."})

                yield sse("progress", {"step": "ai", "message": f"Designing patch with {model}..."})
                raw = generate_full_response(description, backend, model, structured_prompt)

                yield sse("progress", {"step": "parse", "message": "Parsing AI response..."})
                ai_json = extract_json(raw)

                yield sse("progress", {"step": "build", "message": "Building patch structure..."})
                encoder_dict = build_patch(ai_json)

                n_mods = len(encoder_dict["modules"])
                n_conns = len(encoder_dict["connections"])
                yield sse("progress", {"step": "encode", "message": f"Encoding binary ({n_mods} modules, {n_conns} connections)..."})
                binary = encode_patch(encoder_dict)

                patch_name = ai_json.get("name", "patch").replace(" ", "_").lower()
                patch_name = re.sub(r"[^a-z0-9_]", "", patch_name)[:16] or "patch"
                filename = f"{patch_name}.bin"

                b64 = base64.b64encode(binary).decode("ascii")

                yield sse("done", {"filename": filename, "data": b64, "modules": n_mods, "connections": n_conns})
                return

            except json.JSONDecodeError as e:
                last_error = f"AI returned invalid JSON (attempt {attempt + 1}/{max_attempts}). Parser error: {e}"
            except BuildError as e:
                last_error = f"Patch build error: {e}"
            except Exception as e:
                last_error = str(e)

        yield sse("error", {"message": last_error})

    return Response(stream(), mimetype="text/event-stream")


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
