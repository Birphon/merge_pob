"""
merge_pob.py - core logic for PoB Build Merger.

Nothing in this module touches the GUI. It can be imported and used on its own:

    from merge_pob import BuildSource, merge_sources

    result = merge_sources([
        BuildSource("Leveling", "https://pobb.in/c6sAAu_TF8-F"),
        BuildSource("Endgame",  "https://pobb.in/Ls6mWqaM05mF"),
    ])
    print(result.code)

Each input build becomes its own Tree spec, Skill set, Item set and Config set
(named after the build), so they can be switched between using PoB's dropdowns.
"""
from __future__ import annotations

import base64
import copy
import re
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass
from typing import Callable, Iterable, Optional
from urllib.parse import urlparse

USER_AGENT = "pob-merge/1.2 (personal build merging tool)"
REQUEST_TIMEOUT = 30

# (current_index, total, build_name) - called just before each build is loaded
ProgressCallback = Callable[[int, int, str], None]


class MergeError(Exception):
    """Raised for any user-facing failure while loading or merging builds."""


@dataclass(frozen=True)
class BuildSource:
    name: str
    source: str  # share link or raw PoB code


@dataclass(frozen=True)
class MergeResult:
    code: str
    build_count: int


# ======================= decode / encode =======================

def decode_code(code: str) -> ET.Element:
    """PoB code (URL-safe base64 of zlib-compressed XML) -> XML root."""
    code = code.strip()
    if code.startswith("<"):
        return ET.fromstring(code)
    code = code.replace("-", "+").replace("_", "/")
    code += "=" * (-len(code) % 4)
    xml = zlib.decompress(base64.b64decode(code))
    return ET.fromstring(xml)


def encode_root(root: ET.Element) -> str:
    """XML root -> PoB code."""
    xml = ET.tostring(root, encoding="unicode").encode("utf-8")
    return base64.urlsafe_b64encode(zlib.compress(xml, 9)).decode()


def extract_build(text: str) -> Optional[ET.Element]:
    """Find a PoB build inside arbitrary text (raw code, JSON, HTML). None if not found."""
    text = text.replace("\\/", "/")
    candidates = [text.strip()] + re.findall(r"[A-Za-z0-9_\-+/=]{100,}", text)
    for candidate in candidates:
        try:
            root = decode_code(candidate)
            if root.tag == "PathOfBuilding":
                return root
        except Exception:
            continue
    return None


# ======================= fetching =======================

def candidate_urls(source: str) -> list[str]:
    """Raw-code URLs to try for a share link, most likely first."""
    parsed = urlparse(source)
    host = parsed.netloc.lower().removeprefix("www.")
    parts = [p for p in parsed.path.split("/") if p]
    last = parts[-1] if parts else ""
    urls: list[str] = []
    if host == "pobb.in" and parts:
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
    urls.append(source)  # last resort: scrape the page itself
    return urls


