"""llama-server Launcher (native GUI) — v1.0

Standalone tkinter app sharing core.py with the web version:
- same settings.json schema (serverExe, lastModel, global, models{})
- same build_argv() command construction (single authoritative builder)
- same log parsing for token stats (print_timing / n_gen / tg / tg_3s)

No browser or web server required.

Features: professional dark theme with bordered card panels, a custom
parameter tab bar, monitor sparklines with grid lines, color-coded log
lines, a frameless window with integrated minimize / maximize / close
buttons and edge/corner resize handles, and a Chinese / English UI
language toggle (persisted to settings.json, same schema as the web version).
"""

import os
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import core

# ---------------------------------------------------------------------------
# Windows frameless-window constants (only used on Windows; the whole
# frameless path is wrapped in try/except and degrades to the native
# title bar if anything fails).
# ---------------------------------------------------------------------------
_WS_CAPTION = 0x00C00000
_WS_THICKFRAME = 0x00040000
_WS_MAXIMIZE = 0x01000000
_GWL_STYLE = -16
_SWP_NOMOVE = 0x0002
_SWP_NOSIZE = 0x0001
_SWP_NOZORDER = 0x0004
_SWP_FRAMECHANGED = 0x0020
_SWP_SHOWWINDOW = 0x0040
_MIN_W, _MIN_H = 1000, 640


# ---------------------------------------------------------------------------
# Theme — palette mirrors the web version's dark theme (static/styles.css)
# ---------------------------------------------------------------------------
T = {
    "bg": "#0e1116",          # window
    "bg_header": "#161c26",   # top bar
    "panel": "#161b22",       # cards
    "panel_hi": "#1c232d",    # hover / active tab
    "input": "#10151c",       # inputs, logs, charts
    "border": "#2a313c",
    "text": "#e6e8ee",
    "dim": "#8b93a3",
    "accent": "#e0a458",
    "accent_hi": "#ecb878",
    "accent_dim": "#1a1208",
    "ok": "#3fb27f",
    "warn": "#d9a13b",
    "err": "#e5534b",
    "err_hi": "#ea6a62",
    "chart_fill": "#221b10",
    "chart_grid": "#242c38",
    "dis_bg": "#1a1f27",
    "dis_fg": "#5b6371",
}

# general UI fonts bumped by one step (labels 9→10, small text
# 8→9, buttons 10→11, title 11→12) while the command preview, log and
# every input field keep their original sizes (FONT / FONT_MONO = 9).
FONT = ("Segoe UI", 9)
FONT_SM = ("Segoe UI", 9)
FONT_MD = ("Segoe UI", 11)
FONT_BOLD = ("Segoe UI", 11, "bold")
FONT_TITLE = ("Segoe UI", 12, "bold")
FONT_LBL = ("Segoe UI", 10)      # ttk label styles (row / param / monitor)
FONT_MONO = ("Consolas", 9)
FONT_MONO_SM = ("Consolas", 9)


# ---------------------------------------------------------------------------
# i18n — Chinese / English strings.  Mirrors static/i18n.js so the
# native and web versions read the same.  Keys are stable dot-paths; {var}
# placeholders are filled via t(key, **vars).  core.PARAM_LABELS stays the
# Chinese source of truth; PARAM_LABELS_EN mirrors i18n.js "p" for English.
# ---------------------------------------------------------------------------
PARAM_LABELS_EN = {
    "temperature": "Temperature (temperature)",
    "top_k": "Top K",
    "top_p": "Top P",
    "min_p": "Min P",
    "seed": "Seed (-1=random)",
    "ctx_size": "Context size (ctx-size)",
    "batch_size": "Batch size (batch-size)",
    "ubatch_size": "Micro-batch size (ubatch-size)",
    "threads": "Threads (-1=auto)",
    "parallel": "Parallel slots (parallel)",
    "n_gpu_layers": "GPU layers offloaded (-1=all)",
    "cache_type_k": "K cache type",
    "cache_type_v": "V cache type",
    "flash_attn": "Flash Attention",
    "mlock": "Lock memory (--mlock)",
    "no_mmap": "Disable mmap (--no-mmap)",
    "cont_batching": "Continuous batching",
    "jinja": "Jinja templates",
    "metrics": "Expose metrics endpoint",
    "specType": "Speculative decoding (spec-type)",
    "spec_draft_n_max": "Draft max tokens",
    "spec_draft_p_min": "Draft min probability",
    "reasoning": "Reasoning mode (reasoning)",
    "reasoningBudget": "Reasoning budget (-1=auto)",
    "host": "Listen address (host)",
    "port": "Port (port)",
    "apiKey": "API key (optional)",
    "extraArgs": "Extra args",
}

L10N = {
    "zh": {
        "app.title": "llama-server 启动器",
        "status.stopped": "已停止",
        "status.starting": "启动中…",
        "status.running": "运行中",
        "status.exited": "已退出（代码 {code}）",
        "sec.engine": "引擎与模型",
        "sec.presets": "模型预设",
        "sec.command": "启动命令",
        "sec.monitor": "系统监控",
        "sec.tokens": "Token 统计",
        "sec.logs": "日志",
        "sec.params": "启动参数",
        "noPreset": "（无预设）",
        "lbl.serverExe": "llama-server.exe",
        "lbl.model": "模型 .gguf",
        "lbl.mmproj": "视觉 .gguf（mmproj）",
        "btn.browse": "浏览",
        "btn.scan": "扫描",
        "btn.clear": "清空",
        "btn.copyCmd": "复制命令",
        "btn.start": "启动服务",
        "btn.stop": "停止服务",
        "btn.pause": "暂停滚动",
        "btn.resume": "继续滚动",
        "btn.clearLog": "清空",
        "btn.copyLog": "复制全部",
        "btn.open": "打开",
        "btn.cancel": "取消",
        "hint.restored": "✓ 已恢复该模型的参数",
        "grp.sampling": "采样",
        "grp.ctx": "上下文与批处理",
        "grp.gpu": "GPU 与 KV 缓存",
        "grp.advanced": "高级",
        "grp.network": "网络",
        "grp.extra": "额外参数",
        "extra.hint": "额外参数（原样追加，空格分词，可多行）",
        "mon.cpu": "CPU",
        "mon.mem": "内存",
        "mon.gpuUtil": "GPU 利用率",
        "mon.vram": "显存",
        "mon.noGpu": "未检测到 GPU",
        "tok.idle": "空闲",
        "tok.prompting": "提示词处理中",
        "tok.generating": "文字生成中",
        "tok.promptSpeed": "prompt 速度",
        "tok.genSpeed": "生成速度",
        "tok.promptTokens": "已处理 prompt tokens",
        "tok.genTokens": "已生成 tokens",
        "tok.avgTps": "平均生成速度",
        "tok.instTps": "当前瞬时速度",
        "tok.specRate": "Spec 接受率",
        "dlg.pickFile": "选择文件",
        "dlg.scanDir": "选择要扫描的目录",
        "dlg.pickExe": "选择 llama-server 可执行文件",
        "dlg.pickModel": "选择模型文件",
        "dlg.pickMmproj": "选择视觉投影文件",
        "dlg.exes": "可执行文件",
        "dlg.all": "所有文件",
        "dlg.gguf": "GGUF 模型",
        "msg.noServer": "请先选择 llama-server 可执行文件和模型文件。",
        "msg.noServerTitle": "无法启动",
        "msg.dupeTitle": "参数重复",
        "msg.dupe": "以下参数在额外参数中重复出现，已忽略: {list}",
        "msg.startFail": "启动失败",
        "msg.scanEmpty": "该目录下未找到文件。",
        "msg.scanTitle": "扫描",
        "msg.saveFail": "保存设置失败",
        "msg.ignored": "⚠ 额外参数中重复项已忽略: {list}",
        "log.closing": "窗口关闭：正在停止服务…",
        "log.stopped": "服务已停止",
    },
    "en": {
        "app.title": "llama-server Launcher",
        "status.stopped": "Stopped",
        "status.starting": "Starting…",
        "status.running": "Running",
        "status.exited": "Exited (code {code})",
        "sec.engine": "Engine & Model",
        "sec.presets": "Model Presets",
        "sec.command": "Launch Command",
        "sec.monitor": "System Monitor",
        "sec.tokens": "Token Stats",
        "sec.logs": "Logs",
        "sec.params": "Launch Parameters",
        "noPreset": "(no preset)",
        "lbl.serverExe": "llama-server.exe",
        "lbl.model": "Model .gguf",
        "lbl.mmproj": "Vision .gguf (mmproj)",
        "btn.browse": "Browse",
        "btn.scan": "Scan",
        "btn.clear": "Clear",
        "btn.copyCmd": "Copy Command",
        "btn.start": "Start Server",
        "btn.stop": "Stop Server",
        "btn.pause": "Pause Scroll",
        "btn.resume": "Resume Scroll",
        "btn.clearLog": "Clear",
        "btn.copyLog": "Copy All",
        "btn.open": "Open",
        "btn.cancel": "Cancel",
        "hint.restored": "✓ Restored parameters for this model",
        "grp.sampling": "Sampling",
        "grp.ctx": "Context & Batching",
        "grp.gpu": "GPU & KV Cache",
        "grp.advanced": "Advanced",
        "grp.network": "Network",
        "grp.extra": "Extra Args",
        "extra.hint": "Extra args (appended verbatim, space-tokenized, multi-line)",
        "mon.cpu": "CPU",
        "mon.mem": "Memory",
        "mon.gpuUtil": "GPU Utilization",
        "mon.vram": "VRAM",
        "mon.noGpu": "No GPU detected",
        "tok.idle": "Idle",
        "tok.prompting": "Processing prompt",
        "tok.generating": "Generating text",
        "tok.promptSpeed": "Prompt speed",
        "tok.genSpeed": "Generation speed",
        "tok.promptTokens": "Processed prompt tokens",
        "tok.genTokens": "Generated tokens",
        "tok.avgTps": "Average generation speed",
        "tok.instTps": "Current instant speed",
        "tok.specRate": "Spec acceptance rate",
        "dlg.pickFile": "Select File",
        "dlg.scanDir": "Select directory to scan",
        "dlg.pickExe": "Select llama-server executable",
        "dlg.pickModel": "Select model file",
        "dlg.pickMmproj": "Select vision projection file",
        "dlg.exes": "Executables",
        "dlg.all": "All files",
        "dlg.gguf": "GGUF models",
        "msg.noServer": "Please choose the llama-server executable and a model file first.",
        "msg.noServerTitle": "Cannot Start",
        "msg.dupeTitle": "Duplicate Parameters",
        "msg.dupe": "The following parameters appear in extra args and were ignored: {list}",
        "msg.startFail": "Start Failed",
        "msg.scanEmpty": "No files found in that directory.",
        "msg.scanTitle": "Scan",
        "msg.saveFail": "Failed to Save Settings",
        "msg.ignored": "⚠ Duplicates in extra args ignored: {list}",
        "log.closing": "Window closing: stopping server…",
        "log.stopped": "Server stopped",
    },
}


