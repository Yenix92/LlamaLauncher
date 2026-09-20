"""llama-server Launcher shared backend core.

Used by BOTH the web version (app.py) and the standalone native GUI
(native_gui.py). This module must stay free of web-framework imports
(no FastAPI / uvicorn / requests at module level) so the native exe
stays lightweight and portable.

Contents:
  - VERSION, paths, settings.json load/save (atomic)
  - ServerManager: process lifecycle + log pipeline (thread-safe,
    listener-based so both asyncio (web) and tkinter (native) can
    consume lines/states without blocking the reader thread)
  - GPU monitor chain: pynvml -> nvidia-smi CSV -> None
  - get_monitor(): cpu / mem / gpu / server-process snapshot
  - get_server_info(): /health + /slots + /metrics scrape
  - scan_files(): recursive .gguf/.exe scan (depth <= 3, <= 200)
  - port_in_use()
  - build_argv() / tokenize() / quote_arg() / shlex_join():
    Python port of the frontend buildArgv() (SPEC 2.2) — the native
    GUI uses this as its single authoritative command builder, exactly
    mirroring the web frontend behaviour.
"""

import collections
import json
import os
import re
import subprocess
import sys
import threading

VERSION = "1.0"

# ---------------------------------------------------------------------------
# Paths (SPEC section 1)
# ---------------------------------------------------------------------------
APP_DIR = os.path.dirname(os.path.abspath(__file__))
_FROZEN = getattr(sys, "frozen", False)

if _FROZEN:
    # PyInstaller: settings.json lives next to the .exe (writable),
    # static assets come from the temp bundle (web version only).
    WRITABLE_DIR = os.path.dirname(sys.executable)
else:
    WRITABLE_DIR = APP_DIR

SETTINGS_PATH = os.path.join(WRITABLE_DIR, "settings.json")

# Windows: prevent child processes (llama-server, nvidia-smi) from opening
# a console window. getattr keeps this a no-op (0) on Linux/macOS.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------------------------------------------------------------------------
# Settings (SPEC 2.4)
# ---------------------------------------------------------------------------
def default_settings():
    return {
        "version": 1,
        "language": "zh",
        "theme": "dark",
        "serverExe": "",
        "lastModel": "",
        "global": {"host": "127.0.0.1", "port": 8080, "apiKey": ""},
        "models": {},  # key=模型绝对路径 -> {"mmproj": "", "params": {...}, "extraArgs": ""}
    }


def save_settings(data):
    """Atomic write: tmp file + os.replace, UTF-8."""
    tmp_path = SETTINGS_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
    os.replace(tmp_path, SETTINGS_PATH)


def load_settings():
    """Load settings.json; create+persist defaults when missing/corrupt."""
    if not os.path.isfile(SETTINGS_PATH):
        data = default_settings()
        try:
            save_settings(data)
        except Exception:
            pass
        return data
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default_settings()


# ---------------------------------------------------------------------------
# Server process manager + log pipeline (SPEC 1.2)
# ---------------------------------------------------------------------------
READY_MARKERS = ("listening", "server is listening", "all slots are idle")


def is_ready_line(line):
    low = line.lower()
    return any(marker in low for marker in READY_MARKERS)


