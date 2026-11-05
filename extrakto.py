#!/usr/bin/env python3
"""rex-extrakto: Interactive text extractor and fuzzy selector for Rex.

Extracted from and inspired by laktak/extrakto, adapted natively for Rex.
"""

from __future__ import annotations

import argparse
import configparser
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

T_START = time.perf_counter()


def log_timing(msg: str) -> None:
    elapsed = (time.perf_counter() - T_START) * 1000
    try:
        with open("/tmp/extrakto_timing.log", "a") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] [{elapsed:7.2f}ms] {msg}\n")
    except Exception:
        pass


log_timing("extrakto.py module loaded")

SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULT_FILTERS = ["all", "path", "url", "word", "line", "quote"]
GRAB_AREAS = ["recent", "full", "window"]


class FilterDef:
    def __init__(
        self,
        name: str,
        regex: str,
        exclude: str = "",
        lstrip: str = "",
        rstrip: str = "",
        in_all: bool = True,
    ):
        self.name = name
        self.regex = regex
        self.exclude = exclude
        self.lstrip = lstrip
        self.rstrip = rstrip
        self.in_all = in_all
        try:
            self._compiled = re.compile(regex, re.IGNORECASE)
        except re.error:
            self._compiled = None
        try:
            self._compiled_exclude = re.compile(exclude, re.IGNORECASE) if exclude else None
        except re.error:
            self._compiled_exclude = None

    def extract(self, text: str, min_length: int = 1) -> List[str]:
        if not self._compiled:
            return []

        results: List[str] = []
        for match in self._compiled.finditer(text):
            groups = [g for g in match.groups() if g]
            val = "".join(groups) if groups else match.group(0)

            if self.lstrip:
                val = val.lstrip(self.lstrip)
            if self.rstrip:
                val = val.rstrip(self.rstrip)

            val = val.strip()

            if len(val) < min_length:
                continue

            if self._compiled_exclude and self._compiled_exclude.search(val):
                continue

            if val:
                results.append(val)

        return results


class ExtraktoEngine:
    def __init__(self, min_length: int = 5):
        self.min_length = min_length
        self.filters: Dict[str, FilterDef] = {}
        self.filter_order: List[str] = []
        self._load_configs()

    def _load_configs(self) -> None:
        cfg = configparser.ConfigParser(interpolation=None)
        config_files = [
            SCRIPT_DIR / "extrakto.conf",
            Path.home() / ".config" / "extrakto" / "extrakto.conf",
            Path.home() / ".config" / "rex" / "extrakto.conf",
        ]

        valid_files = [str(f) for f in config_files if f.is_file()]
        if valid_files:
            cfg.read(valid_files)

        for section in cfg.sections():
            regex = cfg.get(section, "regex", fallback="")
            if not regex:
                continue
            exclude = cfg.get(section, "exclude", fallback="")
            lstrip = cfg.get(section, "lstrip", fallback="")
            rstrip = cfg.get(section, "rstrip", fallback="")
            in_all = cfg.getboolean(section, "in_all", fallback=True)

            self.filters[section] = FilterDef(
                name=section,
                regex=regex,
                exclude=exclude,
                lstrip=lstrip,
                rstrip=rstrip,
                in_all=in_all,
            )
            self.filter_order.append(section)

    def extract(self, text: str, mode: str) -> List[str]:
        # Process lines in reverse order so recent items appear first
        lines = text.splitlines()
        rev_text = "\n".join(reversed(lines))

        raw_items: List[str] = []

        if mode == "line":
            for line in reversed(lines):
                s = line.strip()
                if len(s) >= self.min_length:
                    raw_items.append(s)
        elif mode == "all":
            # Run enabled in_all filters
            for name, fdef in self.filters.items():
                if fdef.in_all:
                    min_len = self.min_length if name == "word" else 2
                    raw_items.extend(fdef.extract(rev_text, min_length=min_len))
        elif mode in self.filters:
            fdef = self.filters[mode]
            min_len = self.min_length if mode == "word" else 2
            raw_items.extend(fdef.extract(rev_text, min_length=min_len))
        else:
            # Fallback word extraction
            word_def = self.filters.get("word")
            if word_def:
                raw_items.extend(word_def.extract(rev_text, min_length=self.min_length))

        # Deduplicate while preserving order (most recent first)
        seen = set()
        deduped: List[str] = []
        for item in raw_items:
            if item not in seen:
                seen.add(item)
                deduped.append(item)

        return deduped


