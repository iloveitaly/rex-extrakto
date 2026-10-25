#!/usr/bin/env python3
"""rex-extrakto: Interactive text extractor and fuzzy selector for Rex.

Extracted from and inspired by laktak/extrakto, adapted natively for Rex.
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
    """Find fzf executable in PATH or standard user directories."""
    # Ensure standard user directories are in PATH
    user_dirs = [
        str(Path.home() / ".local/share/mise/shims"),
        str(Path.home() / ".local/bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
    ]
    cur_path = os.environ.get("PATH", "")
    for d in user_dirs:
        if d not in cur_path and os.path.isdir(d):
            cur_path = f"{d}:{cur_path}"
    os.environ["PATH"] = cur_path

    # 1. Standard PATH lookup
    found = shutil.which("fzf")
    if found:
        return found

    # 2. Check explicit known locations
    direct_candidates = [
        Path.home() / ".local/share/mise/shims/fzf",
        Path("/opt/homebrew/bin/fzf"),
        Path("/usr/local/bin/fzf"),
        Path.home() / ".local/bin/fzf",
    ]
    for cand in direct_candidates:
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)

    # 3. Check mise installs directly
    mise_fzf_dir = Path.home() / ".local/share/mise/installs/fzf"
    if mise_fzf_dir.is_dir():
        for match in mise_fzf_dir.glob("*/bin/fzf"):
            if match.is_file() and os.access(match, os.X_OK):
                return str(match)
        for match in mise_fzf_dir.glob("*/fzf"):
            if match.is_file() and os.access(match, os.X_OK):
                return str(match)

    return None


def run_fzf_loop(
    engine: ExtraktoEngine,
    session_id: str,
    block_id: str,
    initial_filter: str = "all",
    initial_grab: str = "recent",
) -> None:
    """Main interactive loop using fzf with dynamic reload and mode switching."""
    fzf_bin = find_fzf()
    if not fzf_bin:
        err_msg = (
            "rex-extrakto error: fzf executable not found on PATH or standard directories.\n"
            "Checked PATH, ~/.local/share/mise/shims, /opt/homebrew/bin, and /usr/local/bin.\n"
        )
        print(err_msg, file=sys.stderr)
        try:
            with open("/tmp/extrakto.err", "a") as f:
                f.write(err_msg)
        except Exception:
            pass
        return

    filter_names = [f for f in DEFAULT_FILTERS if f in engine.filters or f in ("all", "line")]
    if initial_filter not in filter_names:
        filter_names.insert(0, initial_filter)

    cur_filter_idx = filter_names.index(initial_filter) if initial_filter in filter_names else 0
    cur_grab_idx = GRAB_AREAS.index(initial_grab) if initial_grab in GRAB_AREAS else 0

    query = ""

    while True:
        cur_filter = filter_names[cur_filter_idx]
        cur_grab = GRAB_AREAS[cur_grab_idx]

        # 1. Capture text
        captured = capture_rex(session_id, block_id, cur_grab)
        items = engine.extract(captured, cur_filter)

        if not items:
            items = ["(no matches found)"]

        # 2. Build header
        header = (
            f"enter:copy | tab:insert | ctrl-f:filter [{cur_filter}] | "
            f"ctrl-g:grab [{cur_grab}] | ctrl-o:open | ctrl-e:edit | esc:cancel"
        )

        fzf_cmd = [
            fzf_bin,
            "--multi",
            "--print-query",
            f"--query={query}",
            f"--header={header}",
            f"--prompt=extrakto [{cur_filter}] > ",
            "--reverse",
            "--height=100%",
            "--border=rounded",
            "--expect=enter,tab,ctrl-f,ctrl-g,ctrl-o,ctrl-e,ctrl-c,esc",
        ]

        proc = subprocess.Popen(
            fzf_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )

        stdout, _ = proc.communicate(input="\n".join(items))
        lines = stdout.splitlines()

        if len(lines) < 2:
            break

        query = lines[0]
        key = lines[1]
        selections = [line for line in lines[2:] if line and line != "(no matches found)"]

        if key in ("ctrl-c", "esc") or not key and not selections:
            break

        if key == "ctrl-f":
            cur_filter_idx = (cur_filter_idx + 1) % len(filter_names)
            continue

        if key == "ctrl-g":
            cur_grab_idx = (cur_grab_idx + 1) % len(GRAB_AREAS)
            continue

        if not selections:
            # If user pressed action key without selecting from list, use current query
            if query.strip():
                selections = [query.strip()]
            else:
                break

        joined_text = "\n".join(selections)

        if key == "enter":
            copy_to_clipboard(joined_text)
            break
        elif key == "tab":
            # Space-joined text when inserting into terminal prompt
            insert_text = " ".join(selections)
            send_to_rex(session_id, block_id, insert_text)
            break
        elif key == "ctrl-o":
            for item in selections:
                open_item(item)
            break
        elif key == "ctrl-e":
            for item in selections:
                edit_item(item)
            break
        else:
            break


def main() -> None:
    parser = argparse.ArgumentParser(description="Extrakto for Rex")
    parser.add_argument("--session", default=os.environ.get("REX_SESSION", ""), help="Target Rex session ID")
    parser.add_argument("--block", default=os.environ.get("REX_BLOCK", ""), help="Target Rex block ID")
    parser.add_argument("--filter", default="all", help="Initial filter (all, path, url, word, line, quote)")
    parser.add_argument("--grab", default="recent", choices=["recent", "full", "window"], help="Capture area")
    parser.add_argument("--min-length", type=int, default=5, help="Minimum word length")

    args = parser.parse_args()

    engine = ExtraktoEngine(min_length=args.min_length)
    run_fzf_loop(
        engine=engine,
        session_id=args.session,
        block_id=args.block,
        initial_filter=args.filter,
        initial_grab=args.grab,
    )


if __name__ == "__main__":
    main()