class ServerManager:
    """llama-server process manager. Thread-safe.

    The stdout reader runs on a worker thread and calls registered
    listeners from that thread. Listeners must be non-blocking
    (enqueue / schedule) — e.g. the web version pushes into an
    asyncio queue, the native GUI schedules a tkinter update.
    """

    def __init__(self):
        self.proc = None
        self.state = "stopped"  # stopped | starting | running | exited
        self.argv = []
        self.exit_code = None
        self.history = collections.deque(maxlen=2000)  # log line buffer
        self._line_listeners = []
        self._state_listeners = []
        self._lock = threading.Lock()

    # -- subscriptions ----------------------------------------------------
    def on_line(self, cb):
        """Register cb(line) for every stdout line (reader thread)."""
        with self._lock:
            self._line_listeners.append(cb)

    def on_state(self, cb):
        """Register cb({"state","pid","exitCode"}) for state changes."""
        with self._lock:
            self._state_listeners.append(cb)

    def _emit_line(self, line):
        for cb in list(self._line_listeners):
            try:
                cb(line)
            except Exception:
                pass

    def _emit_state(self, state, pid, exit_code):
        for cb in list(self._state_listeners):
            try:
                cb({"state": state, "pid": pid, "exitCode": exit_code})
            except Exception:
                pass

    # -- lifecycle ----------------------------------------------------------
    def start(self, argv):
        """Start llama-server. Returns (ok, error, pid)."""
        if self.proc is not None and self.proc.poll() is None:
            return False, "already_running", None
        try:
            proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception as e:
            return False, str(e), None
        self.proc = proc
        self.argv = list(argv)
        self.exit_code = None
        self.state = "starting"
        threading.Thread(target=self._reader, args=(proc,), daemon=True).start()
        self._emit_state("starting", proc.pid, None)
        return True, None, proc.pid

    def stop(self):
        """Kill the server (and children) if running. Always returns True."""
        proc = self.proc
        if proc is not None and proc.poll() is None:
            try:
                import psutil
                parent = psutil.Process(proc.pid)
                for child in parent.children(recursive=True):
                    try:
                        child.kill()
                    except Exception:
                        pass
                try:
                    parent.kill()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=5)
                except Exception:
                    pass
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        return True

    def status(self):
        pid = self.proc.pid if self.proc is not None else None
        return {"state": self.state, "pid": pid, "argv": list(self.argv),
                "exitCode": self.exit_code}

    # -- reader ---------------------------------------------------------------
    def _reader(self, proc):
        try:
            for raw in proc.stdout:
                line = raw.rstrip("\r\n")
                self.history.append(line)
                self._emit_line(line)
                if self.state == "starting" and is_ready_line(line):
                    self.state = "running"
                    self._emit_state("running", proc.pid, None)
        except Exception:
            pass
        finally:
            try:
                code = proc.wait()
            except Exception:
                code = None
            self.exit_code = code
            if self.state in ("starting", "running"):
                self.state = "exited"
                self._emit_state("exited", proc.pid, code)


# Module-level singleton shared by web + native frontends.
mgr = ServerManager()


# ---------------------------------------------------------------------------
# GPU monitoring (SPEC 1.3): pynvml -> nvidia-smi CSV -> None
# ---------------------------------------------------------------------------
_gpu_state = {"checked": False, "mode": "none", "pynvml": None, "handle": None}
_gpu_lock = threading.Lock()

_SMI_CMD = [
    "nvidia-smi",
    "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
    "--format=csv,noheader,nounits",
]