def capture_rex(session_id: str, block_id: str, grab_area: str) -> str:
    """Capture terminal output from Rex CLI."""
    if grab_area == "window":
        # Capture all placed blocks in the session
        cmd = ["rex", "block", "ls", "-s", session_id, "--json"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        all_text = []
        if proc.returncode == 0:
            try:
                data = json.loads(proc.stdout)
                for b in data.get("blocks", []):
                    b_id = b.get("block_id")
                    if b.get("creator_name") == "com.superlogical.terminal" and b_id:
                        cap = subprocess.run(
                            ["rex", "capture", "-s", session_id, "-b", b_id, "--trim"],
                            capture_output=True,
                            text=True,
                        )
                        if cap.returncode == 0:
                            all_text.append(cap.stdout)
            except json.JSONDecodeError:
                pass
        if all_text:
            return "\n".join(all_text)

    # Default to target block capture
    cmd = ["rex", "capture", "-s", session_id, "-b", block_id, "--trim"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = proc.stdout if proc.returncode == 0 else ""

    if grab_area == "recent":
        # Keep the most recent 120 lines
        lines = out.splitlines()
        return "\n".join(lines[-120:])

    return out


def copy_to_clipboard(text: str) -> None:
    """Copy text to system clipboard."""
    if sys.platform == "darwin":
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=False)
    elif shutil.which("wl-copy"):
        subprocess.run(["wl-copy"], input=text.encode("utf-8"), check=False)
    elif shutil.which("xclip"):
        subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode("utf-8"), check=False)


def send_to_rex(session_id: str, block_id: str, text: str) -> None:
    """Send text directly into the Rex terminal block."""
    cmd = ["rex", "send", "-s", session_id, "-b", block_id, "--", text]
    subprocess.run(cmd, check=False)


def open_item(item: str) -> None:
    """Open URL or path with system opener."""
    if sys.platform == "darwin":
        subprocess.run(["open", item], check=False)
    elif shutil.which("xdg-open"):
        subprocess.run(["xdg-open", item], check=False)


def edit_item(item: str) -> None:
    """Open path in editor or custom open hook."""
    open_hook = Path.home() / ".config" / "mbianco" / "open-file-path.sh"
    if open_hook.is_file() and os.access(open_hook, os.X_OK):
        subprocess.run([str(open_hook), item], check=False)
        return

    editor = os.environ.get("EDITOR", "vi")
    if sys.platform == "darwin" and (editor == "vi" or not shutil.which(editor)):
        # Fall back to open
        subprocess.run(["open", item], check=False)
    else:
        subprocess.run([editor, item], check=False)


def find_fzf() -> Optional[str]:
    """Find fzf executable in PATH."""
    return shutil.which("fzf")


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str):
        super().__init__("localhost")
        self.path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.path)


def send_fzf_action(sock_path: str, action: str) -> bool:
    """Send an action payload to fzf over its local Unix domain socket."""
    try:
        conn = UnixHTTPConnection(sock_path)
        conn.request("POST", "/", body=action.encode("utf-8"))
        resp = conn.getresponse()
        conn.close()
        return resp.status == 200
    except Exception:
        return False


def write_filter_items(temp_dir: Path, engine: ExtraktoEngine, captured: str, filter_names: List[str]) -> None:
    """Pre-extract and cache items for all filters into disk files."""
    for name in filter_names:
        items = engine.extract(captured, name)
        if not items:
            items = ["(no matches found)"]
        item_file = temp_dir / f"items_{name}.txt"
        with open(item_file, "w", encoding="utf-8") as f:
            f.write("\n".join(items) + "\n")


def build_header(cur_filter: str, cur_grab: str) -> str:
    return (
        f"enter:copy | tab:insert | →/ctrl-f:filter [{cur_filter}] | "
        f"ctrl-g:grab [{cur_grab}] | ctrl-o:open | ctrl-e:edit | esc:cancel"
    )


