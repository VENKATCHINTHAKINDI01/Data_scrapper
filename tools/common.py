"""Shared helpers for the C2-24 data tools: scope, canonical IDs, references, metadata, provenance."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
STAGING = ROOT / "staging"
MANIFESTS = STAGING / "manifests"

# Hierarchy levels (IMPLEMENTATION_PLAN §6 / CLAUDE.md): lower number = higher authority
LEVEL = {"CONST": 1, "ACT": 2, "RULE": 3, "NOTIF": 3, "GOMS": 4, "GOP": 4, "GORT": 5, "SO": 6,
         "CIRMEMO": 7, "MEMO": 7, "CIR": 7, "RC": 7, "OO": 8, "NOTE": 9, "RPT": 9, "ANX": 9}

# Relationship vocabulary — must match CLAUDE.md §5.7
RELATIONS = {"SUPERSEDES", "SUPERSEDED_BY", "AMENDS", "CLARIFIES", "REPEALS", "REFERENCES"}

# Canonical ID: AP-<DEPT>-<TYPE>-[<FILECODE>-]<NUMBER>-<YEAR>[-<SUFFIX>]
CANONICAL_RE = re.compile(r"^AP-[A-Z0-9]+-[A-Z]+(?:-[A-Z0-9]+)?-\d+-\d{4}(?:-[A-Z0-9]+){0,2}$")

META_REQUIRED = ["canonical_id", "doc_type", "instrument", "number", "date", "department_code",
                 "subject", "hierarchy_level", "classification", "origin", "source_name",
                 "source_url", "verification_status", "sha256", "files", "collected_at"]


def load_scope() -> dict:
    import yaml  # pyyaml
    return yaml.safe_load((ROOT / "scope.yaml").read_text())


# A department code such as FIN01 / Fin01 / ENE01, followed by "-", a line break or the end.
# Seen in real records: "FIN01\n- FINANCE" (description), "Fin01\n- Finance" (title), "ENE01-E- ENERGY".
DEPT_CODE_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{2,6}\d{2})(?=\s*(?:-|$))", re.M)


def dept_code(text: str | None) -> str | None:
    """Explicit department code in a label/title, upper-cased. Never infers from words."""
    m = DEPT_CODE_RE.search(text or "")
    return m.group(1).upper() if m else None


def dept_code_for(text: str, scope: dict | None, aliases: bool = True) -> str | None:
    """Explicit code first; otherwise (only if aliases=True) a whole-word department name from scope.
    Use aliases only on a department field or an order's own heading - never on titles/abstracts,
    where another department's name can appear ("... with concurrence of Finance ...")."""
    if not text:
        return None
    code = dept_code(text)
    if code:
        return code
    if scope and aliases:
        t = text.lower()
        for code, d in scope.get("departments", {}).items():
            for a in [d.get("name", "")] + d.get("aliases", []):
                if a and re.search(r"(?<![A-Za-z])" + re.escape(a.lower()) + r"(?![A-Za-z])", t):
                    return code
    return None


def iso_date(raw: str | None) -> str | None:
    """'12-05-2025' / '12.05.2025' / '2025-05-12' -> '2025-05-12'."""
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%d-%m-%Y", "%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%y", "%d.%m.%y"):
        try:
            return dt.datetime.strptime(raw[:10], fmt).date().isoformat()
        except ValueError:
            pass
    return None


def canonical_id(dept: str, typ: str, number: str, year: str, filecode: str | None = None,
                 suffix: str | None = None, date: str | None = None) -> str:
    """Memos/circulars are numbered by e-File number, and one file issues many memos, so their IDs
    carry the issue date as a final D<yyyymmdd> tag: AP-FIN01-CIRMEMO-FIN01COOROMISC-93-2023-D20240305."""
    parts = ["AP", dept.upper(), typ.upper()]
    if filecode:
        parts.append(re.sub(r"[^A-Z0-9]", "", fix_codes(filecode).upper()))
    parts += [str(int(number)), str(year)]
    if suffix:
        parts.append(re.sub(r"[^A-Z0-9]", "", suffix.upper()))
    if date:
        parts.append("D" + date.replace("-", ""))
    return "-".join(parts)


# ---- OCR clean-up (seen in real archive OCR, 14 Oct 2026) --------------------
def fix_codes(text: str) -> str:
    """Department codes with letter O for zero: FINO1 -> FIN01, GADO1 -> GAD01."""
    return re.sub(r"\b([A-Z]{2,5})O(\d)(?=\b|-|/)", r"\g<1>0\2", text)