def _smi_read():
    """Parse first line of nvidia-smi csv output -> gpu dict or None."""
    try:
        r = subprocess.run(_SMI_CMD, capture_output=True, text=True, timeout=8,
                           creationflags=CREATE_NO_WINDOW)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        parts = [p.strip() for p in r.stdout.strip().splitlines()[0].split(",")]
        if len(parts) < 6:
            return None

        def _f(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return None

        return {"name": parts[0], "util": _f(parts[1]), "memUsed": _f(parts[2]),
                "memTotal": _f(parts[3]), "temp": _f(parts[4]), "power": _f(parts[5])}
    except Exception:
        return None


def _gpu_init():
    """One-time GPU backend detection, result cached globally."""
    with _gpu_lock:
        if _gpu_state["checked"]:
            return
        _gpu_state["checked"] = True
        try:
            import pynvml
            pynvml.nvmlInit()
            _gpu_state["pynvml"] = pynvml
            _gpu_state["handle"] = pynvml.nvmlDeviceGetHandleByIndex(0)
            _gpu_state["mode"] = "pynvml"
            return
        except Exception:
            pass
        if _smi_read() is not None:
            _gpu_state["mode"] = "nvidia-smi"
        else:
            _gpu_state["mode"] = "none"


def _pynvml_read():
    try:
        nv = _gpu_state["pynvml"]
        h = _gpu_state["handle"]
        name = nv.nvmlDeviceGetName(h)
        if isinstance(name, bytes):
            name = name.decode("utf-8", "replace")
        util = float(nv.nvmlDeviceGetUtilizationRates(h).gpu)
        mem = nv.nvmlDeviceGetMemoryInfo(h)
        mem_used = round(mem.used / (1024 * 1024))
        mem_total = round(mem.total / (1024 * 1024))
        try:
            temp = float(nv.nvmlDeviceGetTemperature(h, nv.NVML_TEMPERATURE_GPU))
        except Exception:
            temp = None
        try:
            power = float(nv.nvmlDeviceGetPowerUsage(h)) / 1000.0
        except Exception:
            power = None
        return {"name": name, "util": util, "memUsed": mem_used,
                "memTotal": mem_total, "temp": temp, "power": power}
    except Exception:
        return None


def get_gpu():
    """Best-effort GPU snapshot dict or None. Never raises."""
    try:
        _gpu_init()
        if _gpu_state["mode"] == "pynvml":
            gpu = _pynvml_read()
            if gpu is not None:
                return gpu
            return _smi_read()  # pynvml read failed -> nvidia-smi fallback
        if _gpu_state["mode"] == "nvidia-smi":
            return _smi_read()
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# System monitor snapshot (SPEC 1.3)
# ---------------------------------------------------------------------------
def get_monitor():
    """CPU / memory / GPU / server-process snapshot. Never raises 500;
    every subsystem is guarded independently."""
    import psutil

    out = {"cpu": None, "mem": None, "gpu": None, "server": None}
    try:
        out["cpu"] = {"percent": psutil.cpu_percent(interval=None)}
    except Exception:
        pass
    try:
        vm = psutil.virtual_memory()
        out["mem"] = {"total": int(vm.total), "used": int(vm.used),
                      "percent": float(vm.percent)}
    except Exception:
        pass
    try:
        out["gpu"] = get_gpu()
    except Exception:
        out["gpu"] = None
    try:
        if mgr.proc is not None and mgr.proc.poll() is None:
            rss = 0
            try:
                p = psutil.Process(mgr.proc.pid)
                rss += p.memory_info().rss
                for child in p.children(recursive=True):
                    try:
                        rss += child.memory_info().rss
                    except Exception:
                        pass
            except Exception:
                pass
            out["server"] = {"pid": mgr.proc.pid, "rss": rss}
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# /health + /slots + /metrics scrape (SPEC 1.4)
# ---------------------------------------------------------------------------
_METRIC_RE = re.compile(r"^llamacpp:([a-z_:]+)\s+([0-9.eE+-]+)$", re.MULTILINE)


def get_server_info(host="127.0.0.1", port=8080):
    """Query the running llama-server. Returns {"ok":...} dict. Never raises."""
    import requests

    base = "http://%s:%s" % (host, port)
    try:
        hr = requests.get(base + "/health", timeout=2)
        try:
            body = hr.json()
        except Exception:
            body = hr.text
        health = {"code": hr.status_code, "body": body}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    slots = None
    try:
        slots = requests.get(base + "/slots", timeout=2).json()
    except Exception:
        pass

    raw = {}
    try:
        mr = requests.get(base + "/metrics", timeout=2)
        for m in _METRIC_RE.finditer(mr.text):
            try:
                raw[m.group(1)] = float(m.group(2))
            except ValueError:
                pass
    except Exception:
        pass

    metrics = {
        "promptTokensTotal": int(raw.get("prompt_tokens_total") or 0),
        "tokensPredictedTotal": int(raw.get("tokens_predicted_total") or 0),
        "promptTokPerSec": raw.get("prompt_tokens_seconds"),
        "predictedTokPerSec": raw.get("predicted_tokens_seconds"),
        "requestsProcessing": int(raw.get("requests_processing") or 0),
        "nDecodeTotal": int(raw.get("n_decode_total") or 0),
        "specDraftTokensTotal": int(raw.get("spec_draft_tokens_total") or 0),
        "specAcceptedTokensTotal": int(raw.get("spec_accepted_tokens_total") or 0),
    }
    return {"ok": True, "health": health, "slots": slots, "metrics": metrics}


# ---------------------------------------------------------------------------
# File scan + port check
# ---------------------------------------------------------------------------
def scan_files(dir_path, kind="gguf"):
    """Recursive scan, depth <= 3 levels, <= 200 entries, mtime desc."""
    if kind not in ("gguf", "exe") or not dir_path:
        return []
    if not os.path.isdir(dir_path):
        return []
    suffix = ".gguf" if kind == "gguf" else ".exe"
    found = []  # (mtime, path)

    def _onerror(_err):
        pass

    for root, dirs, files in os.walk(dir_path, onerror=_onerror):
        rel = os.path.relpath(root, dir_path)
        depth = 0 if rel == os.curdir else len(rel.split(os.sep))
        if depth >= 3:
            dirs[:] = []  # do not descend deeper than 3 levels
        for name in files:
            if not name.lower().endswith(suffix):
                continue
            full = os.path.join(root, name)
            try:
                found.append((os.path.getmtime(full), full))
            except OSError:
                continue
    found.sort(key=lambda item: item[0], reverse=True)
    return [path for _mtime, path in found[:200]]


def port_in_use(port, host="127.0.0.1"):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


# ---------------------------------------------------------------------------
# Command building (SPEC 2.2) — Python port of the frontend buildArgv()
# ---------------------------------------------------------------------------
# key -> (min, max, step, default); mirrors PARAM_DEFS in static/app.js
PARAM_DEFS = {
    "temperature":      (0, 2, 0.01, 0.8),
    "top_k":            (0, 200, 1, 40),
    "top_p":            (0, 1, 0.01, 0.95),
    "min_p":            (0, 1, 0.01, 0.05),
    "seed":             (-1, 999999, 1, -1),
    "ctx_size":         (512, 262144, 512, 4096),
    "batch_size":       (32, 8192, 32, 2048),
    "ubatch_size":      (32, 4096, 32, 512),
    "threads":          (-1, 64, 1, -1),
    "parallel":         (1, 16, 1, 1),
    "n_gpu_layers":     (-1, 200, 1, -1),
    "spec_draft_n_max": (1, 16, 1, 2),
    "spec_draft_p_min": (0, 1, 0.01, 0.5),
    "reasoningBudget":  (-1, 65536, 1, -1),
}

# Mirrors DEFAULT_PARAMS in static/app.js (used to merge stored presets).
DEFAULT_PARAMS = {
    "temperature": 0.8, "top_k": 40, "top_p": 0.95, "min_p": 0.05, "seed": -1,
    "ctx_size": 4096, "batch_size": 2048, "ubatch_size": 512, "threads": -1,
    "parallel": 1, "n_gpu_layers": -1, "cache_type_k": "f16",
    "cache_type_v": "f16", "flash_attn": "auto", "mlock": False,
    "no_mmap": False, "cont_batching": True, "jinja": False, "metrics": False,
    "specType": "none", "spec_draft_n_max": 2, "spec_draft_p_min": 0.5,
    "reasoning": "auto", "reasoningBudget": -1,
}

# Dropdown keys and their option lists (mirrors static/app.js).
SELECT_KEYS = {
    "cache_type_k": ["f32", "f16", "bf16", "q8_0", "q4_0", "q4_1",
                     "iq4_nl", "q5_0", "q5_1"],
    "cache_type_v": ["f32", "f16", "bf16", "q8_0", "q4_0", "q4_1",
                     "iq4_nl", "q5_0", "q5_1"],
    "flash_attn": ["auto", "on", "off"],
    "specType": ["none", "draft-mtp", "ngram-simple", "ngram-mod"],
    "reasoning": ["auto", "on", "off"],
}

# Boolean toggle keys (mirrors static/app.js).
SWITCH_KEYS = ["mlock", "no_mmap", "cont_batching", "jinja", "metrics"]

# Chinese display labels (native GUI); mirrors i18n.js zh strings.
PARAM_LABELS = {
    "temperature": "温度 (temperature)",
    "top_k": "Top K",
    "top_p": "Top P",
    "min_p": "Min P",
    "seed": "随机种子 (-1=随机)",
    "ctx_size": "上下文长度 (ctx-size)",
    "batch_size": "批大小 (batch-size)",
    "ubatch_size": "微批大小 (ubatch-size)",
    "threads": "线程数 (-1=自动)",
    "parallel": "并发槽位 (parallel)",
    "n_gpu_layers": "GPU 卸载层数 (-1=全部)",
    "cache_type_k": "K 缓存类型",
    "cache_type_v": "V 缓存类型",
    "flash_attn": "Flash Attention",
    "mlock": "锁定内存 (--mlock)",
    "no_mmap": "禁用 mmap (--no-mmap)",
    "cont_batching": "连续批处理",
    "jinja": "Jinja 模板",
    "metrics": "暴露 metrics 端点",
    "specType": "推测解码 (spec-type)",
    "spec_draft_n_max": "草稿最大 token 数",
    "spec_draft_p_min": "草稿最小概率",
    "reasoning": "推理模式 (reasoning)",
    "reasoningBudget": "推理预算 (-1=自动)",
    "host": "监听地址 (host)",
    "port": "端口 (port)",
    "apiKey": "API 密钥（可空）",
    "extraArgs": "额外参数",
}


def clamp_val(key, raw):
    """Mirror of frontend clampVal: parse, clamp to [min,max], round ints."""
    lo, hi, step, d = PARAM_DEFS[key]
    try:
        v = float(raw)
    except (TypeError, ValueError):
        v = d
    v = min(hi, max(lo, v))
    if step >= 1:
        v = round(v)
    return v


def _fmt4(v):
    """Mirror of JS String(parseFloat(Number(v).toFixed(4))): 4 dp, trim zeros."""
    s = "%.4f" % float(v)
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def fmt_val(key, v):
    step = PARAM_DEFS[key][2]
    if step < 1:
        return _fmt4(v)
    return str(int(round(float(v))))


def tokenize(text):
    """shlex-like tokenizer (mirror of frontend tokenize).

    Supports single/double quotes; backslashes are literal outside double
    quotes (Windows paths), only \\" and \\\\ are escaped inside.
    Guarantees shlex_join(tokenize(x)) round-trips.
    """
    out = []
    cur = ""
    in_s = False
    in_d = False
    has = False
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if in_s:
            if c == "'":
                in_s = False
            else:
                cur += c
        elif in_d:
            if c == '"':
                in_d = False
            elif c == "\\" and i + 1 < n and text[i + 1] in ('"', "\\"):
                cur += text[i + 1]
                i += 1
            else:
                cur += c
        elif c == "'":
            in_s = True
            has = True
        elif c == '"':
            in_d = True
            has = True
        elif c.isspace():
            if has or cur:
                out.append(cur)
                cur = ""
                has = False
        else:
            cur += c
            has = True
        i += 1
    if has or cur:
        out.append(cur)
    return out


def quote_arg(a):
    """Display quoting: args with whitespace/quotes get double quotes."""
    s = str(a)
    if s == "" or re.search(r'[\s"]', s):
        return '"' + s.replace('"', '\\"') + '"'
    return s


def shlex_join(argv):
    """Join argv into a display string (mirror of frontend shlexJoin)."""
    return " ".join(quote_arg(a) for a in argv)


def dedupe_extra(ui_argv, extra_tokens):
    """UI params win; extraArgs dedupe first-come-first-served.

    Returns (argv, ignored): ignored entries are "flag" or "flag value".
    """
    seen = {a for a in ui_argv if a.startswith("-")}
    argv = list(ui_argv)
    ignored = []
    i, n = 0, len(extra_tokens)
    while i < n:
        tk = extra_tokens[i]
        if tk.startswith("-"):
            if tk in seen:
                s = tk
                if i + 1 < n and not extra_tokens[i + 1].startswith("-"):
                    s += " " + extra_tokens[i + 1]
                    i += 1
                ignored.append(s)
                i += 1
                continue
            seen.add(tk)
        argv.append(tk)  # new flag or lone token kept as-is
        i += 1
    return argv, ignored


def build_argv(server_exe, model_path, params, mmproj="", extra_args="",
               host="127.0.0.1", port=8080, api_key=""):
    """Single authoritative command builder (mirror of frontend buildArgv).

    params: dict with the PARAM_DEFS keys + SELECT_KEYS + SWITCH_KEYS
    (missing keys fall back to DEFAULT_PARAMS). Returns (argv, ignored).
    """
    p = dict(DEFAULT_PARAMS)
    p.update(params or {})
    for key in PARAM_DEFS:
        p[key] = clamp_val(key, p[key])

    argv = []
    argv.append(server_exe.strip())
    argv.extend(["-m", model_path.strip()])
    if mmproj.strip():
        argv.extend(["--mmproj", mmproj.strip()])
    argv.extend(["--host", str(host), "--port", str(port)])
    if api_key:
        argv.extend(["--api-key", api_key])
    argv.extend(["--temp", fmt_val("temperature", p["temperature"])])
    argv.extend(["--top-k", fmt_val("top_k", p["top_k"])])
    argv.extend(["--top-p", fmt_val("top_p", p["top_p"])])
    argv.extend(["--min-p", fmt_val("min_p", p["min_p"])])
    if p["seed"] != -1:
        argv.extend(["--seed", str(p["seed"])])
    argv.extend(["--ctx-size", str(p["ctx_size"])])
    argv.extend(["--batch-size", str(p["batch_size"])])
    argv.extend(["--ubatch-size", str(p["ubatch_size"])])
    if p["threads"] > 0:
        argv.extend(["--threads", str(p["threads"])])
    argv.extend(["--n-gpu-layers", str(p["n_gpu_layers"])])
    argv.extend(["--parallel", str(p["parallel"])])
    if p["cache_type_k"] != "f16":
        argv.extend(["--cache-type-k", p["cache_type_k"]])
    if p["cache_type_v"] != "f16":
        argv.extend(["--cache-type-v", p["cache_type_v"]])
    if p["flash_attn"] != "auto":
        argv.extend(["--flash-attn", p["flash_attn"]])
    if p["mlock"]:
        argv.append("--mlock")
    if p["no_mmap"]:
        argv.append("--no-mmap")
    if not p["cont_batching"]:
        argv.append("--no-cont-batching")
    if p["jinja"]:
        argv.append("--jinja")
    if p["metrics"]:
        argv.append("--metrics")
    if p["specType"] != "none":
        argv.extend(["--spec-type", p["specType"]])
        argv.extend(["--spec-draft-n-max", str(p["spec_draft_n_max"])])
        argv.extend(["--spec-draft-p-min", fmt_val("spec_draft_p_min", p["spec_draft_p_min"])])
    if p["reasoning"] != "auto":
        argv.extend(["--reasoning", p["reasoning"]])
    if p["reasoningBudget"] != -1:
        argv.extend(["--reasoning-budget", str(p["reasoningBudget"])])

    return dedupe_extra(argv, tokenize(extra_args))
