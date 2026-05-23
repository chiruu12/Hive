"""Interactive test agent for voice/assistant infrastructure.

Exercises every new module added in 0.3.2:
  - STT providers (WhisperLocal, GroqSTT, DeepgramSTT)
  - AudioRecorder
  - IntentRouter
  - Triggers (Hotkey, Webhook)
  - LinkToolkit

Run:
    uv run python examples/test_voice_infra.py
"""

from __future__ import annotations

import asyncio
import os
import platform
import struct
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

# ── Helpers ──────────────────────────────────────────────────────────────────

PASS = 0
FAIL = 0
SKIP = 0


def ok(msg: str) -> None:
    global PASS
    PASS += 1
    print(f"  \033[32m✓\033[0m {msg}")


def fail(msg: str, err: Exception | str = "") -> None:
    global FAIL
    FAIL += 1
    print(f"  \033[31m✗\033[0m {msg}: {err}")


def skip(msg: str, reason: str = "") -> None:
    global SKIP
    SKIP += 1
    print(f"  \033[33m⊘\033[0m {msg} — {reason}")


def section(title: str) -> None:
    print(f"\n\033[1m{'─' * 60}\033[0m")
    print(f"\033[1m  {title}\033[0m")
    print(f"\033[1m{'─' * 60}\033[0m")


# ── 1. Version & Imports ────────────────────────────────────────────────────

section("1. Version & Top-Level Imports")

import hive

if hive.__version__ == "0.3.2":
    ok(f"Version: {hive.__version__}")
else:
    fail(f"Version mismatch: expected 0.3.2, got {hive.__version__}")

new_exports = [
    "STTProvider", "TranscriptionResult", "WhisperLocal", "GroqSTT",
    "DeepgramSTT", "create_stt_provider", "AudioRecorder",
    "IntentRouter", "IntentResult",
    "HotkeyTrigger", "WebhookTrigger", "Trigger",
    "LinkToolkit",
]
missing = [n for n in new_exports if not hasattr(hive, n)]
if not missing:
    ok(f"All {len(new_exports)} new exports present in hive.__init__")
else:
    fail(f"Missing exports: {missing}")

# Sub-package imports
try:
    from hive.stt import (
        STTProvider, TranscriptionResult, WhisperLocal, GroqSTT,
        DeepgramSTT, create_stt_provider, AudioRecorder,
    )
    from hive.routing import IntentRouter, IntentResult
    from hive.triggers import HotkeyTrigger, WebhookTrigger, Trigger
    from hive.tools.links import LinkToolkit
    ok("All sub-package imports succeed")
except ImportError as e:
    fail("Sub-package import failed", e)


# ── 2. STT Providers ────────────────────────────────────────────────────────

section("2. STT Providers")

from hive.stt.recorder import _write_wav as _write_wav_fn

# TranscriptionResult
r = TranscriptionResult(text="hello", language="en", duration_ms=1500, provider="test")
assert r.text == "hello" and r.language == "en" and r.duration_ms == 1500
ok("TranscriptionResult fields + defaults")

# WhisperLocal
from hive.stt.whisper_local import _HAS_MLX_WHISPER, _HAS_FASTER_WHISPER

w = WhisperLocal(model_size="base")
print(f"  ℹ  Platform: {sys.platform}/{platform.machine()}")
print(f"  ℹ  mlx-whisper: {_HAS_MLX_WHISPER}, faster-whisper: {_HAS_FASTER_WHISPER}")
print(f"  ℹ  WhisperLocal backend={w._backend!r}, available={w.available}")

if w.available:
    ok(f"WhisperLocal available with backend={w._backend!r}")
else:
    skip("WhisperLocal not available", "install mlx-whisper or faster-whisper")

# Test WhisperLocal with mocked mlx backend
mock_mod = MagicMock()
mock_mod.transcribe.return_value = {"text": " mocked transcription ", "language": "en"}
w_mock = WhisperLocal(model_size="tiny")
w_mock._backend = "mlx"
w_mock._model = "mlx-community/whisper-tiny"