def http_get(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return response.read().decode("utf-8", errors="replace")


def resolve(source: str) -> ET.Element:
    """Load one build from a share link or a raw PoB code."""
    source = source.strip()
    if not source.lower().startswith("http"):
        root = extract_build(source)
        if root is None:
            raise MergeError("not a valid PoB code")
        return root

    errors: list[str] = []
    for url in candidate_urls(source):
        try:
            root = extract_build(http_get(url))
            if root is not None:
                return root
            errors.append(f"{url}: no PoB code in response")
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    raise MergeError("could not fetch a build from this link\n  " + "\n  ".join(errors))


# ======================= merging =======================

def _section(root: ET.Element, tag: str) -> ET.Element:
    element = root.find(tag)
    if element is None:
        element = ET.SubElement(root, tag)
    return element


def merge_roots(builds: list[tuple[str, ET.Element]]) -> ET.Element:
    """Merge (title, xml_root) pairs. The first build supplies class/level/etc."""
    out = copy.deepcopy(builds[0][1])
    trees, skills = _section(out, "Tree"), _section(out, "Skills")
    items, config = _section(out, "Items"), _section(out, "Config")
    notes = _section(out, "Notes")
    for element in (trees, skills, items, config):
        for child in list(element):
            element.remove(child)

    skill_id = item_set_id = config_id = item_id = 0
    notes_text: list[str] = []

    for title, root in builds:
        id_map: dict[str, str] = {}  # old item id -> new item id (for this build)

        # Items first: their new ids are needed by item sets AND tree jewel sockets.
        src = root.find("Items")
        if src is not None:
            for item in src.findall("Item"):
                item_id += 1
                id_map[item.get("id")] = str(item_id)
                new = copy.deepcopy(item)
                new.set("id", str(item_id))
                items.append(new)

            item_sets = src.findall("ItemSet")
            if not item_sets:  # old format: Slot directly under Items
                wrapper = ET.Element("ItemSet")
                for slot in src.findall("Slot"):
                    wrapper.append(copy.deepcopy(slot))
                item_sets = [wrapper]
            for item_set in item_sets:
                item_set_id += 1
                new = copy.deepcopy(item_set)
                new.set("id", str(item_set_id))
                new.set("title", title)
                for slot in new.iter("Slot"):
                    if slot.get("itemId") in id_map:
                        slot.set("itemId", id_map[slot.get("itemId")])
                items.append(new)

        # Tree specs (jewel sockets point at item ids, so remap those too).
        specs = root.findall("./Tree/Spec")
        for spec in specs:
            new = copy.deepcopy(spec)
            for socket in new.iter("Socket"):
                if socket.get("itemId") in id_map:
                    socket.set("itemId", id_map[socket.get("itemId")])
            old_title = spec.get("title")
            multiple = len(specs) > 1 and old_title and old_title != "Default"
            new.set("title", f"{title} - {old_title}" if multiple else title)
            trees.append(new)

        # Skill sets.
        src = root.find("Skills")
        skill_sets = src.findall("SkillSet") if src is not None else []
        if not skill_sets and src is not None:  # old format: Skill directly under Skills
            wrapper = ET.Element("SkillSet")
            for skill in src.findall("Skill"):
                wrapper.append(copy.deepcopy(skill))
            skill_sets = [wrapper]
        for skill_set in skill_sets:
            skill_id += 1
            new = copy.deepcopy(skill_set)
            new.set("id", str(skill_id))
            new.set("title", title)
            skills.append(new)

        # Config sets.
        src = root.find("Config")
        config_sets = src.findall("ConfigSet") if src is not None else []
        if not config_sets and src is not None:
            wrapper = ET.Element("ConfigSet")
            for child in src:
                wrapper.append(copy.deepcopy(child))
            config_sets = [wrapper]
        for config_set in config_sets:
            config_id += 1
            new = copy.deepcopy(config_set)
            new.set("id", str(config_id))
            new.set("title", title)
            config.append(new)

        note = root.findtext("Notes")
        if note and note.strip():
            notes_text.append(f"===== {title} =====\n{note.strip()}")

    trees.set("activeSpec", "1")
    skills.set("activeSkillSet", "1")
    items.set("activeItemSet", "1")
    config.set("activeConfigSet", "1")
    if notes_text:
        notes.text = "\n\n".join(notes_text)
    return out


# ======================= public API =======================

def prepare_sources(rows: Iterable[tuple[str, str]]) -> list[BuildSource]:
    """(name, source) pairs from a UI -> clean BuildSources.

    Rows with an empty source are dropped; empty names become "Build N".
    """
    sources: list[BuildSource] = []
    for name, source in rows:
        source = (source or "").strip()
        if not source:
            continue
        name = (name or "").strip() or f"Build {len(sources) + 1}"
        sources.append(BuildSource(name, source))
    return sources


def merge_sources(sources: Iterable[BuildSource],
                  on_progress: Optional[ProgressCallback] = None) -> MergeResult:
    """Load every build, merge them, and return the combined PoB code.

    Blocking (network access). Raises MergeError with a readable message.
    """
    sources = list(sources)
    if not sources:
        raise MergeError("No builds to merge.")

    builds: list[tuple[str, ET.Element]] = []
    for index, build in enumerate(sources, 1):
        if on_progress:
            on_progress(index, len(sources), build.name)
        try:
            builds.append((build.name, resolve(build.source)))
        except Exception as exc:
            raise MergeError(f'"{build.name}": {exc}') from exc

    return MergeResult(encode_root(merge_roots(builds)), len(builds))