def normalize_ocr(text: str) -> str:
    t = text.replace("\u2014", "-").replace("\u2013", "-")
    # "G.0.Ms" / "6.0. 3 read above" / "6.0.2” read" -> G.O.
    t = re.sub(r"\b[G6]\s*\.\s*[0O]\s*\.?\s*(?=(?:Ms|MS|Rt|RT|P\b|No|\(|\d))", "G.O.", t)
    t = re.sub(r"(?m)^(\s*(?:\d{1,2}\s*[.)]\s*)?)\.?\s*(Ms|MS|Rt|RT)\s*\.\s*No", r"\1G.O.\2.No", t)   # ".Ms.No.98" (G.O lost)
    t = fix_codes(t)
    t = re.sub(r"\b[Ii]st\b(?=\s*(?:read|cited))", "1st", t)
    words = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
             "eleventh", "twelfth"]
    for i, w in enumerate(words, 1):
        t = re.sub(rf"\b{w}\b(?=\s*(?:&|and|,)?\s*(?:\w+\s*)?(?:read\b|cited\b))", f"{i}th", t, flags=re.I)
    # ordinals mangled by OCR before "read above"/"cited": 1“ 2™ 3" 6"" 5)  -> 1th 2th ...
    t = re.sub(r"(?<![\d./])(\d{1,2})\s*(?:st|nd|rd|th|[\u201c\u201d\"\u2122\u2019'%\u00b0)!*^])*\s*(?=(?:&|and|,)?\s*(?:\d{1,2}\S*\s*)?(?:read\b|cited\b))",
               r"\1th ", t)
    return t


def junk_line(line: str) -> bool:
    """OCR noise such as 'ok ok 2k 2 నం లం', '* KOK', '28 kok', 'KKK'."""
    words = re.findall(r"[A-Za-z]{4,}", line)
    return not words


# ---- reference parsing ------------------------------------------------------
# e.g. "G.O.Ms.No.88, Finance (HR.I-Plg. & Policy) Department, Dt.03-06-2022"
#      "Circular Memo No.GAD01-SERA0/3/2023, General Administration (Ser.A) Department, Dt.14-08-2023"
GO_REF = re.compile(
    r"G\.?\s*O\.?\s*\(?\s*(?P<kind>Ms|MS|Rt|RT|P|p)\s*\)?\.?\s*No\.?\s*(?P<num>\d+)"
    r"(?P<mid>(?:(?!No\.)[^\n]){0,120}?)(?:Dt|Dated|dt|date[d]?)[\s.:;,]*(?P<date>\d{1,2}[-./]\d{1,2}[-./]\d{2,4})",
    re.I)
MEMO_REF = re.compile(
    r"(?P<kind>Circular\s+Memo|Cir\.?\s*Memo|Memo|Rc|Standing\s+Order)\.?\s*No\.?\s*(?P<code>[A-Z0-9()\-\.]+?)/(?P<num>\d+)/(?P<year>\d{4})"
    r"(?:-(?P<suffix>\d+))?(?P<mid>[^\n]{0,120}?)(?:Dt|Dated)[\s.:;,]*(?P<date>\d{1,2}[-./]\d{1,2}[-./]\d{2,4})",
    re.I)
SO_REF = re.compile(r"Standing\s+Order\s+No\.?\s*(?P<num>\d+)/(?P<year>\d{4})", re.I)


def parse_reference(text: str, default_dept: str | None, scope: dict | None) -> dict | None:
    """Return {'raw','canonical_id' or None,'type'} for one reference string. Never guesses a dept."""
    text = normalize_ocr(text)
    m = GO_REF.search(text)
    if m:
        typ = "GOMS" if m.group("kind").lower() == "ms" else ("GORT" if m.group("kind").lower() == "rt" else "GOP")
        date = iso_date(m.group("date"))
        dept = dept_code_for(m.group("mid"), scope) or (default_dept if not m.group("mid").strip(" ,") else None)
        cid = canonical_id(dept, typ, m.group("num"), date[:4]) if (dept and date) else None
        return {"raw": text.strip(), "type": typ, "canonical_id": cid, "date": date}
    m = MEMO_REF.search(text)
    if m:
        kind = m.group("kind").lower()
        typ = "CIRMEMO" if kind.startswith("cir") else ("RC" if kind == "rc" else "MEMO")
        code = m.group("code")
        dept = re.match(r"([A-Z]{2,6}\d{2})", code.upper())
        dept = dept.group(1) if dept else dept_code_for(m.group("mid"), scope)
        date = iso_date(m.group("date"))
        cid = canonical_id(dept, typ, m.group("num"), m.group("year"), filecode=code,
                           suffix=m.group("suffix"), date=date) if (dept and date) else None
        return {"raw": text.strip(), "type": typ, "canonical_id": cid, "date": date}
    m = SO_REF.search(text)
    if m and default_dept:
        return {"raw": text.strip(), "type": "SO",
                "canonical_id": canonical_id(default_dept, "SO", m.group("num"), m.group("year")), "date": None}
    return None