async def _test_whisper_mock() -> None:
    with patch("hive.stt.whisper_local._mlx_whisper_mod", mock_mod):
        tmp = Path(tempfile.mktemp(suffix=".wav"))
        tmp.write_bytes(b"fake")
        result = await w_mock.transcribe(tmp)
        tmp.unlink()
        assert result.text == "mocked transcription"
        assert result.provider == "mlx-whisper"
        ok("WhisperLocal mlx transcribe (mocked)")


asyncio.run(_test_whisper_mock())

# Test WhisperLocal with mocked faster backend
mock_seg = MagicMock()
mock_seg.text = " faster result"
mock_info = MagicMock()
mock_info.language = "fr"
mock_info.duration = 3.2
mock_model = MagicMock()
mock_model.transcribe.return_value = ([mock_seg], mock_info)

w_faster = WhisperLocal(model_size="small")
w_faster._backend = "faster"
w_faster._model = mock_model


async def _test_faster_mock() -> None:
    tmp = Path(tempfile.mktemp(suffix=".wav"))
    tmp.write_bytes(b"fake")
    result = await w_faster.transcribe(tmp)
    tmp.unlink()
    assert result.text == "faster result"
    assert result.language == "fr"
    assert result.duration_ms == 3200
    assert result.provider == "faster-whisper"
    ok("WhisperLocal faster-whisper transcribe (mocked)")


asyncio.run(_test_faster_mock())

# GroqSTT
g = GroqSTT(api_key="test-key")
assert g.available
with patch.dict(os.environ, {}, clear=True):
    g_empty = GroqSTT(api_key="")
    assert not g_empty.available
ok("GroqSTT availability detection (with/without key)")

# Test GroqSTT with mocked HTTP
mock_resp = MagicMock(spec=httpx.Response)
mock_resp.json.return_value = {"text": " groq result ", "language": "en", "duration": 2.0}
mock_resp.raise_for_status = MagicMock()
mock_client = AsyncMock()
mock_client.post.return_value = mock_resp
mock_client.__aenter__ = AsyncMock(return_value=mock_client)
mock_client.__aexit__ = AsyncMock(return_value=False)


async def _test_groq_mock() -> None:
    with patch("hive.stt.groq_stt.httpx.AsyncClient", return_value=mock_client):
        tmp = Path(tempfile.mktemp(suffix=".wav"))
        tmp.write_bytes(b"audio")
        result = await GroqSTT(api_key="k").transcribe(tmp)
        tmp.unlink()
        assert result.text == "groq result"
        assert result.provider == "groq"
        assert result.duration_ms == 2000
        ok("GroqSTT transcribe (mocked HTTP)")


asyncio.run(_test_groq_mock())

# Live GroqSTT test
groq_key = os.environ.get("GROQ_API_KEY", "")
if groq_key:
    async def _test_groq_live() -> None:
        # Generate a short silent WAV to send
        tmp = Path(tempfile.mktemp(suffix=".wav"))
        _write_wav_fn(tmp, b"\x00\x00" * 8000, sample_rate=16000, channels=1)
        try:
            g_live = GroqSTT(api_key=groq_key)
            result = await g_live.transcribe(tmp)
            ok(f"GroqSTT LIVE: text={result.text!r}, lang={result.language}, dur={result.duration_ms}ms")
        except Exception as e:
            fail("GroqSTT live transcribe", e)
        finally:
            tmp.unlink()

    asyncio.run(_test_groq_live())
else:
    skip("GroqSTT live test", "GROQ_API_KEY not set")

# DeepgramSTT
d = DeepgramSTT(api_key="test-key")
assert d.available
with patch.dict(os.environ, {}, clear=True):
    d_empty = DeepgramSTT(api_key="")
    assert not d_empty.available
ok("DeepgramSTT availability detection (with/without key)")

dg_key = os.environ.get("DEEPGRAM_API_KEY", "")
if dg_key:
    async def _test_deepgram_live() -> None:
        tmp = Path(tempfile.mktemp(suffix=".wav"))
        _write_wav_fn(tmp, b"\x00\x00" * 8000, sample_rate=16000, channels=1)
        try:
            d_live = DeepgramSTT(api_key=dg_key)
            result = await d_live.transcribe(tmp)
            ok(f"DeepgramSTT LIVE: text={result.text!r}, lang={result.language}, dur={result.duration_ms}ms")
        except Exception as e:
            fail("DeepgramSTT live transcribe", e)
        finally:
            tmp.unlink()

    asyncio.run(_test_deepgram_live())
