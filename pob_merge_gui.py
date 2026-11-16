#!/usr/bin/env python3
"""
PoB Build Merger (Tkinter GUI)

Each row: [link or PoB code] [name]. Press "Merge" and you get ONE PoB code in
which every row is its own Tree spec / Skill set / Item set / Config set.

Supported sources: pobb.in, pastebin, poedb.tw, poe.ninja, pob.codes,
maxroll.gg/poe/pob/..., or a raw PoB code pasted directly.

Needs only Python 3 (tkinter ships with the standard installer).
"""
import base64
import copy
import queue
import re
import threading
import tkinter as tk
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from tkinter import ttk
from tkinter import font as tkfont
from urllib.parse import urlparse

UA = "pob-merge-gui/1.2 (personal build merging tool)"


# ======================= decode / encode =======================

def decode_code(code: str) -> ET.Element:
    code = code.strip()
    if code.startswith("<"):
        return ET.fromstring(code)
    code = code.replace("-", "+").replace("_", "/")
    code += "=" * (-len(code) % 4)
    xml = zlib.decompress(base64.b64decode(code))
    return ET.fromstring(xml)


def encode_root(root: ET.Element) -> str:
    xml = ET.tostring(root, encoding="unicode").encode("utf-8")
    return base64.urlsafe_b64encode(zlib.compress(xml, 9)).decode()


def extract_build(text: str):
    """Find a PoB build inside arbitrary text (raw code, JSON, HTML). None if not found."""
    text = text.replace("\\/", "/")
    candidates = [text.strip()] + re.findall(r"[A-Za-z0-9_\-+/=]{100,}", text)
    for c in candidates:
        try:
            root = decode_code(c)
            if root.tag == "PathOfBuilding":
                return root
        except Exception:
            continue
    return None


# ======================= fetching =======================

def candidate_urls(src: str):
    p = urlparse(src)
    host = p.netloc.lower().removeprefix("www.")
    parts = [x for x in p.path.split("/") if x]
    last = parts[-1] if parts else ""
    urls = []
    if host == "pobb.in":
        urls.append(f"https://pobb.in/{parts[0]}/raw")
    elif host == "pastebin.com":
        urls.append(f"https://pastebin.com/raw/{last}")
    elif host == "poedb.tw":
        urls.append(f"https://poedb.tw/pob/{last}/raw")
    elif host == "poe.ninja":
        urls += [f"https://poe.ninja/poe1/pob/raw/{last}",
                 f"https://poe.ninja/pob/raw/{last}"]
    elif host == "pob.codes":
        urls += [f"https://pob.codes/raw/{last}",
                 f"https://pob.codes/api/{last}"]
    elif host == "maxroll.gg":
        urls += [f"https://maxroll.gg/poe/api/pob/{last}",
                 f"https://maxroll.gg/poe/pob/{last}"]
    urls.append(src)  # last resort: scrape the page itself
    return urls


def http_get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def resolve(source: str) -> ET.Element:
    source = source.strip()
    if not source.lower().startswith("http"):
        root = extract_build(source)
        if root is None:
            raise ValueError("not a valid PoB code")
        return root
    errors = []
    for url in candidate_urls(source):
        try:
            root = extract_build(http_get(url))
            if root is not None:
                return root
            errors.append(f"{url}: no PoB code in response")
        except Exception as e:
            errors.append(f"{url}: {e}")
    raise ValueError("could not fetch a build from this link\n  " + "\n  ".join(errors))


# ======================= merging =======================

def section(root, tag):
    el = root.find(tag)
    if el is None:
        el = ET.SubElement(root, tag)
    return el


