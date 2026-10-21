"""Convert the mock corpus v1 (C2-24_mock_corpus/) into the data-plan layout under seed/mock-v1/.

  python tools/seed_from_mock.py /path/to/C2-24_mock_corpus

Everything produced is origin: synthetic. Rule-type documents go to rule-library/synthetic/...,
notings/reports/annexures are grouped by e-File number into efiles/<DEPT>/<SECTION>/<file-slug>/.
"""
from __future__ import annotations

import csv
import json
import pathlib
import re
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import ROOT, append_jsonl, file_slug, read_list, sha256, write_json  # noqa: E402

BANNER = "<!-- SYNTHETIC — not a real government file (C2-24 mock corpus v1) -->\n"
RULE_TYPES = {"Government Order", "Amendment", "Clarification", "Circular", "Standing Order"}
STAMP = "2026-10-02T00:00:00+05:30"


def iso(d: str | None):
    if not d:
        return None
    dd, mm, yy = d.split("-")
    return f"{yy}-{mm}-{dd}"


def split_notes(text: str):
    parts = re.split(r"\n(?=Note\s*#\s*\d+)", "\n" + text)
    header, notes = parts[0].strip(), [p.strip() for p in parts[1:] if p.strip()]
    return header, notes


def signature(note: str):
    m = re.search(r"\n([^\n/]+?)\s*/\s*([^\n/]+?)\s*/\s*(\d{2}/\d{2}/\d{4}\s+\d{1,2}:\d{2}\s*[AP]M)\s*$", note.strip())
    return {"name": m.group(1).strip(), "designation": m.group(2).strip(), "at": m.group(3)} if m else None