else:
    skip("DeepgramSTT live test", "DEEPGRAM_API_KEY not set")

# Factory
assert isinstance(create_stt_provider("whisper"), WhisperLocal)
assert isinstance(create_stt_provider("groq"), GroqSTT)
assert isinstance(create_stt_provider("deepgram"), DeepgramSTT)
ok("Factory explicit routing (whisper/groq/deepgram)")

try:
    create_stt_provider("nope")
    fail("Factory should reject unknown provider")
except ValueError:
    ok("Factory rejects unknown provider")

# Factory auto-detect
with (
    patch.object(WhisperLocal, "available", new_callable=lambda: property(lambda s: False)),
    patch.dict(os.environ, {"GROQ_API_KEY": "k"}, clear=True),
):
    assert isinstance(create_stt_provider(), GroqSTT)
    ok("Factory auto-detect falls through to GroqSTT")

# Protocol conformance
assert isinstance(GroqSTT(api_key="k"), STTProvider)
assert isinstance(DeepgramSTT(api_key="k"), STTProvider)
ok("Providers satisfy STTProvider protocol")


# ── 3. AudioRecorder ────────────────────────────────────────────────────────

section("3. AudioRecorder")

from hive.stt.recorder import _write_wav

# WAV writing
tmp_wav = Path(tempfile.mktemp(suffix=".wav"))
pcm = b"\x00\x01" * 200
_write_wav(tmp_wav, pcm, sample_rate=16000, channels=1)
content = tmp_wav.read_bytes()
assert content[:4] == b"RIFF"
assert content[8:12] == b"WAVE"
sr = struct.unpack("<I", content[24:28])[0]
assert sr == 16000
tmp_wav.unlink()
ok("WAV file written with correct RIFF/WAVE header and sample rate")

# Mocked recorder lifecycle
mock_sd = MagicMock()
mock_sd.InputStream.return_value = MagicMock()

with patch("hive.stt.recorder.sd", mock_sd), patch("hive.stt.recorder._HAS_SOUNDDEVICE", True):
    rec = AudioRecorder(sample_rate=44100, channels=2)
    assert not rec.is_recording
    ok("AudioRecorder created (not recording)")

    rec.start()
    assert rec.is_recording
    ok("start() sets is_recording=True")

    rec.start()  # idempotent
    assert mock_sd.InputStream.call_count == 1
    ok("start() is idempotent")

    rec._callback(b"\x00" * 100, 50, None, None)
    rec._callback(b"\xff" * 100, 50, None, None)
    assert len(rec._frames) == 2
    ok("Callback captures frames")

    audio = rec.stop()
    assert len(audio) == 200
    assert not rec.is_recording
    ok("stop() returns concatenated bytes, clears state")

    rec.start()
    rec._frames = [b"\x00\x00" * 50]
    out = rec.stop_and_save()
    assert out.suffix == ".wav"
    assert out.exists()
    out.unlink()
    ok("stop_and_save() creates WAV file")

# Import error without sounddevice
with patch("hive.stt.recorder._HAS_SOUNDDEVICE", False):
    try:
        AudioRecorder()
        fail("Should raise ImportError without sounddevice")
    except ImportError:
        ok("Raises ImportError with install hint when sounddevice missing")

# Real sounddevice check
try:
    import sounddevice

    ok(f"sounddevice installed: {sounddevice.__version__}")
    real_rec = AudioRecorder(sample_rate=16000, channels=1)
    ok(f"Real AudioRecorder created (sample_rate={real_rec._sample_rate})")

    # Quick record test (100ms)
    real_rec.start()
    assert real_rec.is_recording
    import time as _time
    _time.sleep(0.1)
    audio_data = real_rec.stop()
    assert not real_rec.is_recording
    assert len(audio_data) > 0
    ok(f"Real recording: {len(audio_data)} bytes captured in 100ms")

    # Save to WAV
    real_rec.start()
    _time.sleep(0.1)
    wav_path = real_rec.stop_and_save()
    assert wav_path.exists()
    wav_size = wav_path.stat().st_size
    wav_path.unlink()
    ok(f"Real WAV saved: {wav_size} bytes")