def merge(builds):
    """builds: list of (title, root). First build supplies class/level/etc."""
    out = copy.deepcopy(builds[0][1])
    trees, skills = section(out, "Tree"), section(out, "Skills")
    items, config = section(out, "Items"), section(out, "Config")
    notes = section(out, "Notes")
    for el in (trees, skills, items, config):
        for child in list(el):
            el.remove(child)

    skill_id = item_set_id = config_id = item_id = 0
    notes_text = []

    for title, root in builds:
        id_map = {}  # old item id -> new item id (for this build)

        # items first: their new ids are needed by item sets AND tree jewel sockets
        src = root.find("Items")
        if src is not None:
            for it in src.findall("Item"):
                item_id += 1
                id_map[it.get("id")] = str(item_id)
                n = copy.deepcopy(it)
                n.set("id", str(item_id))
                items.append(n)
            isets = src.findall("ItemSet")
            if not isets:  # old format: Slot directly under Items
                w = ET.Element("ItemSet")
                for sl in src.findall("Slot"):
                    w.append(copy.deepcopy(sl))
                isets = [w]
            for iset in isets:
                item_set_id += 1
                n = copy.deepcopy(iset)
                n.set("id", str(item_set_id))
                n.set("title", title)
                for slot in n.iter("Slot"):
                    if slot.get("itemId") in id_map:
                        slot.set("itemId", id_map[slot.get("itemId")])
                items.append(n)

        # tree specs (jewel sockets point at item ids, so remap those too)
        specs = root.findall("./Tree/Spec")
        for spec in specs:
            s = copy.deepcopy(spec)
            for sock in s.iter("Socket"):
                if sock.get("itemId") in id_map:
                    sock.set("itemId", id_map[sock.get("itemId")])
            old = spec.get("title")
            s.set("title", f"{title} - {old}" if len(specs) > 1 and old and old != "Default" else title)
            trees.append(s)

        # skill sets
        src = root.find("Skills")
        sets = src.findall("SkillSet") if src is not None else []
        if not sets and src is not None:  # old format: Skill directly under Skills
            w = ET.Element("SkillSet")
            for sk in src.findall("Skill"):
                w.append(copy.deepcopy(sk))
            sets = [w]
        for ss in sets:
            skill_id += 1
            n = copy.deepcopy(ss)
            n.set("id", str(skill_id))
            n.set("title", title)
            skills.append(n)

        # config sets
        src = root.find("Config")
        csets = src.findall("ConfigSet") if src is not None else []
        if not csets and src is not None:
            w = ET.Element("ConfigSet")
            for child in src:
                w.append(copy.deepcopy(child))
            csets = [w]
        for cs in csets:
            config_id += 1
            n = copy.deepcopy(cs)
            n.set("id", str(config_id))
            n.set("title", title)
            config.append(n)

        nt = root.findtext("Notes")
        if nt and nt.strip():
            notes_text.append(f"===== {title} =====\n{nt.strip()}")

    trees.set("activeSpec", "1")
    skills.set("activeSkillSet", "1")
    items.set("activeItemSet", "1")
    config.set("activeConfigSet", "1")
    if notes_text:
        notes.text = "\n\n".join(notes_text)
    return out


# ======================= GUI =======================

HINT_FG = "#9a9a9a"
STATUS_COLORS = {"info": "#555555", "ok": "#1a7f37", "err": "#c62828"}


class HintEntry(ttk.Entry):
    """Entry with grey placeholder text."""

    def __init__(self, master, hint, **kw):
        self.var = tk.StringVar()
        super().__init__(master, textvariable=self.var, **kw)
        self.hint = hint
        self.showing = False
        self.normal_fg = ttk.Style().lookup("TEntry", "foreground") or "black"
        self.bind("<FocusIn>", self._focus_in)
        self.bind("<FocusOut>", self._focus_out)
        self._focus_out()

    def _focus_in(self, _=None):
        if self.showing:
            self.showing = False
            self.var.set("")
            self.configure(foreground=self.normal_fg)

    def _focus_out(self, _=None):
        if not self.showing and not self.var.get():
            self.showing = True
            self.var.set(self.hint)
            self.configure(foreground=HINT_FG)

    def value(self):
        return "" if self.showing else self.var.get().strip()

    def reset(self):
        self.showing = False
        self.var.set("")
        self.configure(foreground=self.normal_fg)
        if self.focus_get() is not self:
            self._focus_out()