def handle_cycle_filter(state_dir: Path, step: int) -> None:
    """Cycle the active filter and update running fzf instance in-place."""
    state_file = state_dir / "state.json"
    if not state_file.is_file():
        return
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        return

    filter_names = state["filter_names"]
    cur_idx = (state["cur_filter_idx"] + step) % len(filter_names)
    state["cur_filter_idx"] = cur_idx
    cur_filter = filter_names[cur_idx]
    cur_grab = state["grab_areas"][state["cur_grab_idx"]]

    try:
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        pass

    item_file = state_dir / f"items_{cur_filter}.txt"
    header = build_header(cur_filter, cur_grab)
    action = (
        f"reload-sync(cat '{item_file}')+"
        f"change-prompt(extrakto [{cur_filter}] > )+"
        f"change-header({header})"
    )
    send_fzf_action(state["sock_path"], action)


def handle_cycle_grab(state_dir: Path, step: int) -> None:
    """Cycle the grab area, re-extract items from Rex, and update fzf in-place."""
    state_file = state_dir / "state.json"
    if not state_file.is_file():
        return
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        return

    grab_areas = state["grab_areas"]
    cur_grab_idx = (state["cur_grab_idx"] + step) % len(grab_areas)
    state["cur_grab_idx"] = cur_grab_idx
    cur_grab = grab_areas[cur_grab_idx]
    cur_filter = state["filter_names"][state["cur_filter_idx"]]

    # Re-capture from Rex
    captured = capture_rex(state["session_id"], state["block_id"], cur_grab)
    engine = ExtraktoEngine(min_length=state.get("min_length", 5))
    write_filter_items(state_dir, engine, captured, state["filter_names"])

    try:
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception:
        pass

    item_file = state_dir / f"items_{cur_filter}.txt"
    header = build_header(cur_filter, cur_grab)
    action = (
        f"reload-sync(cat '{item_file}')+"
        f"change-header({header})"
    )
    send_fzf_action(state["sock_path"], action)


