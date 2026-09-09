"""LLM cross-source contradiction audit over 100% of multi-source groups.

Design for fail-closed, no-slop output:

1. The model sees ONE dossier of verbatim source text at a time and must answer
   in strict JSON.
2. Every flag must carry, for each side, a `claimId` and a `quote` that is a
   VERBATIM substring of that claim's text. `verify_findings.py` re-checks each
   quote against the frozen dataset; a quote that does not appear is a
   hallucination and the finding is REJECTED, not softened.
3. The model is explicitly told that complementary or differing-depth coverage is
   NOT a defect, and that inventing conflicts is the primary failure mode.
4. Any dossier whose response cannot be parsed, or which errors after retries,
   is recorded as UNAUDITED and fails the completeness gate. Nothing is silently
   dropped.
"""
import argparse
import json
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import boto3
from botocore.config import Config

HERE = Path(__file__).resolve().parent.parent
DOSSIERS = HERE / "dossiers"
OUT = HERE / "evidence" / "llm_findings"
MODEL = "global.anthropic.claude-opus-5"

SYSTEM = """You audit a merged Japanese-grammar dictionary for CROSS-SOURCE CONTRADICTIONS.

You receive one canonical grammar point with every contributing source's VERBATIM text side by side.

Your ONLY job is to decide whether two sources make claims that CANNOT BOTH BE TRUE, or that would mislead a learner if shown on the same card.

Report a contradiction ONLY for these classes:
  meaning        - incompatible core meaning/nuance claims about the SAME sense (not different senses, not different wording of the same idea, not different depth of coverage)
  jlpt           - the same sense assigned different JLPT levels
  register       - incompatible formality/register/politeness claims about the same usage
  formation      - conflicting attachment/conjugation rules for the same pattern (e.g. one says the pattern attaches to plain form, another says to stem, for the identical construction)
  example        - example sentences that contradict each other, OR a sentence marked incorrect (x, X, 誤用, NG, 使えない) by one source that another source presents as correct, OR a sentence whose correct/incorrect marking is internally wrong

NOT defects (do NOT report these):
  - one source covering more senses, more detail, or more examples than another
  - different English wordings of the same meaning
  - one source giving a JLPT level and another giving none
  - different senses of a polysemous point being described differently
  - stylistic or emphasis differences
  - a source using Japanese metalanguage while another uses English
  - different but compatible example sentences

Inventing a conflict is the WORST possible failure. When two claims merely differ, that is not a contradiction. If you are unsure whether something is a genuine contradiction, set confidence "low" and explain what a human should glance at.

Cite BOTH sides. For each side give the exact claimId from the dossier and a `quote` that is a VERBATIM contiguous substring copied character-for-character from that claim's text in the dossier. Do not normalize, translate, trim punctuation, or reflow the quote. A quote that is not an exact substring will be automatically rejected.

Respond with ONLY this JSON object and nothing else:
{"entryId": "<the entryId>", "findings": [{"class": "meaning|jlpt|register|formation|example", "confidence": "high|low", "sense": "<canonicalKey or empty>", "sideA": {"claimId": "...", "field": "jlpt|meaning|structure|explanation|notes|example", "quote": "..."}, "sideB": {"claimId": "...", "field": "...", "quote": "..."}, "why": "<one or two sentences stating what cannot both be true>", "proposedTrust": "<optional: which source to trust and why, or empty>"}]}

If there are no genuine contradictions, return {"entryId": "...", "findings": []}."""

USER_TMPL = """Audit this canonical grammar point for cross-source contradictions.

{dossier}"""


class Runner:
    def __init__(self, region="us-east-1", max_attempts=6):
        cfg = Config(
            retries={"max_attempts": 10, "mode": "adaptive"},
            read_timeout=900,
            connect_timeout=30,
        )
        self.client = boto3.client("bedrock-runtime", region_name=region, config=cfg)
        self.max_attempts = max_attempts
        self.lock = threading.Lock()
        self.usage = {"in": 0, "out": 0, "calls": 0}

    def call(self, dossier_text):
        last = None
        for attempt in range(self.max_attempts):
            try:
                r = self.client.converse(
                    modelId=MODEL,
                    system=[{"text": SYSTEM}],
                    messages=[
                        {
                            "role": "user",
                            "content": [{"text": USER_TMPL.format(dossier=dossier_text)}],
                        }
                    ],
                    inferenceConfig={"maxTokens": 8000},
                )
                txt = "".join(
                    b.get("text", "") for b in r["output"]["message"]["content"]
                )
                u = r.get("usage", {})
                with self.lock:
                    self.usage["in"] += u.get("inputTokens", 0)
                    self.usage["out"] += u.get("outputTokens", 0)
                    self.usage["calls"] += 1
                return txt, r.get("stopReason")
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(min(60, (2**attempt) + random.random() * 2))
        raise RuntimeError(f"bedrock failed after {self.max_attempts} attempts: {last}")


def parse_json(txt):
    txt = txt.strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```(?:json)?\s*", "", txt)
        txt = re.sub(r"\s*```$", "", txt)
    start = txt.find("{")
    end = txt.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in response")
    return json.loads(txt[start : end + 1])


def audit_one(runner, path):
    out_path = OUT / path.name
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            if existing.get("status") == "ok":
                return "cached"
        except Exception:  # noqa: BLE001
            pass
    dossier_text = path.read_text(encoding="utf-8")
    entry_id = json.loads(dossier_text)["entryId"]
    rec = {"file": path.name, "entryId": entry_id}
    try:
        txt, stop = runner.call(dossier_text)
        rec["stopReason"] = stop
        if stop == "max_tokens":
            rec.update(status="truncated", raw=txt)
        else:
            data = parse_json(txt)
            if data.get("entryId") != entry_id:
                rec["entryIdMismatch"] = data.get("entryId")
            rec.update(status="ok", findings=data.get("findings", []))
    except Exception as exc:  # noqa: BLE001
        rec.update(status="error", error=str(exc)[:500])
    out_path.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return rec["status"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--files", nargs="*", default=None)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    if args.files:
        paths = [DOSSIERS / f for f in args.files]
    else:
        paths = sorted(DOSSIERS.glob("*.json"))
        if args.limit:
            paths = paths[: args.limit]

    runner = Runner()
    done = {"ok": 0, "cached": 0, "error": 0, "truncated": 0}
    t0 = time.time()
    lock = threading.Lock()

    def work(p):
        st = audit_one(runner, p)
        with lock:
            done[st] = done.get(st, 0) + 1
            n = sum(done.values())
            if n % 25 == 0 or n == len(paths):
                el = time.time() - t0
                print(
                    f"[{n}/{len(paths)}] {done} "
                    f"{el:.0f}s in={runner.usage['in']} out={runner.usage['out']}",
                    flush=True,
                )

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(work, paths))

    print(json.dumps({"done": done, "usage": runner.usage, "seconds": round(time.time() - t0)}))
    return 0 if not (done.get("error") or done.get("truncated")) else 1


if __name__ == "__main__":
    sys.exit(main())