except ImportError:
    skip("Real sounddevice test", "not installed")
except Exception as e:
    fail("Real sounddevice test", e)


# ── 4. IntentRouter ──────────────────────────────────────────────────────────

section("4. IntentRouter")

from hive.routing.router import IntentClassification
from hive.runtime.types import Message

INTENTS = {
    "task": "user wants to create a todo item",
    "note": "user wants to save information",
    "query": "user is asking a question",
    "agent": "user needs multi-step help",
    "link": "user wants to save a URL",
}


def _mock_structured(intent: str, confidence: float) -> MagicMock:
    """Mock provider that returns structured output."""
    p = MagicMock()
    p.generate_structured = AsyncMock(
        return_value=IntentClassification(intent=intent, confidence=confidence)
    )
    p.generate = AsyncMock(return_value=Message.assistant(intent))
    return p


def _mock_text_only(text: str) -> MagicMock:
    """Mock provider that fails structured, falls back to text."""
    p = MagicMock()
    p.generate_structured = AsyncMock(side_effect=Exception("not supported"))
    p.generate = AsyncMock(return_value=Message.assistant(text))
    return p


async def _test_router() -> None:
    # Structured output path
    r = IntentRouter(model=_mock_structured("task", 0.95), intents=INTENTS)
    res = await r.classify("add a todo for tomorrow")
    assert res.intent == "task" and res.confidence == 0.95
    ok(f"Structured classification: intent={res.intent}, conf={res.confidence}")

    r2 = IntentRouter(model=_mock_structured("query", 0.8), intents=INTENTS)
    res2 = await r2.classify("what is python?")
    assert res2.intent == "query" and res2.confidence == 0.8
    ok("Structured output query classification")

    # Unknown intent in structured output falls back
    r3 = IntentRouter(model=_mock_structured("dance", 0.9), intents=INTENTS)
    res3 = await r3.classify("let's dance")
    assert res3.intent == "task" and res3.confidence == 0.0
    ok("Unknown intent in structured output triggers fallback")

    # Text fallback — structured fails, name match works
    r4 = IntentRouter(model=_mock_text_only("user wants a note"), intents=INTENTS)
    res4 = await r4.classify("remember this")
    assert res4.intent == "note" and res4.confidence == 0.5
    ok("Text fallback: fuzzy name matching")

    # Text fallback — garbage response
    r5 = IntentRouter(model=_mock_text_only("???"), intents=INTENTS, fallback="query")
    res5 = await r5.classify("asdkfj")
    assert res5.intent == "query" and res5.confidence == 0.0
    ok("Text fallback: garbage → configured fallback")

    # Default fallback = first intent
    r6 = IntentRouter(model=_mock_text_only("gibberish"), intents=INTENTS)
    res6 = await r6.classify("xyz")
    assert res6.intent == "task"
    ok("Default fallback = first intent in dict")

    # Pydantic validation
    ic = IntentClassification(intent="task", confidence=0.9)
    assert ic.intent == "task"
    d = ic.model_dump()
    assert d["confidence"] == 0.9
    ok("IntentClassification Pydantic model works")

    from pydantic import ValidationError
    try:
        IntentClassification(intent="task", confidence=1.5)
        fail("Should reject confidence > 1.0")
    except ValidationError:
        ok("IntentClassification rejects confidence > 1.0")

    try:
        IntentClassification(intent="task", confidence=-0.1)
        fail("Should reject confidence < 0.0")
    except ValidationError:
        ok("IntentClassification rejects confidence < 0.0")

    # IntentResult Pydantic model
    ir = IntentResult(intent="link", confidence=0.7, raw_text="save this url")
    assert ir.intent == "link" and ir.raw_text == "save this url"
    d2 = ir.model_dump()
    assert d2["confidence"] == 0.7
    ok("IntentResult Pydantic model works")