def run_fzf_loop(
    engine: ExtraktoEngine,
    session_id: str,
    block_id: str,
    initial_filter: str = "all",
    initial_grab: str = "recent",
    bg_color: str = "#282c34",
    bg_highlight: str = "#3e4452",
    min_length: int = 5,
) -> None:
    """Interactive selector using a single persistent fzf instance with in-place reloading."""
    fzf_bin = find_fzf()
    if not fzf_bin:
        print(
            f"rex-extrakto error: fzf executable not found on PATH ({os.environ.get('PATH', '')}).",
            file=sys.stderr,
        )
        return

    filter_names = [f for f in DEFAULT_FILTERS if f in engine.filters or f in ("all", "line")]
    if initial_filter not in filter_names:
        filter_names.insert(0, initial_filter)

    cur_filter_idx = filter_names.index(initial_filter) if initial_filter in filter_names else 0
    cur_grab_idx = GRAB_AREAS.index(initial_grab) if initial_grab in GRAB_AREAS else 0

    temp_dir_str = tempfile.mkdtemp(prefix="rex-extrakto-")
    temp_dir = Path(temp_dir_str)
    sock_path = str(temp_dir / "fzf.sock")
    state_file = temp_dir / "state.json"

    # Pre-extract items for initial grab area
    cur_grab = GRAB_AREAS[cur_grab_idx]
    captured = capture_rex(session_id, block_id, cur_grab)
    write_filter_items(temp_dir, engine, captured, filter_names)

    state = {
        "session_id": session_id,
        "block_id": block_id,
        "filter_names": filter_names,
        "cur_filter_idx": cur_filter_idx,
        "grab_areas": GRAB_AREAS,
        "cur_grab_idx": cur_grab_idx,
        "temp_dir": temp_dir_str,
        "sock_path": sock_path,
        "min_length": min_length,
        "bg_color": bg_color,
        "bg_highlight": bg_highlight,
    }
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f)

    cur_filter = filter_names[cur_filter_idx]
    header = build_header(cur_filter, cur_grab)

    script_path = str(Path(__file__).resolve())
    py_exec = sys.executable

    next_filter_cmd = f'{py_exec} "{script_path}" --state-dir "{temp_dir_str}" --cycle-filter 1'
    prev_filter_cmd = f'{py_exec} "{script_path}" --state-dir "{temp_dir_str}" --cycle-filter -1'
    cycle_grab_cmd = f'{py_exec} "{script_path}" --state-dir "{temp_dir_str}" --cycle-grab 1'

    fzf_cmd = [
        fzf_bin,
        f"--listen={sock_path}",
        "--multi",
        "--print-query",
        f"--header={header}",
        f"--prompt=extrakto [{cur_filter}] > ",
        "--reverse",
        "--height=100%",
        "--border=rounded",
        f"--color=bg:{bg_color},bg+:{bg_highlight},gutter:{bg_color},border:#4b5263",
        f"--bind=right:execute-silent({next_filter_cmd})",
        f"--bind=ctrl-f:execute-silent({next_filter_cmd})",
        f"--bind=left:execute-silent({prev_filter_cmd})",
        f"--bind=ctrl-g:execute-silent({cycle_grab_cmd})",
        "--expect=enter,tab,ctrl-o,ctrl-e,ctrl-c,esc",
    ]

    initial_item_file = temp_dir / f"items_{cur_filter}.txt"
    initial_items = ""
    if initial_item_file.is_file():
        with open(initial_item_file, "r", encoding="utf-8") as f:
            initial_items = f.read()

    proc = subprocess.Popen(
        fzf_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )

    stdout, _ = proc.communicate(input=initial_items)
    lines = stdout.splitlines()

    query = lines[0] if len(lines) > 0 else ""
    key = lines[1] if len(lines) > 1 else ""
    selections = [line for line in lines[2:] if line and line != "(no matches found)"]

    if not selections and query.strip() and key not in ("ctrl-c", "esc"):
        selections = [query.strip()]

    joined_text = "\n".join(selections)

    if key == "enter" and joined_text:
        copy_to_clipboard(joined_text)
    elif key == "tab" and joined_text:
        insert_text = " ".join(selections)
        send_to_rex(session_id, block_id, insert_text)
    elif key == "ctrl-o" and selections:
        for item in selections:
            open_item(item)
    elif key == "ctrl-e" and selections:
        for item in selections:
            edit_item(item)

    # Cleanup temp directory
    shutil.rmtree(temp_dir_str, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extrakto for Rex")
    parser.add_argument("--session", default=os.environ.get("REX_SESSION", ""), help="Target Rex session ID")
    parser.add_argument("--block", default=os.environ.get("REX_BLOCK", ""), help="Target Rex block ID")
    parser.add_argument("--filter", default="all", help="Initial filter (all, path, url, word, line, quote)")
    parser.add_argument("--grab", default="recent", choices=["recent", "full", "window"], help="Capture area")
    parser.add_argument("--min-length", type=int, default=5, help="Minimum word length")
    parser.add_argument("--bg-color", default="#282c34", help="Solid background color")
    parser.add_argument("--bg-highlight", default="#3e4452", help="Solid background highlight for selected row")

    # Fast IPC actions for dynamic in-place fzf updates
    parser.add_argument("--state-dir", default="", help="Internal IPC state directory for fzf socket communication")
    parser.add_argument("--cycle-filter", type=int, default=0, help="Cycle filter by step (+1 or -1) without reload")
    parser.add_argument("--cycle-grab", type=int, default=0, help="Cycle grab area by step (+1) without reload")

    args = parser.parse_args()

    # Fast-path handlers for keybindings inside running fzf
    if args.state_dir:
        state_dir = Path(args.state_dir)
        if args.cycle_filter != 0:
            handle_cycle_filter(state_dir, args.cycle_filter)
            return
        if args.cycle_grab != 0:
            handle_cycle_grab(state_dir, args.cycle_grab)
            return

    engine = ExtraktoEngine(min_length=args.min_length)
    run_fzf_loop(
        engine=engine,
        session_id=args.session,
        block_id=args.block,
        initial_filter=args.filter,
        initial_grab=args.grab,
        bg_color=args.bg_color,
        bg_highlight=args.bg_highlight,
        min_length=args.min_length,
    )


if __name__ == "__main__":
    main()