REF_START = re.compile(r"^\s*(?:\d{1,2}\s*[.)]\s*)?[.,]?\s*(?:G\.?\s*O\b|GO\b|G\.O\.|Memo|Cir|Circular|Govt|Lr\b|Letter|From\b|"
                       r"Office\s+Memo|OMF?\b|O\.M\.|F\.?\s*No|MO\s+No|U\.O|Notification|Ref)", re.I)


def read_list(text: str) -> list[str]:
    """Items under 'Read the following:' / 'Read:-' up to 'ORDER' / 'MEMO'. Handles OCR forms seen in real
    orders: '1.G.0.Ms...' (no space), '1) MO No...', 'Ref: 1.G.O...', lost item numbers (each line starts a
    new reference), a single unnumbered item, noise lines. Item order = position (for 'Nth read above')."""
    m = re.search(r"(?m)^\s*\W{0,3}\s*Read\s*(?:the\s+following)?\s*[:\-;]+\s*(.*?)(?:\n\s*(?:ORDERS?|MEMO|O\s*R\s*D\s*E\s*R)\s*:?)",
                  text, re.I | re.S)
    if not m:
        return []
    lines = [l for l in m.group(1).splitlines() if l.strip() and not junk_line(l)]
    lines = [re.sub(r"^\s*Ref\s*:\s*", "", l, flags=re.I) for l in lines]
    items: list[str] = []
    for l in lines:
        if not items or REF_START.match(l):
            items.append(l)
        else:
            items[-1] += " " + l
    out = []
    for i in items:
        i = re.sub(r"^\s*\d{1,2}\s*[.)]\s*", "", i)
        i = re.sub(r"\s+", " ", i).strip(" -*#_|.,")
        if len(re.findall(r"[A-Za-z]{3,}", i)) >= 2:
            out.append(i)
    return out


# ---- files, hashes, provenance ----------------------------------------------
def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def now() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30))).isoformat(timespec="seconds")


def write_json(path: pathlib.Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def append_jsonl(path: pathlib.Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def provenance(root: pathlib.Path, meta: dict, method: str) -> None:
    append_jsonl(root / "manifests" / "provenance.jsonl", {
        "canonical_id": meta["canonical_id"], "source_name": meta["source_name"],
        "source_url": meta["source_url"], "archive_identifier": meta.get("archive_identifier"),
        "sha256": meta["sha256"], "method": method, "origin": meta["origin"],
        "collected_at": meta["collected_at"]})


def doc_folder(root: pathlib.Path, source: str, meta: dict) -> pathlib.Path:
    """rule-library/<source>/<DEPT>/<YEAR>/<canonical-id>/"""
    return root / "rule-library" / source / meta["department_code"] / meta["date"][:4] / meta["canonical_id"]


def file_slug(file_no: str) -> str:
    """e-File numbers contain '/', which would create nested folders: 'USD01-12/44/2025-ESTT.I' -> 'USD01-12_44_2025-ESTT.I'."""
    return re.sub(r"[/\\:]", "_", file_no.strip())


# ---- what to keep ---------------------------------------------------------------
def topic_decision(abstract: str, scope: dict, all_topics: bool = False) -> tuple[bool, str]:
    """Keep rule-like orders. skip_topics (individual cases, events) win over keep_topics."""
    a = (abstract or "").lower()
    for s_ in scope.get("skip_topics", []) or []:
        if re.search(r"(?<![a-z])" + re.escape(str(s_).lower()), a):
            return False, f"excluded: {s_}"
    a_np = re.sub(r"\b(?:sri|smt|dr|justice)\b\.?\s*[a-z][a-z. ]{0,40}?(?:committee|commission)", "committee", a)
    for pat in scope.get("skip_patterns", []) or []:
        if re.search(pat, a_np, re.I):
            return False, "excluded: names an individual"
    if all_topics:
        return True, "all topics"
    for t in scope.get("keep_topics", []) or []:
        if re.search(r"(?<![a-z])" + re.escape(str(t).lower()), a):
            return True, str(t)
    return False, "no keep topic"


def order_kinds(scope: dict, depts: list[str] | None) -> set[str]:
    """G.O. kinds to keep: per-department `order_types` override the global one. Ms -> GOMS, Rt -> GORT."""
    m = {"MS": "GOMS", "RT": "GORT"}
    out: set[str] = set()
    for d in (depts or [None]):
        types = (scope.get("departments", {}).get(d, {}) or {}).get("order_types") if d else None
        for t in (types or scope.get("order_types", []) or []):
            out.add(m.get(str(t).upper(), str(t).upper()))
    return out