class App:
    def __init__(self, win: tk.Tk):
        self.win = win
        win.title("PoB Build Merger")
        win.geometry("860x540")
        win.minsize(680, 440)
        self.q = queue.Queue()
        self.rows = []  # dicts: num, src, name, btn

        base = tkfont.nametofont("TkDefaultFont")
        bold = base.copy()
        bold.configure(weight="bold")
        small = base.copy()
        small.configure(size=max(base.cget("size") - 1, 8))
        mono = tkfont.nametofont("TkFixedFont").copy()
        mono.configure(size=9)

        style = ttk.Style()
        style.configure("Merge.TButton", font=bold, padding=(18, 5))
        style.configure("Remove.TButton", padding=(2, 1))

        outer = ttk.Frame(win, padding=(16, 14))
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Combine builds into one PoB code", font=bold).pack(anchor="w")
        ttk.Label(outer, foreground=HINT_FG, font=small,
                  text="pobb.in · pastebin · poedb.tw · poe.ninja · pob.codes · maxroll · or a raw PoB code"
                  ).pack(anchor="w", pady=(0, 10))

        # ---- rows (single grid so columns line up exactly) ----
        self.grid_frame = ttk.Frame(outer)
        self.grid_frame.pack(fill="x")
        self.grid_frame.columnconfigure(1, weight=1)
        ttk.Label(self.grid_frame, text="Link or code", font=small, foreground="#666").grid(
            row=0, column=1, sticky="w", padx=(0, 8))
        ttk.Label(self.grid_frame, text="Name", font=small, foreground="#666").grid(
            row=0, column=2, sticky="w")
        for _ in range(5):
            self.add_row(render=False)
        self.render_rows()

        # ---- action bar ----
        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=(10, 0))
        ttk.Button(bar, text="+ Add row", command=self.add_row).pack(side="left")
        ttk.Button(bar, text="Clear", command=self.clear).pack(side="left", padx=6)
        self.merge_btn = ttk.Button(bar, text="Merge", style="Merge.TButton", command=self.start_merge)
        self.merge_btn.pack(side="right")
        ttk.Label(bar, text="Row 1 sets class & level", font=small, foreground=HINT_FG).pack(
            side="right", padx=14)

        ttk.Separator(outer).pack(fill="x", pady=12)

        # ---- output ----
        out_head = ttk.Frame(outer)
        out_head.pack(fill="x")
        ttk.Label(out_head, text="Merged code", font=bold).pack(side="left")
        self.copy_btn = ttk.Button(out_head, text="Copy", command=self.copy_out)
        self.copy_btn.pack(side="right")

        out_frame = ttk.Frame(outer)
        out_frame.pack(fill="both", expand=True, pady=(4, 6))
        self.output = tk.Text(out_frame, height=5, wrap="char", font=mono, relief="solid",
                              borderwidth=1, highlightthickness=0, padx=6, pady=4)
        sb = ttk.Scrollbar(out_frame, command=self.output.yview)
        self.output.configure(yscrollcommand=sb.set)
        self.output.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        status_bar = ttk.Frame(outer)
        status_bar.pack(fill="x")
        self.status = ttk.Label(status_bar, text="Ready.", foreground=STATUS_COLORS["info"])
        self.status.pack(side="left")
        self.progress = ttk.Progressbar(status_bar, mode="indeterminate", length=110)

        self.win.after(100, self.poll)

    # ---- rows ----
    def add_row(self, render=True):
        g = self.grid_frame
        row = {
            "num": ttk.Label(g, width=2, foreground=HINT_FG, anchor="e"),
            "src": HintEntry(g, "Paste a link or PoB code"),
            "name": HintEntry(g, "Name (e.g. Leveling)", width=26),
        }
        row["btn"] = ttk.Button(g, text="✕", width=3, style="Remove.TButton",
                                command=lambda r=row: self.remove_row(r))
        self.rows.append(row)
        if render:
            self.render_rows()

    def render_rows(self):
        for i, r in enumerate(self.rows, 1):
            r["num"].configure(text=str(i))
            r["num"].grid(row=i, column=0, padx=(0, 6), pady=2)
            r["src"].grid(row=i, column=1, sticky="ew", padx=(0, 8), pady=2, ipady=2)
            r["name"].grid(row=i, column=2, padx=(0, 8), pady=2, ipady=2)
            r["btn"].grid(row=i, column=3, pady=2)

    def remove_row(self, row):
        if len(self.rows) <= 1:
            row["src"].reset()
            row["name"].reset()
            return
        self.rows.remove(row)
        for w in ("num", "src", "name", "btn"):
            row[w].destroy()
        self.render_rows()

    def clear(self):
        for r in self.rows:
            r["src"].reset()
            r["name"].reset()
        self.output.delete("1.0", "end")
        self.set_status("Ready.")

    def set_status(self, text, kind="info"):
        self.status.configure(text=text, foreground=STATUS_COLORS[kind])

    # ---- merge ----
    def start_merge(self):
        entries = []
        for r in self.rows:
            src = r["src"].value()
            if src:
                entries.append((r["name"].value() or f"Build {len(entries) + 1}", src))
        if not entries:
            self.set_status("Add at least one link or code.", "err")
            return
        self.merge_btn.state(["disabled"])
        self.output.delete("1.0", "end")
        self.progress.pack(side="right")
        self.progress.start(12)
        threading.Thread(target=self.worker, args=(entries,), daemon=True).start()

    def worker(self, entries):
        try:
            builds = []
            for i, (name, src) in enumerate(entries, 1):
                self.q.put(("status", f"Loading {i}/{len(entries)}: {name}…"))
                try:
                    builds.append((name, resolve(src)))
                except Exception as e:
                    raise ValueError(f'"{name}": {e}')
            self.q.put(("done", encode_root(merge(builds)), len(builds)))
        except Exception as e:
            self.q.put(("error", str(e)))

    def finish_run(self):
        self.progress.stop()
        self.progress.pack_forget()
        self.merge_btn.state(["!disabled"])

    def poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                if msg[0] == "status":
                    self.set_status(msg[1])
                elif msg[0] == "done":
                    self.output.insert("1.0", msg[1])
                    self.copy_out(quiet=True)
                    self.set_status(f"Merged {msg[2]} builds. Code copied to clipboard.", "ok")
                    self.finish_run()
                elif msg[0] == "error":
                    self.set_status("Error: " + msg[1].splitlines()[0], "err")
                    self.output.insert("1.0", "ERROR\n" + msg[1])
                    self.finish_run()
        except queue.Empty:
            pass
        self.win.after(100, self.poll)

    def copy_out(self, quiet=False):
        text = self.output.get("1.0", "end").strip()
        if text and not text.startswith("ERROR"):
            self.win.clipboard_clear()
            self.win.clipboard_append(text)
            if not quiet:
                self.set_status("Copied to clipboard.", "ok")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()