def build_style(root):
    """Apply the dark theme to all ttk widgets (clam base)."""
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=FONT, background=T["bg"], foreground=T["text"])
    style.configure("TFrame", background=T["bg"])
    style.configure("TPanedwindow", background=T["bg"])
    style.configure("TPanedwindow.Sash", background=T["border"],
                    sashthickness=4, relief="flat")
    # labels render one step larger than the input fields, which
    # keep the base "." font (9pt) so entry text stays unchanged.
    style.configure("TLabel", font=FONT_LBL,
                    background=T["panel"], foreground=T["text"])
    style.configure("Dim.TLabel", font=FONT_LBL,
                    background=T["panel"], foreground=T["dim"])
    style.configure("TEntry", fieldbackground=T["input"], background=T["input"],
                    foreground=T["text"], insertcolor=T["text"],
                    bordercolor=T["border"], lightcolor=T["input"],
                    darkcolor=T["input"])
    style.map("TEntry", bordercolor=[("focus", T["accent"])])
    style.configure("TCombobox", fieldbackground=T["input"],
                    background=T["input"], foreground=T["text"],
                    arrowcolor=T["dim"], bordercolor=T["border"],
                    lightcolor=T["input"], darkcolor=T["input"])
    # clam's theme maps fieldbackground/foreground to light colors for the
    # readonly state, overriding the configure above; map them back so the
    # selected value stays readable on the dark field.
    style.map("TCombobox",
              fieldbackground=[("readonly", T["input"]),
                               ("readonly focus", T["input"])],
              foreground=[("readonly", T["text"]),
                          ("readonly focus", T["text"])])
    style.map("TCombobox", bordercolor=[("focus", T["accent"])])
    root.option_add("*TCombobox*Listbox.background", T["input"])
    root.option_add("*TCombobox*Listbox.foreground", T["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", T["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", T["accent_dim"])
    style.configure("TCheckbutton", background=T["panel"],
                    foreground=T["text"], indicatorcolor=T["input"],
                    focuscolor=T["border"])
    style.map("TCheckbutton", background=[("active", T["panel_hi"])])
    style.configure("TSpinbox", fieldbackground=T["input"],
                    background=T["input"], foreground=T["text"],
                    arrowcolor=T["dim"], bordercolor=T["border"],
                    lightcolor=T["input"], darkcolor=T["input"])
    style.map("TSpinbox", bordercolor=[("focus", T["accent"])])
    style.configure("TProgressbar", background=T["accent"],
                    troughcolor=T["input"], bordercolor=T["border"],
                    lightcolor=T["accent"], darkcolor=T["accent"])
    style.configure("Vertical.TScrollbar", background=T["border"],
                    troughcolor=T["panel"], bordercolor=T["panel"],
                    arrowcolor=T["dim"], relief="flat")
    style.configure("Horizontal.TScrollbar", background=T["border"],
                    troughcolor=T["panel"], bordercolor=T["panel"],
                    arrowcolor=T["dim"], relief="flat")


def card(parent, title):
    """Bordered card with an accent-marker header.

    Returns (outer, inner, head, title_label): outer is the widget to
    place in the parent's geometry manager, inner is the content area,
    head is the header row (for optional right-aligned widgets), and
    title_label is the header title (kept for i18n retranslation).
    """
    outer = tk.Frame(parent, bg=T["panel"], highlightthickness=1,
                     highlightbackground=T["border"])
    head = tk.Frame(outer, bg=T["panel"])
    head.pack(fill="x", padx=12, pady=(10, 6))
    tk.Frame(head, bg=T["accent"], width=3, height=14).pack(side="left")
    title_label = tk.Label(head, text=title, bg=T["panel"], fg=T["text"],
                           font=FONT_BOLD)
    title_label.pack(side="left", padx=(7, 0))
    inner = tk.Frame(outer, bg=T["panel"])
    inner.pack(fill="both", expand=True, padx=12, pady=(0, 12))
    return outer, inner, head, title_label


_BTN_COLORS = {
    "default": (T["input"], T["text"], T["accent_hi"]),
    "ghost": (T["panel"], T["dim"], T["accent_hi"]),
    "primary": (T["accent"], T["accent_dim"], T["accent_hi"]),
    "danger": (T["err"], "#ffffff", T["err_hi"]),
}
_BTN_DISABLED = {
    "default": (T["dis_bg"], T["dis_fg"]),
    "ghost": (T["panel"], T["dis_fg"]),
    "primary": ("#33291a", "#8a6d3f"),
    "danger": ("#332224", "#a05a56"),
}


def flat_button(parent, text, command=None, kind="default", font=None):
    """Flat button with a 1px border and accent hover (web .btn style)."""
    bg, fg, _hover = _BTN_COLORS[kind]
    btn = tk.Button(parent, text=text, command=command, font=font or FONT,
                    bg=bg, fg=fg, activebackground=T["accent_hi"],
                    activeforeground=fg, relief="flat", bd=0,
                    highlightthickness=1, highlightbackground=T["border"],
                    cursor="hand2", padx=10, pady=3)
    btn._kind = kind

    def _enter(_e):
        if str(btn["state"]) != "disabled":
            btn.configure(highlightbackground=T["accent"])

    def _leave(_e):
        btn.configure(highlightbackground=T["border"])

    btn.bind("<Enter>", _enter)
    btn.bind("<Leave>", _leave)
    return btn


def set_button_state(btn, state):
    """Enable/disable a flat button with matching disabled colors."""
    btn.configure(state=state)
    if state == "disabled":
        bg, fg = _BTN_DISABLED[btn._kind]
        btn.configure(bg=bg, fg=fg, cursor="arrow")
    else:
        bg, fg, _hover = _BTN_COLORS[btn._kind]
        btn.configure(bg=bg, fg=fg, cursor="hand2")


# ---------------------------------------------------------------------------
# Live token stats: log parsing (port of static/app.js logic)
# ---------------------------------------------------------------------------
RE_LIVE_PROMPT = re.compile(
    r"prompt processing,\s*n_tokens\s*=\s*(\d+),\s*progress\s*=\s*([\d.]+),\s*"
    r"t\s*=\s*([\d.]+)\s*s\s*/\s*([\d.]+)\s*tokens per second")
RE_LIVE_GEN = re.compile(
    r"n_gen\s*=\s*(\d+),\s*tg\s*=\s*([\d.]+)\s*t/s,\s*tg_3s\s*=\s*([\d.]+)\s*t/s")
RE_LIVE_TASK = re.compile(r"task\s+(\d+)")


def fresh_tok_acc():
    """Zeroed accumulator (reset on each new server process start)."""
    return {"genTokens": 0, "genTime": 0.0, "promptTokens": 0,
            "lastGenTask": None, "lastNGen": 0,
            "lastPromptTask": None, "lastPromptNTokens": 0,
            "lastHitMode": None}


def parse_live_stats(line, st):
    """Pure function: returns the updated state dict on match, else None."""
    m = RE_LIVE_PROMPT.search(line)
    if m:
        tm = RE_LIVE_TASK.search(line)
        st["mode"] = "prompt"
        st["taskId"] = int(tm.group(1)) if tm else None
        st["nTokens"] = int(m.group(1))
        st["progress"] = float(m.group(2))
        st["ppSec"] = float(m.group(3))
        st["ppTps"] = float(m.group(4))
        st["ts"] = time.time()
        return st
    m = RE_LIVE_GEN.search(line)
    if m:
        tm = RE_LIVE_TASK.search(line)
        st["mode"] = "gen"
        st["taskId"] = int(tm.group(1)) if tm else None
        st["nGen"] = int(m.group(1))
        st["tg"] = float(m.group(2))
        st["tg3"] = float(m.group(3))
        st["ts"] = time.time()
        return st
    return None


def update_tok_acc(acc, s):
    """Accumulate tokens/speed from a live-stats hit (web rules)."""
    task_id = s.get("taskId")
    if s["mode"] == "gen":
        n_gen = s["nGen"]
        if (task_id is not None and task_id == acc["lastGenTask"]
                and n_gen >= acc["lastNGen"]):
            delta = n_gen - acc["lastNGen"]
        else:
            delta = n_gen
        acc["genTokens"] += delta
        if s["tg"] > 0:
            acc["genTime"] += delta / s["tg"]
        acc["lastGenTask"] = task_id
        acc["lastNGen"] = n_gen
        acc["lastHitMode"] = "gen"
    elif s["mode"] == "prompt":
        n_tok = s["nTokens"]
        if task_id is not None:
            if task_id != acc["lastPromptTask"]:
                acc["promptTokens"] += n_tok
            acc["lastPromptTask"] = task_id
        elif acc["lastHitMode"] != "prompt" or n_tok != acc["lastPromptNTokens"]:
            acc["promptTokens"] += n_tok
        acc["lastPromptNTokens"] = n_tok
        acc["lastHitMode"] = "prompt"


# ---------------------------------------------------------------------------
# Sparkline: small canvas trend chart (web drawChart equivalent)
# ---------------------------------------------------------------------------
class Sparkline:
    """90-sample window, 0-100 scale, accent line + full grid (no fill)."""

    WINDOW = 90

    def __init__(self, parent, width=220, height=60):
        self.canvas = tk.Canvas(parent, width=width, height=height,
                                bg=T["input"], highlightthickness=1,
                                highlightbackground=T["border"])
        self.samples = []
        self.height = height
        self._cw = width
        self.canvas.bind("<Configure>", self._on_resize)

    def _on_resize(self, event):
        if event.widget is self.canvas and event.width > 60:
            if event.width != self._cw:
                self._cw = event.width
                self.canvas.configure(width=event.width)
                self.draw()

    def push(self, value):
        self.samples.append(float(value))
        if len(self.samples) > self.WINDOW:
            self.samples.pop(0)
        self.draw()

    def draw(self):
        c = self.canvas
        c.delete("all")
        w, h = self._cw, self.height
        top, bottom = 4, h - 4
        span = bottom - top
        # grid lines now span the full plot width (they used to
        # stop short of the value label), plus a top line at 100% that
        # sits directly above the number, and vertical lines at
        # 25/50/75% of the width.
        for p in (25, 50, 75):
            y = bottom - (p / 100.0) * span
            c.create_line(2, y, w - 2, y, fill=T["chart_grid"])
        c.create_line(2, top, w - 2, top, fill=T["chart_grid"])
        for p in (25, 50, 75):
            x = 2 + (p / 100.0) * (w - 4)
            c.create_line(x, top, x, bottom, fill=T["chart_grid"])
        if len(self.samples) < 2:
            return
        step = (w - 8) / (self.WINDOW - 1)
        pts = []
        for i, v in enumerate(self.samples[-self.WINDOW:]):
            x = 4 + i * step
            y = bottom - (max(0.0, min(100.0, v)) / 100.0) * span
            pts.extend((x, y))
        # the area fill under the curve is removed (it read as an
        # unexplained triangle on nearly flat lines); only the line stays.
        c.create_line(*pts, fill=T["accent"], width=2, smooth=True)
        c.create_text(w - 6, 6, text=f"{self.samples[-1]:.1f}%", anchor="ne",
                      fill=T["text"], font=FONT_MONO_SM)


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------
class LauncherApp:
    def __init__(self, root):
        self.root = root
        self.settings = core.load_settings()
        self.lang = self.settings.get("language", "zh")
        if self.lang not in L10N:
            self.lang = "zh"
        root.title(f"{self.t('app.title')} v{core.VERSION}")
        # narrower + taller default window (1180x1000) — the extra
        # height goes mainly to the log card (see _build_ui vertical split).
        root.geometry("1180x1000")
        root.minsize(_MIN_W, _MIN_H)
        root.configure(bg=T["bg"])
        build_style(root)
        # (w, h, x, y) tuple — consumed by _restore_from_max().
        self._prev_geom = (1180, 1000, 0, 0)
        # None until _apply_frameless() runs after the toplevel is
        # mapped — Tk applies WS_CAPTION|WS_THICKFRAME when the window is
        # mapped, which clobbers any pre-map strip.
        self._frameless = None
        self._drag = None
        self._rs = None

        self.ui_q = queue.Queue()
        self.live = {"mode": "idle"}
        self.tok_acc = fresh_tok_acc()
        self.last_metrics = None
        self.last_monitor = None
        self.log_paused = False
        self.param_widgets = {}  # key -> widget
        self.tok_labels = {}
        self._save_timer = None
        self._poll_host, self._poll_port = "127.0.0.1", 8080
        self._tab_frames = {}
        self._tab_btns = {}
        # i18n: widget references retranslated by _apply_i18n().
        self._path_row_refs = {}
        self._mon_row_labels = {}
        self._tok_row_labels = {}
        self._param_labels = {}

        core.mgr.on_line(self._on_line)
        core.mgr.on_state(self._on_state)

        self._build_ui()
        self._load_settings_to_ui()
        self._start_pollers()
        root.after(100, self._poll_ui)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        # finalize frameless mode after the toplevel is mapped
        # (Tk sets WS_CAPTION|WS_THICKFRAME on map, clobbering pre-map
        # strips); <Map> covers iconify/restore re-maps as well.
        root.bind("<Map>", self._on_map_frameless)
        root.after(100, self._apply_frameless)

    # -- layout ----------------------------------------------------------
    def _build_ui(self):
        self._build_resize_handles()
        self._content = tk.Frame(self.root, bg=T["bg"])
        self._content.grid(row=1, column=1, sticky="nsew")
        self._build_topbar()
        # vertical split between the 3-column body and the log
        # card, so the log gets a larger (user-adjustable) share of the
        # taller, narrower window.
        self.vbody = ttk.PanedWindow(self._content, orient="vertical")
        self.vbody.pack(fill="both", expand=True, padx=10, pady=(2, 10))
        body = ttk.PanedWindow(self.vbody, orient="horizontal")
        self.body = body
        self.vbody.add(body)
        self._build_left(body)
        self._build_center(body)
        self._build_right(body)
        self._build_bottom(self.vbody)
        # initial split — left 450 / middle 372 / right ≈330 px
        # (the parameter column narrows, the monitor column widens, per
        # the user's reference screenshot), log ≈42% of the body height.
        # Applied only after the window is mapped at full size: sashpos
        # calls made while the toplevel is still unmapped are clamped to
        # the panedwindow's narrow requested width and collapse the
        # columns. (This Tk build has no "sash place" subcommand —
        # "sashpos index newpos" is the working form.)
        self.root.after(150, self._init_splits)

    def _init_splits(self):
        """Set the initial horizontal (450/372/≈330) and vertical
        (≈58/42) sash positions once, after the window is mapped at its
        full size.

        The sashes stay user-draggable afterwards; this only fixes the
        startup position. Retries until the window is mapped wide and
        tall enough to measure."""
        if getattr(self, "_splits_done", False):
            return
        try:
            w = self.body.winfo_width()
            h = self.vbody.winfo_height()
        except tk.TclError:
            return
        if w > 900 and h > 500:
            try:
                # The top pane must be at least as tall as its content's
                # requested height (the monitor + token cards), otherwise
                # the bottom rows get clipped; the 58% target applies when
                # it leaves that much room.
                top = max(int(h * 0.58), self.body.winfo_reqheight() + 16)
                self.body.tk.call(self.body, "sashpos", 0, 450)
                self.body.tk.call(self.body, "sashpos", 1, 450 + 4 + 372)
                self.vbody.tk.call(self.vbody, "sashpos", 0, top)
                self._splits_done = True
                return
            except tk.TclError:
                pass
        self.root.after(100, self._init_splits)

    # -- frameless window: resize handles -----------------------------------
    def _build_resize_handles(self):
        """Eight thin frames around the window for manual edge/corner
        resizing (used once the native frame is removed; they are inert
        otherwise because the native frame covers the same area)."""
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(1, weight=1)
        self._handles = []
        specs = [
            (0, 0, "top_left_corner", "nw"),
            (0, 1, "top_side", "n"),
            (0, 2, "top_right_corner", "ne"),
            (1, 0, "left_side", "w"),
            (1, 2, "right_side", "e"),
            (2, 0, "bottom_left_corner", "sw"),
            (2, 1, "bottom_side", "s"),
            (2, 2, "bottom_right_corner", "se"),
        ]
        for row, col, cursor, edges in specs:
            hd = tk.Frame(self.root, bg=T["bg"])
            hd.grid(row=row, column=col, sticky="nsew")
            hd.configure(cursor=cursor)
            hd.bind("<ButtonPress-1>",
                    lambda e, edges=edges: self._start_resize(e, edges))
            hd.bind("<B1-Motion>", self._do_resize)
            hd.bind("<ButtonRelease-1>",
                    lambda _e: setattr(self, "_rs", None))
            self._handles.append(hd)

    def _start_resize(self, e, edges):
        if self._is_zoomed():
            self._restore_from_max()
        self._rs = {
            "edges": edges,
            "x0": e.x_root, "y0": e.y_root,
            "x": self.root.winfo_x(), "y": self.root.winfo_y(),
            "w": self.root.winfo_width(), "h": self.root.winfo_height(),
        }

    def _do_resize(self, e):
        rs = self._rs
        if not rs:
            return
        dx = e.x_root - rs["x0"]
        dy = e.y_root - rs["y0"]
        x, y, w, h = rs["x"], rs["y"], rs["w"], rs["h"]
        if "e" in rs["edges"]:
            w += dx
        if "s" in rs["edges"]:
            h += dy
        if "w" in rs["edges"]:
            w -= dx
            x += dx
        if "n" in rs["edges"]:
            h -= dy
            y += dy
        # root.minsize() does not constrain manual geometry changes.
        if w < _MIN_W:
            if "w" in rs["edges"]:
                x -= _MIN_W - w
            w = _MIN_W
        if h < _MIN_H:
            if "n" in rs["edges"]:
                y -= _MIN_H - h
            h = _MIN_H
        self._set_window_size(w, h, x, y)

    def _set_window_size(self, w, h, x, y):
        """Resize/move the toplevel to exactly w×h at (x, y).

        on frameless Windows, Tk's geometry() adds a phantom
        16 px frame delta to the width even though the window has no
        frame (verified empirically: geometry("1196x1039") produced a
        1212 px wide window), so every size change — restore from
        maximize, manual edge resize — drifted the window wider.  After
        the Tk call we re-assert the exact outer rect on the wrapper
        toplevel with SetWindowPos; the frameless client auto-fills the
        wrapper's client area, so the final size is exactly w×h.
        """
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        if os.name == "nt" and self._frameless:
            try:
                # Tk applies the geometry change during idle-task
                # processing; wait for it so the SetWindowPos correction
                # below runs last and wins.
                self.root.update_idletasks()
                import ctypes
                user32 = ctypes.windll.user32
                # Explicit argtypes: 64-bit HWNDs must not be truncated.
                user32.GetParent.argtypes = [ctypes.c_void_p]
                user32.GetParent.restype = ctypes.c_void_p
                user32.SetWindowPos.argtypes = [ctypes.c_void_p,
                                                ctypes.c_void_p,
                                                ctypes.c_int, ctypes.c_int,
                                                ctypes.c_int, ctypes.c_int,
                                                ctypes.c_uint]
                user32.SetWindowPos.restype = ctypes.c_int
                hwnd = user32.GetParent(self.root.winfo_id())
                if hwnd:
                    user32.SetWindowPos(hwnd, None, x, y, w, h,
                                        _SWP_NOZORDER | _SWP_SHOWWINDOW)
            except Exception:
                pass

    # -- frameless window: frame removal, drag, window buttons --------------
    def _make_frameless(self):
        """Strip the native Windows frame; True on success.

        Must run after the toplevel is mapped: Tk applies
        WS_CAPTION|WS_THICKFRAME when the window is mapped, which clobbers
        any pre-map strip (verified empirically).  Idempotent.
        Falls back to the native title bar (self._frameless False) on any
        failure, so the app stays fully usable either way.
        """
        if os.name != "nt":
            return False
        try:
            import ctypes
            user32 = ctypes.windll.user32
            # Explicit argtypes: 64-bit HWNDs must not be truncated to int.
            user32.GetParent.argtypes = [ctypes.c_void_p]
            user32.GetParent.restype = ctypes.c_void_p
            user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
            user32.GetWindowLongW.restype = ctypes.c_int
            user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                             ctypes.c_int]
            user32.SetWindowLongW.restype = ctypes.c_int
            user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                           ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int,
                                           ctypes.c_uint]
            hwnd = user32.GetParent(self.root.winfo_id())
            if not hwnd:
                return False
            style = user32.GetWindowLongW(hwnd, _GWL_STYLE)
            style &= ~(_WS_CAPTION | _WS_THICKFRAME)
            user32.SetWindowLongW(hwnd, _GWL_STYLE, style)
            user32.SetWindowPos(
                hwnd, None, 0, 0, 0, 0,
                _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_FRAMECHANGED)
            return True
        except Exception:
            return False

    def _apply_frameless(self, attempt=0):
        """Finalize frameless mode once the wrapper toplevel exists

        Called from the <Map> binding and a 100 ms after() fallback.  On
        success the custom ✕/□/— buttons are added to the app title bar;
        on failure the native title bar (with its own buttons) stays.

        The wrapper toplevel is created by Tk *around* the first map, so
        GetParent(winfo_id()) can legitimately return 0 for a few
        milliseconds after startup.  A failed attempt must NOT record
        _frameless = False — that would poison every later retry (the
        early-return guard below), so failures keep _frameless None until
        the attempts are exhausted.
        """
        if self._frameless:
            return
        if attempt > 20:
            # The wrapper never appeared; keep the native frame.
            self._frameless = False
            return
        try:
            if not self.root.winfo_exists():
                raise tk.TclError
            ok = self._make_frameless()
        except Exception:
            ok = False
        if ok:
            self._frameless = True
            self._build_window_buttons()
        else:
            self.root.after(50, lambda: self._apply_frameless(attempt + 1))

    def _on_map_frameless(self, _e):
        """(Re)assert frameless on every map: iconify/restore and other
        Tk state changes can re-apply the native frame style."""
        if self._frameless:
            self._make_frameless()
        else:
            self._apply_frameless()

    def _is_zoomed(self):
        """Whether the window is actually maximized.

        Tk's state() can lag behind the real wrapper style in
        frameless mode, so on Windows also read the WS_MAXIMIZE bit from
        the wrapper toplevel (GetParent of the client hwnd). Either signal
        counts as zoomed so rapid double-clicks toggle correctly.
        """
        if os.name == "nt":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                user32.GetParent.argtypes = [ctypes.c_void_p]
                user32.GetParent.restype = ctypes.c_void_p
                user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
                user32.GetWindowLongW.restype = ctypes.c_int
                hwnd = user32.GetParent(self.root.winfo_id())
                if hwnd and (user32.GetWindowLongW(hwnd, _GWL_STYLE)
                             & _WS_MAXIMIZE):
                    return True
            except Exception:
                pass
        return self.root.state() == "zoomed"

    def _build_window_buttons(self):
        """Create the ✕/□/— buttons at the right end of the app title bar
        (frameless mode only) and bind title-bar drag/maximize."""
        bar = self._topbar
        self.btn_win_close = flat_button(bar, "✕", self._win_close,
                                         kind="ghost", font=FONT_MD)
        self.btn_win_max = flat_button(bar, "□", self._win_max,
                                       kind="ghost", font=FONT_MD)
        self.btn_win_min = flat_button(bar, "—", self._win_min,
                                       kind="ghost", font=FONT_MD)
        # Pack right-to-left: close first (rightmost), then max, min, then
        # re-pack the language button to their left.
        self.btn_win_close.pack(side="right", padx=0)
        self.btn_win_max.pack(side="right", padx=0)
        self.btn_win_min.pack(side="right", padx=(0, 8))
        self.btn_lang.pack_forget()
        self.btn_lang.pack(side="right", padx=(0, 8))
        # Title-bar drag + double-click maximize (frameless only).
        for w in (bar, self.lbl_icon, self.lbl_title):
            w.bind("<ButtonPress-1>", self._on_title_press)
            w.bind("<B1-Motion>", self._on_title_motion)
            w.bind("<ButtonRelease-1>", self._on_title_release)
            w.bind("<Double-Button-1>", self._on_title_double)

    def _on_title_press(self, e):
        if self._is_zoomed():
            # Dragging a maximized title bar restores the window, matching
            # native Windows behavior.
            self._restore_from_max()
        self._drag = (e.x_root - self.root.winfo_x(),
                      e.y_root - self.root.winfo_y())

    def _on_title_motion(self, e):
        if self._drag is None:
            return
        self.root.geometry(
            f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _on_title_release(self, _e):
        self._drag = None

    def _on_title_double(self, _e):
        if self._is_zoomed():
            self._restore_from_max()
        else:
            self._maximize()

    def _win_min(self):
        self.root.state("iconic")

    def _win_max(self):
        if self._is_zoomed():
            self._restore_from_max()
        else:
            self._maximize()

    def _maximize(self):
        self._prev_geom = (self.root.winfo_width(), self.root.winfo_height(),
                           self.root.winfo_x(), self.root.winfo_y())
        self.root.state("zoomed")
        self._set_handles_visible(False)

    def _restore_from_max(self):
        self._set_handles_visible(True)
        # Windows silently ignores geometry changes while a window
        # is maximized, so the old single geometry() call did nothing on
        # the second click of the max button. Drop the maximized state
        # first, then re-apply the saved geometry via _set_window_size,
        # which also corrects Tk's phantom frame delta on frameless
        # windows (see _set_window_size).
        self.root.state("normal")
        w, h, x, y = self._prev_geom or (1180, 1000, 0, 0)
        self._set_window_size(w, h, x, y)

    def _set_handles_visible(self, on):
        for hd in getattr(self, "_handles", []):
            if on:
                hd.grid()
            else:
                hd.grid_remove()

    def _win_close(self):
        self._on_close()

    # -- i18n --------------------------------------------------------
    def t(self, key, **vars):
        """Translate an i18n key into the current language, with {vars}."""
        table = L10N.get(self.lang) or L10N["zh"]
        text = table.get(key)
        if text is None:
            text = L10N["zh"].get(key, key)
        if vars:
            try:
                text = text.format(**vars)
            except (KeyError, IndexError):
                pass
        return text

    def _set_lang(self, lang):
        """Switch to the given language (dual 中/EN toggle)."""
        if lang not in L10N or lang == self.lang:
            return
        self.lang = lang
        self.settings["language"] = lang
        self._apply_i18n()
        self._save_settings()

    def _toggle_lang(self):
        """Switch zh <-> en (kept for compatibility)."""
        self._set_lang("en" if self.lang == "zh" else "zh")

    def _update_lang_btns(self):
        """Light the active language segment, dim the other."""
        for lang, btn in (("zh", self.btn_lang_zh), ("en", self.btn_lang_en)):
            if lang == self.lang:
                btn.configure(bg=T["accent"], fg=T["accent_dim"])
            else:
                btn.configure(bg=T["panel"], fg=T["dim"])

    def _lang_segment(self, text, lang):
        """One segment of the dual 中/EN language toggle."""
        btn = tk.Button(self.btn_lang, text=text,
                        command=lambda l=lang: self._set_lang(l),
                        font=FONT_SM, bg=T["panel"], fg=T["dim"],
                        activebackground=T["accent_hi"],
                        activeforeground=T["accent_dim"],
                        relief="flat", bd=0, highlightthickness=0,
                        cursor="hand2", padx=8, pady=2)
        btn.pack(side="left", padx=1, pady=1)
        return btn

    def _apply_i18n(self):
        """Retranslate every static label/button after a language toggle.
        Dynamic values (status, live stats, monitor) are re-rendered from
        their current data so they pick up the new language too."""
        self.root.title(f"{self.t('app.title')} v{core.VERSION}")
        self.lbl_title.configure(text=self.t("app.title"))
        self.btn_start.configure(text=self.t("btn.start"))
        self.btn_stop.configure(text=self.t("btn.stop"))
        self._update_lang_btns()  # dual 中/EN segments
        self.btn_pause.configure(
            text=self.t("btn.resume") if self.log_paused
            else self.t("btn.pause"))
        self.btn_clear_log.configure(text=self.t("btn.clearLog"))
        self.btn_copy_log.configure(text=self.t("btn.copyLog"))
        self.btn_copy_cmd.configure(text=self.t("btn.copyCmd"))
        if self.lbl_restored.cget("text"):
            self.lbl_restored.configure(text=self.t("hint.restored"))
        self.lbl_card_engine.configure(text=self.t("sec.engine"))
        self.lbl_card_command.configure(text=self.t("sec.command"))
        self.lbl_card_monitor.configure(text=self.t("sec.monitor"))
        self.lbl_card_tokens.configure(text=self.t("sec.tokens"))
        self.lbl_card_params.configure(text=self.t("sec.params"))
        self.lbl_card_logs.configure(text=self.t("sec.logs"))
        self.lbl_presets.configure(text=self.t("sec.presets"))
        for refs in self._path_row_refs.values():
            refs["label"].configure(text=self.t(refs["i18n"]))
            refs["browse"].configure(text=self.t("btn.browse"))
            refs["scan"].configure(text=self.t("btn.scan"))
            if refs.get("clear"):
                refs["clear"].configure(text=self.t("btn.clear"))
        for key, lbl in self._mon_row_labels.items():
            lbl.configure(text=self.t(key))
        for key, lbl in self._tok_row_labels.items():
            lbl.configure(text=self.t(f"tok.{key}"))
        for key, lbl in self._param_labels.items():
            if key == "extraArgs":
                lbl.configure(text=self.t("extra.hint"))
            else:
                lbl.configure(text=self._param_label(key))
        for title, btn in self._tab_btns.items():
            btn.configure(text=self.t(self.PARAM_TAB_I18N[title]))
        self._refresh_presets()
        self._render_state(core.mgr.status())
        self._render_live()
        if self.last_monitor is not None:
            self._render_monitor(self.last_monitor)

    def _build_topbar(self):
        bar = tk.Frame(self._content, bg=T["bg_header"], highlightthickness=1,
                       highlightbackground=T["border"])
        self._topbar = bar
        bar.pack(fill="x", padx=8, pady=(4, 6))
        self.lbl_icon = tk.Label(bar, text="🦙", font=("Segoe UI", 14),
                                 bg=T["bg_header"])
        self.lbl_icon.pack(side="left", padx=(10, 4))
        self.lbl_title = tk.Label(bar, text=self.t("app.title"), font=FONT_TITLE,
                                  bg=T["bg_header"], fg=T["text"])
        self.lbl_title.pack(side="left", padx=(0, 10))
        # version badge sits between the title and the status pill,
        # leaving the right end free for the window buttons.
        self.lbl_version = tk.Label(bar, text=f"v{core.VERSION}", font=FONT_SM,
                                    fg=T["dim"], bg=T["bg_header"])
        self.lbl_version.pack(side="left", padx=(0, 10))
        pill = tk.Frame(bar, bg=T["input"], highlightthickness=1,
                        highlightbackground=T["border"])
        pill.pack(side="left", padx=(0, 10))
        self.status_dot = tk.Label(pill, text="●", fg=T["dim"],
                                   font=("Segoe UI", 10), bg=T["input"])
        self.status_dot.pack(side="left", padx=(10, 4), pady=4)
        self.status_label = tk.Label(pill, text=self.t("status.stopped"),
                                     font=FONT_LBL, bg=T["input"], fg=T["dim"])
        self.status_label.pack(side="left", padx=(0, 10), pady=4)
        self.btn_start = flat_button(bar, self.t("btn.start"), self.on_start,
                                     kind="primary", font=FONT_MD)
        self.btn_start.pack(side="left", padx=4)
        self.btn_stop = flat_button(bar, self.t("btn.stop"), self.on_stop,
                                    kind="danger", font=FONT_MD)
        set_button_state(self.btn_stop, "disabled")
        self.btn_stop.pack(side="left", padx=4)
        # dual-segment language toggle — both 中 and EN are shown
        # at all times; the active language is lit (accent), the inactive
        # one dimmed. The ✕/□/— window buttons are added later by
        # _build_window_buttons() once frameless mode is confirmed.
        self.btn_lang = tk.Frame(bar, bg=T["bg_header"], highlightthickness=1,
                                 highlightbackground=T["border"])
        self.btn_lang.pack(side="right", padx=(0, 8))
        self.btn_lang_zh = self._lang_segment("中", "zh")
        self.btn_lang_en = self._lang_segment("EN", "en")
        self._update_lang_btns()

    # -- left column: engine & model --------------------------------------
    def _build_left(self, body):
        cont = tk.Frame(body, bg=T["bg"])
        body.add(cont, weight=2)
        cont.columnconfigure(0, weight=1)
        cont.rowconfigure(1, weight=1)
        outer, f, _head, self.lbl_card_engine = card(cont, self.t("sec.engine"))
        outer.grid(row=0, column=0, sticky="nsew")
        f.columnconfigure(0, weight=1)
        self.entry_exe = self._path_row(
            f, 0, "lbl.serverExe", self.on_pick_exe, kind="exe")
        self.entry_model = self._path_row(
            f, 2, "lbl.model", self.on_pick_model, kind="gguf")
        self.lbl_restored = tk.Label(f, text="", font=FONT_SM,
                                     bg=T["panel"], fg=T["ok"])
        self.lbl_restored.grid(row=3, column=0, columnspan=4, sticky="w",
                               pady=(0, 2))
        self.entry_mmproj = self._path_row(
            f, 4, "lbl.mmproj", self.on_pick_mmproj, kind="gguf",
            with_clear=True)
        self.lbl_presets = ttk.Label(f, text=self.t("sec.presets"),
                                     style="Dim.TLabel")
        self.lbl_presets.grid(row=6, column=0, columnspan=4, sticky="w",
                              pady=(8, 2))
        self.cmb_preset = ttk.Combobox(f, values=[self.t("noPreset")],
                                       state="readonly")
        self.cmb_preset.grid(row=7, column=0, columnspan=4, sticky="we")
        self.cmb_preset.bind("<<ComboboxSelected>>", self.on_preset)
        # 启动命令 sits below 模型预设, leaving the bottom row for 日志.
        cmd_o, cmd, cmd_head, self.lbl_card_command = card(cont, self.t("sec.command"))
        cmd_o.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self.btn_copy_cmd = flat_button(cmd_head, self.t("btn.copyCmd"),
                                        self._copy_cmd,
                                        kind="default", font=FONT_SM)
        self.btn_copy_cmd.pack(side="right")
        self.lbl_match = tk.Label(cmd_head, text="", font=FONT_SM,
                                  bg=T["panel"], fg=T["ok"])
        self.lbl_match.pack(side="right", padx=(0, 8))
        self.cmd_text = tk.Text(cmd, height=3, wrap="word", font=FONT_MONO,
                                bg=T["input"], fg=T["text"], relief="flat",
                                bd=0, highlightthickness=1,
                                highlightbackground=T["border"],
                                state="disabled")
        self.cmd_text.pack(fill="both", expand=True)

    def _path_row(self, parent, row, i18n_key, on_pick,
                  kind="gguf", with_clear=False):
        """Label + entry + browse + scan (+ clear) block; returns the entry.

        i18n_key is the translation key for the row label (also used to
        keep the widget refs for _apply_i18n); kind stays the scan kind
        ("gguf" or "exe")."""
        lbl = ttk.Label(parent, text=self.t(i18n_key), style="Dim.TLabel")
        lbl.grid(row=row, column=0, columnspan=4, sticky="w", pady=(8, 1))
        e = ttk.Entry(parent)
        e.grid(row=row + 1, column=0, columnspan=2, sticky="we", padx=(0, 4))
        browse = flat_button(parent, self.t("btn.browse"), on_pick,
                             kind="default", font=FONT_SM)
        browse.grid(row=row + 1, column=2, padx=(0, 3))
        scan = flat_button(parent, self.t("btn.scan"),
                           lambda: self.on_scan(e, kind),
                           kind="default", font=FONT_SM)
        scan.grid(row=row + 1, column=3, padx=(0, 3))
        clear = None
        if with_clear:
            clear = flat_button(parent, self.t("btn.clear"),
                                lambda: (e.delete(0, "end"),
                                         self._on_param_change()),
                                kind="ghost", font=FONT_SM)
            clear.grid(row=row + 1, column=4, padx=(0, 2))
        e.bind("<KeyRelease>", lambda _ev: self._on_param_change())
        self._path_row_refs[i18n_key] = {
            "i18n": i18n_key, "label": lbl,
            "browse": browse, "scan": scan, "clear": clear,
        }
        return e

    def _file_dialog(self, files, on_pick):
        """Modal listbox picker; double-click or 打开 selects."""
        win = tk.Toplevel(self.root)
        win.title(self.t("dlg.pickFile"))
        win.geometry("620x460")
        win.configure(bg=T["panel"])
        win.transient(self.root)
        lb = tk.Listbox(win, activestyle="none", exportselection=False,
                        font=FONT_MONO, bg=T["input"], fg=T["text"],
                        relief="flat", bd=0, highlightthickness=1,
                        highlightbackground=T["border"],
                        selectbackground=T["accent"],
                        selectforeground=T["accent_dim"])
        for p in files:
            lb.insert("end", p)
        sb = ttk.Scrollbar(win, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        sb.pack(side="left", fill="y", pady=10)
        btns = tk.Frame(win, bg=T["panel"])
        btns.pack(side="bottom", fill="x", padx=10, pady=(0, 10))

        def _confirm():
            sel = lb.get("active")
            if sel:
                on_pick(sel)
            win.destroy()

        flat_button(btns, self.t("btn.open"), _confirm, kind="primary",
                    font=FONT_MD).pack(side="right")
        flat_button(btns, self.t("btn.cancel"), win.destroy, kind="default",
                    font=FONT_MD).pack(side="right", padx=8)
        lb.bind("<Double-Button-1>", lambda _e: _confirm())

    def on_scan(self, entry, kind):
        text = entry.get().strip()
        base = text if os.path.isdir(text) else os.path.dirname(text)
        if not base or not os.path.isdir(base):
            base = filedialog.askdirectory(title=self.t("dlg.scanDir"))
            if not base:
                return
        files = core.scan_files(base, kind)
        if not files:
            messagebox.showinfo(self.t("msg.scanTitle"), self.t("msg.scanEmpty"))
            return
        self._file_dialog(files, lambda p: (
            entry.delete(0, "end"), entry.insert(0, p), self._on_param_change()))

    def on_pick_exe(self):
        p = filedialog.askopenfilename(title=self.t("dlg.pickExe"),
                                        filetypes=[(self.t("dlg.exes"), "*.exe"),
                                                   (self.t("dlg.all"), "*")])
        if p:
            self.entry_exe.delete(0, "end")
            self.entry_exe.insert(0, p)
            self._on_param_change()

    def on_pick_model(self):
        p = filedialog.askopenfilename(title=self.t("dlg.pickModel"),
                                        filetypes=[(self.t("dlg.gguf"), "*.gguf"),
                                                   (self.t("dlg.all"), "*")])
        if p:
            self.entry_model.delete(0, "end")
            self.entry_model.insert(0, p)
            self._on_param_change()

    def on_pick_mmproj(self):
        p = filedialog.askopenfilename(title=self.t("dlg.pickMmproj"),
                                        filetypes=[(self.t("dlg.gguf"), "*.gguf"),
                                                   (self.t("dlg.all"), "*")])
        if p:
            self.entry_mmproj.delete(0, "end")
            self.entry_mmproj.insert(0, p)
            self._on_param_change()

    # -- center column: monitor + token stats -----------------------------
    def _build_center(self, body):
        cont = tk.Frame(body, bg=T["bg"])
        body.add(cont, weight=3)
        cont.columnconfigure(0, weight=1)
        cont.rowconfigure(0, weight=3)
        cont.rowconfigure(1, weight=2)

        mon_o, mon, _h, self.lbl_card_monitor = card(cont, self.t("sec.monitor"))
        mon_o.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        mon.columnconfigure(1, weight=1)
        self.sp_cpu = Sparkline(mon)
        self.sp_mem = Sparkline(mon)
        self.sp_gpu = Sparkline(mon)
        self.sp_vram = Sparkline(mon)
        rows = [("mon.cpu", self.sp_cpu), ("mon.mem", self.sp_mem),
                ("mon.gpuUtil", self.sp_gpu), ("mon.vram", self.sp_vram)]
        for i, (key, sp) in enumerate(rows):
            lbl = ttk.Label(mon, text=self.t(key), style="Dim.TLabel")
            lbl.grid(row=i, column=0, sticky="w", padx=(0, 8))
            sp.canvas.grid(row=i, column=1, columnspan=2, sticky="we",
                           padx=2, pady=2)
            self._mon_row_labels[key] = lbl
        self.lbl_gpu_info = tk.Label(mon, text="", font=FONT_SM,
                                     bg=T["panel"], fg=T["dim"])
        self.lbl_gpu_info.grid(row=4, column=0, columnspan=3, sticky="w",
                               pady=(2, 2))

        tok_o, tok, _h2, self.lbl_card_tokens = card(cont, self.t("sec.tokens"))
        tok_o.grid(row=1, column=0, sticky="nsew")
        tok.columnconfigure(1, weight=1)
        self.lbl_live = tk.Label(tok, text=self.t("tok.idle"), font=FONT_BOLD,
                                 bg=T["panel"], fg=T["dim"])
        self.lbl_live.grid(row=0, column=0, columnspan=2, sticky="w",
                           pady=(0, 4))
        self.pb_prompt = ttk.Progressbar(tok, maximum=100, value=0)
        self.pb_prompt.grid(row=1, column=0, columnspan=2, sticky="we",
                            pady=(0, 6))
        # tok_labels is keyed by the stable i18n key (not the translated
        # text) so _render_* and the tests work in either language.
        self._tok_row(tok, 2, "promptSpeed")
        self._tok_row(tok, 3, "genSpeed")
        self._tok_row(tok, 4, "promptTokens")
        self._tok_row(tok, 5, "genTokens")
        self._tok_row(tok, 6, "avgTps")
        self._tok_row(tok, 7, "instTps")
        self._tok_row(tok, 8, "specRate")

    def _tok_row(self, parent, row, key):
        row_lbl = ttk.Label(parent, text=self.t(f"tok.{key}"),
                            style="Dim.TLabel")
        row_lbl.grid(row=row, column=0, sticky="w", pady=1)
        lbl = tk.Label(parent, text="-", font=FONT_MONO,
                       bg=T["panel"], fg=T["accent"])
        lbl.grid(row=row, column=1, sticky="e", padx=(12, 0))
        self.tok_labels[key] = lbl
        self._tok_row_labels[key] = row_lbl
        return lbl

    # -- right column: parameter tabs --------------------------------------
    # Tab keys stay the Chinese titles (stable identifiers); PARAM_TAB_I18N
    # maps them to the i18n key used for the button label.
    PARAM_TABS = [
        ("采样", ["temperature", "top_k", "top_p", "min_p", "seed"]),
        ("上下文与批处理", ["ctx_size", "batch_size", "ubatch_size", "threads",
                           "parallel"]),
        ("GPU 与 KV 缓存", ["n_gpu_layers", "cache_type_k", "cache_type_v",
                            "flash_attn", "mlock", "no_mmap"]),
        ("高级", ["cont_batching", "jinja", "metrics", "reasoning",
                  "reasoningBudget", "specType", "spec_draft_n_max",
                  "spec_draft_p_min"]),
        ("网络", ["host", "port", "apiKey"]),
        ("额外参数", ["extraArgs"]),
    ]
    PARAM_TAB_I18N = {
        "采样": "grp.sampling",
        "上下文与批处理": "grp.ctx",
        "GPU 与 KV 缓存": "grp.gpu",
        "高级": "grp.advanced",
        "网络": "grp.network",
        "额外参数": "grp.extra",
    }

    def _build_right(self, body):
        outer, f, _h, self.lbl_card_params = card(body, self.t("sec.params"))
        body.add(outer, weight=4)
        bar = tk.Frame(f, bg=T["panel"])
        bar.pack(fill="x", pady=(0, 8))
        for i, (title, _keys) in enumerate(self.PARAM_TABS):
            btn = flat_button(bar, self.t(self.PARAM_TAB_I18N[title]),
                              lambda t=title: self._select_tab(t),
                              kind="ghost", font=FONT_SM)
            btn.grid(row=i // 3, column=i % 3, sticky="we", padx=2, pady=2)
            self._tab_btns[title] = btn
        for c in range(3):
            bar.columnconfigure(c, weight=1)

        # no vertical scrollbar — every tab's content fits at normal
        # window sizes. The content still sits on a canvas so the mouse
        # wheel can scroll it if the user shrinks the window below the
        # content height.
        self._tab_canvas = tk.Canvas(f, bg=T["panel"], highlightthickness=0)
        self._tab_canvas.pack(fill="both", expand=True)
        self._tab_container = tk.Frame(self._tab_canvas, bg=T["panel"])
        win_id = self._tab_canvas.create_window(
            (0, 0), window=self._tab_container, anchor="nw")
        self._tab_container.bind(
            "<Configure>",
            lambda _e: self._tab_canvas.configure(
                scrollregion=self._tab_canvas.bbox("all")))
        self._tab_canvas.bind(
            "<Configure>",
            lambda e: self._tab_canvas.itemconfigure(win_id, width=e.width))
        self._tab_canvas.bind("<MouseWheel>", self._tab_wheel)
        for title, keys in self.PARAM_TABS:
            tab = tk.Frame(self._tab_container, bg=T["panel"])
            tab.grid(row=0, column=0, sticky="nsew")
            tab.columnconfigure(0, weight=1)
            for i, key in enumerate(keys):
                self._build_param(tab, i * 2, key)
            self._tab_frames[title] = tab
        self._select_tab(self.PARAM_TABS[0][0])

    def _tab_wheel(self, e):
        """Mouse-wheel scroll for the parameter panel (scrollbar removed)."""
        self._tab_canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")

    def _select_tab(self, title):
        for t, fr in self._tab_frames.items():
            if t == title:
                fr.lift()
        for t, btn in self._tab_btns.items():
            if t == title:
                btn.configure(bg=T["accent"], fg=T["accent_dim"])
            else:
                btn.configure(bg=T["input"], fg=T["dim"])

    def _param_label(self, key):
        """Translated display label for a parameter key (zh or en)."""
        if self.lang == "en":
            return PARAM_LABELS_EN.get(key, core.PARAM_LABELS.get(key, key))
        return core.PARAM_LABELS.get(key, key)

    def _build_param(self, tab, row, key):
        """Create the widget for one parameter key; returns nothing.

        The text-bearing widget (label or checkbutton) is kept in
        self._param_labels[key] for _apply_i18n retranslation."""
        if key == "extraArgs":
            lbl = ttk.Label(tab, text=self.t("extra.hint"),
                            style="Dim.TLabel")
            lbl.grid(row=row, column=0, sticky="w", pady=(10, 1))
            e = tk.Text(tab, height=3, width=40, wrap="word", font=FONT_MONO,
                        bg=T["input"], fg=T["text"], relief="flat", bd=0,
                        highlightthickness=1,
                        highlightbackground=T["border"],
                        insertbackground=T["text"])
            # fixed width so the box's right edge is always visible.
            e.grid(row=row + 1, column=0, sticky="nw", pady=(0, 8))
            e.bind("<KeyRelease>", lambda _ev: self._on_param_change())
            self.param_widgets[key] = e
            self._param_labels[key] = lbl
            return
        if key in ("host", "port", "apiKey"):
            lbl = ttk.Label(tab, text=self._param_label(key),
                            style="Dim.TLabel")
            lbl.grid(row=row, column=0, sticky="w", pady=(10, 1))
            # fixed width so the box's right edge is always visible.
            e = ttk.Entry(tab, width=24)
            e.grid(row=row + 1, column=0, sticky="w", pady=(0, 8))
            e.bind("<KeyRelease>", lambda _ev: self._on_param_change())
            self.param_widgets[key] = e
            self._param_labels[key] = lbl
            return
        if key in core.SELECT_KEYS:
            lbl = ttk.Label(tab, text=self._param_label(key),
                            style="Dim.TLabel")
            lbl.grid(row=row, column=0, sticky="w", pady=(10, 1))
            # fixed width so the box's right edge is always visible.
            w = ttk.Combobox(tab, values=core.SELECT_KEYS[key],
                             state="readonly", width=18)
            w.grid(row=row + 1, column=0, sticky="w", pady=(0, 8))
            w.bind("<<ComboboxSelected>>", lambda _ev: self._on_param_change())
            self.param_widgets[key] = w
            self._param_labels[key] = lbl
            return
        if key in core.SWITCH_KEYS:
            var = tk.BooleanVar()
            cb = ttk.Checkbutton(tab, text=self._param_label(key),
                                 variable=var, command=self._on_param_change)
            cb.grid(row=row, column=0, sticky="w", pady=(8, 2))
            self.param_widgets[key] = var  # store the Variable, not the widget
            self._param_labels[key] = cb
            return
        lo, hi, step, _def = core.PARAM_DEFS[key]
        lbl = ttk.Label(tab, text=self._param_label(key), style="Dim.TLabel")
        lbl.grid(row=row, column=0, sticky="w", pady=(10, 1))
        # fixed width so the box's right edge is always visible.
        sp = ttk.Spinbox(tab, from_=lo, to=hi, increment=step, width=12)
        sp.grid(row=row + 1, column=0, sticky="w", pady=(0, 8))
        sp.bind("<KeyRelease>", lambda _ev: self._on_param_change())
        # Commit (snap to a nearby valid value) only when editing finishes:
        # pressing Enter, or moving focus elsewhere (click / Tab away).
        sp.bind("<Return>", lambda _ev, k=key: self._on_commit(k))
        sp.bind("<FocusOut>", lambda _ev, k=key: self._on_commit(k))
        self.param_widgets[key] = sp
        self._param_labels[key] = lbl

    # -- bottom: log (启动命令 moved to the left column) ----------------------
    def _build_bottom(self, vbody):
        # the log card is the lower pane of a vertical PanedWindow
        # (see _build_ui), so it gets a large, user-adjustable height.
        wrap = tk.Frame(vbody, bg=T["bg"])
        vbody.add(wrap)
        log_o, log, log_head, self.lbl_card_logs = card(wrap, self.t("sec.logs"))
        log_o.pack(fill="both", expand=True)
        self.btn_pause = flat_button(log_head, self.t("btn.pause"),
                                     self._toggle_pause,
                                     kind="default", font=FONT_SM)
        self.btn_pause.pack(side="right")
        self.btn_clear_log = flat_button(log_head, self.t("btn.clearLog"),
                                         self._clear_log,
                                         kind="default", font=FONT_SM)
        self.btn_clear_log.pack(side="right", padx=(0, 4))
        self.btn_copy_log = flat_button(log_head, self.t("btn.copyLog"),
                                        self._copy_log,
                                        kind="default", font=FONT_SM)
        self.btn_copy_log.pack(side="right", padx=(0, 4))
        self.log_text = ScrolledText(log, height=8, wrap="none",
                                     font=FONT_MONO, bg=T["input"],
                                     fg=T["text"], relief="flat", bd=0,
                                     highlightthickness=1,
                                     highlightbackground=T["border"],
                                     state="disabled")
        self.log_text.tag_configure("err", foreground=T["err"])
        self.log_text.tag_configure("warn", foreground=T["warn"])
        self.log_text.pack(fill="both", expand=True)

    # -- parameter state ----------------------------------------------------
    def _on_param_change(self):
        """Any widget edit: refresh preview + debounce settings save.

        Numeric fields are deliberately NOT rewritten here — doing so would
        clobber a value the user is still typing (e.g. a "1" that is on its
        way to "128000").  Clamping happens only on commit: when the user
        presses <Return> in the field or focus leaves it (<FocusOut>).
        See _on_commit() / _commit_param().
        """
        self._update_cmd_preview()
        self._update_poll_target()
        if self._save_timer is not None:
            self.root.after_cancel(self._save_timer)
        self._save_timer = self.root.after(500, self._save_settings)

    def _all_param_keys(self):
        return (list(core.PARAM_DEFS) + list(core.SELECT_KEYS)
                + core.SWITCH_KEYS)

    def _set_widget(self, key, value):
        w = self.param_widgets.get(key)
        if w is None:
            return
        try:
            if key in core.SWITCH_KEYS:
                w.set(bool(value))
            elif key in core.SELECT_KEYS:
                # Combobox: set() writes the entry text (delete/insert would
                # corrupt the dropdown item list).
                w.set(value)
            else:
                w.delete(0, "end")
                w.insert(0, value)
        except (tk.TclError, ValueError):
            pass

    def _get_params(self):
        """Read all widgets into a params dict (clamped by core)."""
        out = {}
        keys = list(core.PARAM_DEFS) + list(core.SELECT_KEYS) + core.SWITCH_KEYS
        for key in keys:
            w = self.param_widgets.get(key)
            if w is None:
                continue
            if key in core.SWITCH_KEYS:
                out[key] = bool(w.get())
            elif key in core.SELECT_KEYS:
                out[key] = w.get()
            else:
                out[key] = core.clamp_val(key, w.get())
        return out

    def _on_commit(self, key):
        """Field editing finished (Enter or focus-out): clamp, then refresh."""
        self._commit_param(key)
        self._on_param_change()

    def _commit_param(self, key):
        """Commit one numeric field: clamp to [min, max] and rewrite it.

        Called only when the user finishes editing the field, never
        mid-keystroke, so a value still being typed (e.g. "1" on the way to
        "128000") is left untouched until then.
        """
        w = self.param_widgets.get(key)
        if w is None or key in core.SWITCH_KEYS:
            return
        try:
            raw = w.get()
            parsed = float(raw)
        except (tk.TclError, ValueError):
            return  # non-numeric; leave as-is
        clamped = core.clamp_val(key, raw)
        if parsed != clamped:
            w.delete(0, "end")
            w.insert(0, core.fmt_val(key, clamped))

    def _clamp_params(self):
        """Commit (clamp) every numeric field; used before launch."""
        for key in core.PARAM_DEFS:
            self._commit_param(key)

    def _model_entry(self):
        return self.entry_model.get().strip()

    def _get_extra_args(self):
        """extraArgs is a multi-line Text widget; read without the newline."""
        return self.param_widgets["extraArgs"].get("1.0", "end-1c").strip()

    def _set_extra_args(self, value):
        w = self.param_widgets["extraArgs"]
        w.delete("1.0", "end")
        w.insert("1.0", value or "")

    def _port_value(self):
        """Parse the port widget; clamp to 1-65535, default 8080."""
        try:
            v = int(float(self.param_widgets["port"].get()))
        except (tk.TclError, ValueError):
            return 8080
        return min(65535, max(1, v))

    def _update_cmd_preview(self):
        s = self.settings
        model = self._model_entry()
        params = self._get_params()
        host = (self.param_widgets["host"].get().strip() or "127.0.0.1")
        port = self._port_value()
        api_key = self.param_widgets["apiKey"].get().strip()
        extra = self._get_extra_args()
        argv, ignored = core.build_argv(
            s["serverExe"], model, params,
            mmproj=self.entry_mmproj.get().strip(),
            extra_args=extra, host=host, port=port, api_key=api_key)
        text = core.shlex_join(argv)
        self.cmd_text.configure(state="normal")
        self.cmd_text.delete("1.0", "end")
        self.cmd_text.insert("1.0", text)
        self.cmd_text.configure(state="disabled")
        if ignored:
            self.lbl_match.configure(
                text=self.t("msg.ignored", list=", ".join(ignored)),
                foreground=T["warn"])
        else:
            self.lbl_match.configure(text="")

    # -- presets & settings --------------------------------------------------
    def _refresh_presets(self):
        models = self.settings.get("models", {})
        names = [self.t("noPreset")] + sorted(models.keys())
        self.cmb_preset.configure(values=names)
        cur = self._model_entry()
        idx = names.index(cur) if cur in names else 0
        self.cmb_preset.current(idx)

    def on_preset(self, _event=None):
        name = self.cmb_preset.get()
        if name == self.t("noPreset"):
            return
        entry = self.settings.get("models", {}).get(name)
        if not entry:
            return
        self.entry_model.delete(0, "end")
        self.entry_model.insert(0, name)
        self.entry_mmproj.delete(0, "end")
        self.entry_mmproj.insert(0, entry.get("mmproj", ""))
        params = dict(core.DEFAULT_PARAMS)
        params.update(entry.get("params", {}))
        for key in self._all_param_keys():
            self._set_widget(key, params.get(key))
        self._set_extra_args(entry.get("extraArgs", ""))
        self._on_param_change()

    def _load_settings_to_ui(self):
        s = self.settings
        self.entry_exe.delete(0, "end")
        self.entry_exe.insert(0, s.get("serverExe", ""))
        last = s.get("lastModel", "")
        self.entry_model.delete(0, "end")
        self.entry_model.insert(0, last)
        if last:
            entry = s.get("models", {}).get(last)
            if entry:
                self.entry_mmproj.delete(0, "end")
                self.entry_mmproj.insert(0, entry.get("mmproj", ""))
                params = dict(core.DEFAULT_PARAMS)
                params.update(entry.get("params", {}))
                for key in self._all_param_keys():
                    self._set_widget(key, params.get(key))
                self._set_extra_args(entry.get("extraArgs", ""))
                self.lbl_restored.configure(text=self.t("hint.restored"))
            else:
                self._apply_defaults()
        else:
            self._apply_defaults()
        g = s.get("global", {})
        self.param_widgets["host"].delete(0, "end")
        self.param_widgets["host"].insert(0, g.get("host", "127.0.0.1"))
        self.param_widgets["port"].delete(0, "end")
        self.param_widgets["port"].insert(0, g.get("port", 8080))
        self.param_widgets["apiKey"].delete(0, "end")
        self.param_widgets["apiKey"].insert(0, g.get("apiKey", ""))
        self._refresh_presets()
        self._update_cmd_preview()
        self._update_poll_target()

    def _apply_defaults(self):
        for key, val in core.DEFAULT_PARAMS.items():
            self._set_widget(key, val)
        for key in core.SELECT_KEYS:
            self._set_widget(key, core.DEFAULT_PARAMS[key])
        for key in core.SWITCH_KEYS:
            self._set_widget(key, core.DEFAULT_PARAMS[key])
        self._set_extra_args("")
        self.lbl_restored.configure(text="")

    def _save_settings(self):
        """Persist the shared settings.json (same schema as the web version)."""
        model = self._model_entry()
        s = self.settings
        s["serverExe"] = self.entry_exe.get().strip()
        if model:
            s["lastModel"] = model
        s["language"] = self.lang  # shared with the web version
        g = s.setdefault("global", {})
        g["host"] = self.param_widgets["host"].get().strip() or "127.0.0.1"
        g["port"] = self._port_value()
        g["apiKey"] = self.param_widgets["apiKey"].get().strip()
        models = s.setdefault("models", {})
        if model:
            models[model] = {
                "mmproj": self.entry_mmproj.get().strip(),
                "params": self._get_params(),
                "extraArgs": self._get_extra_args(),
            }
        try:
            core.save_settings(s)
        except OSError as e:
            messagebox.showerror(self.t("msg.saveFail"), str(e))

    # -- background pollers ---------------------------------------------------
    def _start_pollers(self):
        threading.Thread(target=self._monitor_loop, daemon=True).start()
        threading.Thread(target=self._info_loop, daemon=True).start()

    def _monitor_loop(self):
        while True:
            try:
                self.ui_q.put(("monitor", core.get_monitor()))
            except Exception:
                pass
            time.sleep(1.5)

    def _info_loop(self):
        while True:
            host, port = self._poll_host, self._poll_port
            if core.mgr.status()["state"] == "running":
                try:
                    info = core.get_server_info(host, port)
                    if info.get("ok"):
                        self.ui_q.put(("metrics", info.get("metrics")))
                        time.sleep(2)
                        continue
                except Exception:
                    pass
            self.ui_q.put(("metrics", None))
            time.sleep(2)

    def _update_poll_target(self):
        """Main-thread: publish host/port for the background info loop."""
        self._poll_host = (self.param_widgets["host"].get().strip()
                           or "127.0.0.1")
        self._poll_port = self._port_value()

    # -- UI queue pump (main thread) -----------------------------------------
    def _poll_ui(self):
        try:
            while True:
                kind, payload = self.ui_q.get_nowait()
                if kind == "line":
                    self._append_log(payload)
                    self._handle_live_line(payload)
                elif kind == "state":
                    self._render_state(payload)
                elif kind == "monitor":
                    self._render_monitor(payload)
                elif kind == "metrics":
                    self.last_metrics = payload
                    self._render_token_stats()
        except queue.Empty:
            pass
        self.root.after(100, self._poll_ui)

    def _on_line(self, line):
        self.ui_q.put(("line", line))

    def _on_state(self, state):
        self.ui_q.put(("state", state))

    def _append_log(self, line):
        low = line.lower()
        tag = "err" if "error" in low else ("warn" if "warn" in low else None)
        self.log_text.configure(state="normal")
        stamp = time.strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{stamp}] {line}\n", tag)
        self.log_text.see("end")
        # keep bounded
        if int(self.log_text.index("end-1c").split(".")[0]) > 4000:
            self.log_text.delete("1.0", "1000.0")
        if not self.log_paused:
            self.log_text.yview_moveto(1.0)
        self.log_text.configure(state="disabled")

    def _handle_live_line(self, line):
        hit = parse_live_stats(line, self.live)
        if hit is None:
            return
        update_tok_acc(self.tok_acc, hit)
        self._render_live()

    def _render_live(self):
        s = self.live
        if s["mode"] == "prompt":
            self.lbl_live.configure(
                text=f"{self.t('tok.prompting')}  {s['progress'] * 100:.0f}%",
                foreground=T["accent"])
            self.pb_prompt.configure(value=s["progress"] * 100)
            self.tok_labels["promptSpeed"].configure(
                text=f"{s['ppTps']:.1f} tok/s（{s['nTokens']:,} tokens）")
            self.tok_labels["genSpeed"].configure(text="-")
        elif s["mode"] == "gen":
            self.lbl_live.configure(text=self.t("tok.generating"),
                                    foreground=T["ok"])
            self.pb_prompt.configure(value=0)
            self.tok_labels["promptSpeed"].configure(text="-")
            self.tok_labels["genSpeed"].configure(
                text=f"tg {s['tg']:.1f} · tg_3s {s['tg3']:.1f} tok/s")
        else:
            self.lbl_live.configure(text=self.t("tok.idle"), foreground=T["dim"])
            self.pb_prompt.configure(value=0)
            self.tok_labels["promptSpeed"].configure(text="-")
            self.tok_labels["genSpeed"].configure(text="-")
        self._render_token_stats()

    def _render_state(self, st):
        state = st.get("state")
        if state == "starting":
            self._set_running_ui(True, self.t("status.starting"), T["accent"])
            self.tok_acc = fresh_tok_acc()
            self.live = {"mode": "idle"}
            self.last_metrics = None
            self._render_live()
            self._render_token_stats()
        elif state == "running":
            self._set_running_ui(True, self.t("status.running"), T["ok"])
        elif state == "exited":
            code = st.get("exitCode")
            self._set_running_ui(False, self.t("status.exited", code=code),
                                 T["err"])
            self.tok_acc = fresh_tok_acc()
            self.live = {"mode": "idle"}
            self.last_metrics = None
            self._render_live()
            self._render_token_stats()
        else:  # stopped
            self._set_running_ui(False, self.t("status.stopped"), T["dim"])

    def _set_running_ui(self, running, text, color):
        self.status_label.configure(text=text, foreground=color)
        self.status_dot.configure(fg=color)
        set_button_state(self.btn_start, "disabled" if running else "normal")
        set_button_state(self.btn_stop, "normal" if running else "disabled")

    def _render_monitor(self, d):
        self.last_monitor = d
        cpu = d.get("cpu") or {}
        mem = d.get("mem") or {}
        gpu = d.get("gpu")
        self.sp_cpu.push(float(cpu.get("percent") or 0))
        self.sp_mem.push(float(mem.get("percent") or 0))
        self.sp_gpu.push(float((gpu or {}).get("util") or 0))
        vram = 0.0
        if gpu and gpu.get("memTotal"):
            vram = float(gpu["memUsed"]) / float(gpu["memTotal"]) * 100.0
        self.sp_vram.push(vram)
        if gpu:
            parts = [gpu.get("name") or "GPU"]
            if gpu.get("temp") is not None:
                parts.append(f"{gpu['temp']:.0f}°C")
            if gpu.get("power") is not None:
                parts.append(f"{gpu['power']:.1f} W")
            # No unit suffix: the middle column is narrow and the MiB
            # values are self-evident (e.g. 15,893/16,303).
            parts.append(f"{(gpu.get('memUsed') or 0):,}/"
                         f"{(gpu.get('memTotal') or 0):,}")
            self.lbl_gpu_info.configure(text=" · ".join(parts))
        else:
            self.lbl_gpu_info.configure(text=self.t("mon.noGpu"))

    def _render_token_stats(self):
        m = self.last_metrics or {}
        acc = self.tok_acc
        p_total = (m.get("promptTokensTotal")
                   if isinstance(m.get("promptTokensTotal"), (int, float))
                   and m.get("promptTokensTotal") > 0
                   else acc["promptTokens"])
        g_total = (m.get("tokensPredictedTotal")
                   if isinstance(m.get("tokensPredictedTotal"), (int, float))
                   and m.get("tokensPredictedTotal") > 0
                   else acc["genTokens"])
        self.tok_labels["promptTokens"].configure(text=f"{int(p_total):,}")
        self.tok_labels["genTokens"].configure(text=f"{int(g_total):,}")
        avg = (acc["genTokens"] / acc["genTime"]) if acc["genTime"] > 0 else None
        if avg is None and isinstance(m.get("predictedTokPerSec"), (int, float)) \
                and m["predictedTokPerSec"] > 0:
            avg = m["predictedTokPerSec"]
        self.tok_labels["avgTps"].configure(
            text=f"{avg:.1f} tok/s" if avg is not None else "0.0 tok/s")
        s = self.live
        if s["mode"] == "gen" and isinstance(s.get("tg"), (int, float)):
            inst = s["tg"]
        elif s["mode"] == "prompt" and isinstance(s.get("ppTps"), (int, float)):
            inst = s["ppTps"]
        else:
            inst = 0.0
        self.tok_labels["instTps"].configure(text=f"{inst:.1f} tok/s")
        draft = m.get("specDraftTokensTotal") or 0
        accpt = m.get("specAcceptedTokensTotal") or 0
        if draft and draft > 0:
            self.tok_labels["specRate"].configure(
                text=f"{accpt / draft * 100:.1f}%")
        else:
            self.tok_labels["specRate"].configure(text="-")

    # -- actions --------------------------------------------------------------
    def on_start(self):
        s = self.settings
        exe = self.entry_exe.get().strip()
        model = self._model_entry()
        if not exe or not model:
            messagebox.showerror(self.t("msg.noServerTitle"),
                                  self.t("msg.noServer"))
            return
        s["serverExe"] = exe  # sync widget into settings (save is debounced)
        self._clamp_params()  # commit all numeric fields: display == launch
        params = self._get_params()
        host = self.param_widgets["host"].get().strip() or "127.0.0.1"
        port = self._port_value()
        api_key = self.param_widgets["apiKey"].get().strip()
        argv, ignored = core.build_argv(
            exe, model, params,
            mmproj=self.entry_mmproj.get().strip(),
            extra_args=self._get_extra_args(),
            host=host, port=port, api_key=api_key)
        if ignored:
            messagebox.showwarning(
                self.t("msg.dupeTitle"),
                self.t("msg.dupe", list=", ".join(ignored)))
        threading.Thread(target=self._do_start, args=(argv,), daemon=True).start()

    def _do_start(self, argv):
        ok, err, _pid = core.mgr.start(argv)
        if not ok:
            self.ui_q.put(("state", {"state": "stopped",
                                     "error": err}))
            self.root.after(0, lambda: messagebox.showerror(
                self.t("msg.startFail"), err))

    def on_stop(self):
        threading.Thread(target=self._do_stop, daemon=True).start()

    def _do_stop(self):
        core.mgr.stop()

    def _toggle_pause(self):
        self.log_paused = not self.log_paused
        self.btn_pause.configure(text=self.t("btn.resume") if self.log_paused
                                 else self.t("btn.pause"))
        if not self.log_paused:
            self.log_text.yview_moveto(1.0)

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _copy_cmd(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.cmd_text.get("1.0", "end").strip())

    def _copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log_text.get("1.0", "end"))

    def _on_close(self):
        try:
            if self._save_timer is not None:
                self.root.after_cancel(self._save_timer)
            # Never leave llama-server running in the background when the
            # launcher window closes.
            if core.mgr.status().get("state") in ("starting", "running"):
                self._append_log(self.t("log.closing"))
                core.mgr.stop()
                self._append_log(self.t("log.stopped"))
            self._save_settings()
        except Exception:
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