asyncio.run(_test_router())


# ── 5. Triggers ──────────────────────────────────────────────────────────────

section("5. Triggers")

# WebhookTrigger
assert isinstance(WebhookTrigger(), Trigger)
ok("WebhookTrigger satisfies Trigger protocol")


async def _test_webhook() -> None:
    received: list[str] = []
    async_received: list[str] = []

    wh = WebhookTrigger(host="127.0.0.1", port=0)
    wh.register("/sync", lambda b: received.append(b), method="POST", name="sync-hook")
    wh.register("/async", lambda b: async_received.append(b), method="POST")

    assert len(wh.active_triggers) == 2
    ok("Registered 2 webhook routes")

    await wh.start()
    port = wh._server.sockets[0].getsockname()[1]
    ok(f"Webhook server started on port {port}")

    async with httpx.AsyncClient() as client:
        r1 = await client.post(f"http://127.0.0.1:{port}/sync", content="payload-1")
        assert r1.status_code == 200
        ok("POST /sync → 200 OK")

        r2 = await client.post(f"http://127.0.0.1:{port}/async", content="payload-2")
        assert r2.status_code == 200
        ok("POST /async → 200 OK")

        r3 = await client.get(f"http://127.0.0.1:{port}/nope")
        assert r3.status_code == 404
        ok("GET /nope → 404 Not Found")

    await wh.stop()
    assert wh._server is None
    ok("Server stopped cleanly")

    assert received == ["payload-1"]
    assert async_received == ["payload-2"]
    ok("Both callbacks received correct payloads")


asyncio.run(_test_webhook())

# HotkeyTrigger (mocked)
mock_kb = MagicMock()
mock_kb.Key.cmd = "CMD"
mock_kb.Key.shift = "SHIFT"
mock_kb.Key.ctrl = "CTRL"
mock_kb.Key.alt = "ALT"
mock_kb.KeyCode.from_char.return_value = "M"

mod_attrs = {"cmd": "CMD", "ctrl": "CTRL", "alt": "ALT", "shift": "SHIFT"}

with (
    patch("hive.triggers.hotkey._HAS_PYNPUT", True),
    patch("hive.triggers.hotkey.keyboard", mock_kb),
    patch("hive.triggers.hotkey._MODIFIER_ATTRS", mod_attrs),
):
    ht = HotkeyTrigger()
    ok("HotkeyTrigger created (mocked pynput)")

    t1 = ht.register("cmd+shift+m", lambda: None, name="mic")
    t2 = ht.register("ctrl+m", lambda: None, name="mute")
    assert len(ht.active_triggers) == 2
    ok("Registered 2 hotkeys")

    names = {t["name"] for t in ht.active_triggers}
    assert names == {"mic", "mute"}
    ok(f"Active triggers: {names}")

    ht.unregister(t1)
    assert len(ht.active_triggers) == 1
    ok("Unregistered 'mic', 1 remaining")

    # Test _on_press fires callback
    fired = []
    t3 = ht.register("cmd+m", lambda: fired.append(True), name="fire-test")
    trigger_info = ht._triggers[t3]
    ht._pressed = {"CMD"}  # simulate cmd held
    ht._on_press("M")  # press the trigger key

    import time
    time.sleep(0.1)  # callback fires in a thread
    assert len(fired) == 1
    ok("Hotkey callback fires on key press (simulated)")

# Real pynput check
try:
    from pynput import keyboard as _real_kb

    ok(f"pynput installed: {_real_kb.__name__}")
    real_ht = HotkeyTrigger()
    t_id = real_ht.register("cmd+shift+m", lambda: print("hotkey!"), name="mic-test")
    ok(f"Real HotkeyTrigger: registered cmd+shift+m")

    real_ht.start()
    ok("Real HotkeyTrigger listener started")

    import time as _t2
    _t2.sleep(0.05)
    real_ht.stop()
    ok("Real HotkeyTrigger listener stopped cleanly")
except ImportError:
    skip("Real pynput test", "not installed")
except Exception as e:
    fail("Real pynput test", e)


# ── 6. LinkToolkit ───────────────────────────────────────────────────────────

section("6. LinkToolkit")