def main():
    src = pathlib.Path(sys.argv[1])
    out = ROOT / "seed" / "mock-v1"
    if out.exists():
        sys.exit(f"{out} exists; move it aside first")
    man = json.loads((src / "manifest.json").read_text())["documents"]
    gt_text = src / "ground_truth" / "text"
    efiles: dict[str, list] = {}
    for d in man:
        text = (gt_text / f"{d['id']}.txt").read_text() if (gt_text / f"{d['id']}.txt").exists() else ""
        # memos/circulars carry their issue date in the ID (see common.canonical_id)
        if d["canonical_id"].split("-")[2] in ("MEMO", "CIRMEMO", "RC"):
            d["canonical_id"] = d["canonical_id"] + "-D" + iso(d["date"]).replace("-", "")
        if d["doc_type"] in RULE_TYPES:
            ext = pathlib.Path(d["file"]).suffix
            folder = out / "rule-library" / "synthetic" / d["dept"] / iso(d["date"])[:4] / d["canonical_id"]
            folder.mkdir(parents=True)
            shutil.copy2(src / d["file"], folder / f"order{ext}")
            (folder / "ocr.txt").write_text(text)
            meta = {
                "canonical_id": d["canonical_id"], "doc_type": d["doc_type"], "instrument": d["instrument"],
                "number": re.search(r"-(\d+)-\d{4}", d["canonical_id"]).group(1), "date": iso(d["date"]),
                "date_raw": d["date"], "department_code": d["dept"], "department_name": None, "section": d["sec"],
                "subject": d["subject"], "hierarchy_level": d["level"], "classification": d["classification"],
                "status": d["status"], "effective_from": d["effective_from"], "effective_to": d["effective_to"],
                "read_list": read_list(text), "language": d["language"], "origin": "synthetic",
                "source_name": "C2-24 mock corpus v1", "source_url": f"mock://{d['file']}",
                "archive_identifier": None, "verification_status": "synthetic", "parse_confidence": "ground-truth",
                "files": {"original": f"order{ext}", "ocr": "ocr.txt"}, "ingest_path": d["ingest_path"],
                "file_no": d["file_no"], "computer_no": d["computer_no"],
                "sha256": sha256(folder / f"order{ext}"), "ocr_source": "ground-truth text (clean)",
                "collected_at": STAMP, "collector": "tools/seed_from_mock.py"}
            write_json(folder / "meta.json", meta)
            append_jsonl(out / "manifests" / "provenance.jsonl", {
                "canonical_id": d["canonical_id"], "source_name": meta["source_name"], "source_url": meta["source_url"],
                "sha256": meta["sha256"], "method": "seed_from_mock.py", "origin": "synthetic", "collected_at": STAMP})
        else:
            efiles.setdefault(d["file_no"], []).append((d, text))

    for file_no, docs in efiles.items():
        d0 = docs[0][0]
        folder = out / "efiles" / d0["dept"] / d0["sec"] / file_slug(file_no)
        for sub in ("Correspondence", "Note File1", "GO", "Drafts", "Documents"):
            (folder / sub).mkdir(parents=True, exist_ok=True)
        notes_written, movements, cited = 0, [], []
        top_class = max((x[0]["classification"] for x in docs),
                        key=["UNCLASSIFIED", "RESTRICTED", "CONFIDENTIAL", "SECRET"].index)
        for d, text in docs:
            shutil.copy2(src / d["file"], folder / "Documents" / pathlib.Path(d["file"]).name)
            memo_ids = {x["canonical_id"].rsplit("-D", 1)[0]: x["canonical_id"] for x in man if "-D" in x["canonical_id"]}
            cited += [memo_ids.get(r["target"], r["target"]) for r in d["relations"] if r["type"] == "CITES"]
            if d["doc_type"].startswith("Noting"):
                _, notes = split_notes(text)
                for n in notes:
                    notes_written += 1
                    status = "yellow (draft)" if d["status"] == "under_processing" and n is notes[-1] else "green"
                    (folder / "Note File1" / f"note-{notes_written:03d}.md").write_text(
                        BANNER + f"<!-- source doc {d['id']} · {status} -->\n" + n + "\n")
                    sig = signature(n)
                    if sig:
                        movements.append(sig)
        for a, b in zip(movements, movements[1:]):
            a["sent_to"] = b["designation"]
        write_json(folder / "file.json", {
            "file_no": file_no, "computer_no": d0["computer_no"], "canonical_id": d0["canonical_id"],
            "subject": d0["subject"], "department_code": d0["dept"], "section": d0["sec"],
            "classification": top_class, "status": d0["status"], "decision": d0.get("decision"),
            "documents": [d["canonical_id"] for d, _ in docs], "origin": "synthetic",
            "banner": "Synthetic — not a real government file"})
        write_json(folder / "GO" / "link.json", sorted(set(cited)))
        write_json(folder / "movements.json", movements)
        write_json(folder / "links.json", [])
        (folder / "Correspondence" / "README.md").write_text(
            BANNER + "Receipts not yet generated (mock v1 has no receipt objects) - Step 8 adds them.\n")
        if notes_written == 0:
            (folder / "Note File1" / "note-000.md").write_text(
                BANNER + f"No noting in mock v1; file holds {', '.join(d['doc_type'] for d, _ in docs)} only.\n")

    # directory, access and ground truth
    (out / "directory").mkdir(parents=True, exist_ok=True)
    with open(src / "users.csv") as f:
        write_json(out / "directory" / "officers.json", list(csv.DictReader(f)))
    shutil.copy2(src / "access_matrix.csv", out / "directory" / "access_matrix.csv")
    (out / "ground-truth").mkdir(parents=True, exist_ok=True)
    for name in ("conflicts.json", "golden_questions.json", "relations.csv"):
        shutil.copy2(src / "ground_truth" / name, out / "ground-truth" / name)
    (out / "README.md").write_text(
        "# Seed: mock corpus v1 (SYNTHETIC)\n\nAll content is invented for testing the C2-24 pipeline. "
        "Not real government records. Real collected data goes in ../../staging/.\n")
    print(f"seed written to {out}")


if __name__ == "__main__":
    main()