from hive.memory.semantic import SemanticMemory


async def _test_links() -> None:
    tmp = Path(tempfile.mkdtemp())
    memory = SemanticMemory(tmp, "test-agent")
    tk = LinkToolkit(memory=memory)
    tk.bind("test-agent")

    # Tool discovery
    tools = tk.get_tools()
    tool_names = sorted(t.name for t in tools)
    assert tool_names == ["list_links", "save_link", "scrape_link", "search_links"]
    ok(f"4 tools discovered: {tool_names}")

    assert tk.instructions != ""
    ok(f"Instructions: '{tk.instructions}'")

    # save_link with mocked HTTP
    html = '<html><head><title>Test Page</title></head><body><p>Content</p></body></html>'
    mock_r = MagicMock()
    mock_r.text = html
    mock_r.headers = {"content-type": "text/html"}
    mock_r.raise_for_status = MagicMock()

    with patch("hive.tools.links.toolkit.httpx.get", return_value=mock_r):
        res = await tk.save_link("https://example.com", tags="test,demo", notes="A note")
    assert "Saved link" in res and "Test Page" in res
    ok(f"save_link: {res}")

    # save another
    html2 = '<html><head><title>Rust Book</title></head><body><p>Learn Rust</p></body></html>'
    mock_r2 = MagicMock()
    mock_r2.text = html2
    mock_r2.headers = {"content-type": "text/html"}
    mock_r2.raise_for_status = MagicMock()

    with patch("hive.tools.links.toolkit.httpx.get", return_value=mock_r2):
        res2 = await tk.save_link("https://doc.rust-lang.org", tags="rust")
    ok(f"save_link #2: {res2}")

    # Store a non-link to test filtering
    await memory.store("Just a plain note", {"type": "note"})

    # search_links
    search = await tk.search_links("example")
    assert "example.com" in search.lower() or "Test Page" in search
    assert "plain note" not in search
    ok(f"search_links filters by type=link")

    # list_links
    links = await tk.list_links()
    assert "rust-lang" in links.lower() or "Rust Book" in links
    ok(f"list_links shows recent links")

    # Empty search
    empty = await tk.search_links("xyznonexistent12345")
    assert "No matching" in empty
    ok("Empty search returns 'No matching links'")

    # scrape_link
    html3 = '<html><body><h1>Heading</h1><p>Paragraph text.</p></body></html>'
    mock_r3 = MagicMock()
    mock_r3.text = html3
    mock_r3.headers = {"content-type": "text/html"}
    mock_r3.raise_for_status = MagicMock()

    with patch("hive.tools.links.toolkit.httpx.get", return_value=mock_r3):
        scraped = tk.scrape_link("https://example.com/page")
    assert "Heading" in scraped and "Paragraph" in scraped
    ok(f"scrape_link returns markdown: '{scraped[:60]}...'")

    # scrape error
    with patch("hive.tools.links.toolkit.httpx.get", side_effect=httpx.RequestError("boom")):
        err = tk.scrape_link("https://broken.com")
    assert "Request failed" in err
    ok(f"scrape_link error: {err}")

    # save with fetch failure still saves
    with patch("hive.tools.links.toolkit.httpx.get", side_effect=httpx.RequestError("dns")):
        res3 = await tk.save_link("https://unreachable.com")
    assert "Saved link" in res3
    ok("save_link gracefully handles fetch failure")

    # Standalone mode
    tmp2 = Path(tempfile.mkdtemp())
    tk2 = LinkToolkit(memory_dir=tmp2)
    tk2.bind("standalone-agent")
    assert tk2._memory is not None
    ok("Standalone mode (memory_dir) creates memory on bind")

    # Rebind
    tk2.rebind("other-agent")
    assert tk2._memory is not None
    ok("rebind() works for server mode")

    # Requires args
    try:
        LinkToolkit()
        fail("Should raise ValueError without args")
    except ValueError:
        ok("Raises ValueError without memory or memory_dir")

    # Not bound
    tk3 = LinkToolkit(memory_dir=tmp2)
    try:
        await tk3.save_link("https://x.com")
        fail("Should raise RuntimeError when not bound")
    except RuntimeError as e:
        assert "not bound" in str(e)
        ok("Raises RuntimeError when not bound to agent")


asyncio.run(_test_links())


# ── 7. Integration: Agent with LinkToolkit ───────────────────────────────────

section("7. Agent + LinkToolkit Integration")

from hive import Agent, Instructions, TaskToolkit, KnowledgeToolkit


async def _test_agent_integration() -> None:
    tmp = Path(tempfile.mkdtemp())
    agent = Agent(
        name="test-agent",
        model=_mock_text_only("I saved the link for you."),
        instructions="You are a test assistant.",
        toolkits=[
            LinkToolkit(memory_dir=tmp),
            KnowledgeToolkit(memory_dir=tmp),
            TaskToolkit(db_path=tmp / "tasks.db"),
        ],
    )

    all_tools = agent.get_tools()
    tool_names = sorted(t.name for t in all_tools)
    link_tools = [n for n in tool_names if "link" in n]
    assert len(link_tools) == 4
    ok(f"Agent has {len(all_tools)} tools total, {len(link_tools)} link tools")

    knowledge_tools = [n for n in tool_names if "note" in n]
    assert len(knowledge_tools) >= 1
    ok(f"Agent also has knowledge tools: {knowledge_tools}")

    task_tools = [n for n in tool_names if "task" in n]
    assert len(task_tools) >= 1
    ok(f"Agent also has task tools: {task_tools}")

    print(f"  ℹ  All tools: {tool_names}")


asyncio.run(_test_agent_integration())


# ── 8. Daemon Integration Check ─────────────────────────────────────────────

section("8. Daemon Integration")

from hive.daemon.loop import HiveDaemon

# Verify LinkToolkit is in _build_toolkits
import inspect

source = inspect.getsource(HiveDaemon._build_toolkits)
assert "LinkToolkit" in source
ok("LinkToolkit present in HiveDaemon._build_toolkits()")

from hive.tools.links import LinkToolkit as LT_check

assert LT_check is LinkToolkit
ok("hive.tools.links exports LinkToolkit correctly")


# ── 9. pyproject.toml Extras ────────────────────────────────────────────────

section("9. pyproject.toml Optional Deps")

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

pyproject = Path(__file__).parent.parent / "pyproject.toml"
with open(pyproject, "rb") as f:
    cfg = tomllib.load(f)

extras = cfg.get("project", {}).get("optional-dependencies", {})
assert "audio" in extras
assert "hotkeys" in extras
assert "voice" in extras
assert any("sounddevice" in d for d in extras["audio"])
assert any("scipy" in d for d in extras["audio"])
assert any("pynput" in d for d in extras["hotkeys"])
assert any("hive-agent[audio,hotkeys]" in d for d in extras["voice"])
ok(f"Optional deps defined: {list(extras.keys())}")

# mypy overrides
overrides = cfg.get("tool", {}).get("mypy", {}).get("overrides", [])
if overrides:
    modules = []
    for o in overrides:
        modules.extend(o.get("module", []))
    for mod in ["mlx_whisper.*", "faster_whisper.*", "sounddevice.*", "pynput.*"]:
        assert mod in modules, f"Missing mypy override for {mod}"
    ok(f"mypy overrides include all optional dep modules")
else:
    fail("No mypy overrides found")


# ── Summary ──────────────────────────────────────────────────────────────────

section("SUMMARY")
total = PASS + FAIL + SKIP
print(f"  \033[32m{PASS} passed\033[0m, \033[31m{FAIL} failed\033[0m, \033[33m{SKIP} skipped\033[0m (total: {total})")

if FAIL == 0:
    print(f"\n  \033[32m{'═' * 40}\033[0m")
    print(f"  \033[32m  ALL CHECKS PASSED — ready to ship 0.3.2\033[0m")
    print(f"  \033[32m{'═' * 40}\033[0m")
else:
    print(f"\n  \033[31m{'═' * 40}\033[0m")
    print(f"  \033[31m  {FAIL} FAILURE(S) — fix before shipping\033[0m")
    print(f"  \033[31m{'═' * 40}\033[0m")
    sys.exit(1)
