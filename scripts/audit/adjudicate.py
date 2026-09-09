"""Adversarial adjudication: try to DISPROVE each verified finding.

The audit pass is biased toward reporting. This pass is biased toward rejection:
it receives the full dossier plus one candidate finding and must argue whether
the two cited claims genuinely cannot both be true, or whether the flag is an
artifact of sense confusion, complementary coverage, wording, or scope.

Only findings that survive this pass AND carry verbatim-verified citations reach
the must-fix list. Everything else lands in low-confidence or dismissed.
"""
import argparse
import json
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
OUT = HERE / "evidence" / "adjudication"
MODEL = "global.anthropic.claude-opus-5"

SYSTEM = """You are the SKEPTIC in a two-stage audit of a merged Japanese-grammar dictionary.

A first pass flagged a possible CROSS-SOURCE CONTRADICTION. Your job is to try hard to DISPROVE it. Most flags in audits like this are false: they usually turn out to be different senses of a polysemous point, complementary coverage, different depth, different metalanguage, or a paraphrase difference dressed up as a conflict.

You get the complete verbatim dossier for the grammar point and the candidate finding.

Ask, in order:
1. Do the two cited claims actually describe the SAME sense/usage? If they describe different senses of a polysemous pattern, the flag is FALSE.
2. Can both statements be simultaneously true as written? If yes, FALSE.
3. Is the difference only wording, depth, emphasis, metalanguage, or one source being silent? If yes, FALSE.
4. For JLPT: is the level attached to the same sense on both sides? Sources legitimately grade different senses differently, and sources legitimately disagree about difficulty. A bare level difference on the SAME sense is a real label mismatch (UPHELD), but a level difference across DIFFERENT senses is FALSE.
5. For examples: does one source state a restriction that another source's example genuinely violates, or does one source mark as incorrect a sentence another presents as correct? Check whether the restriction actually covers that example. If it does not, FALSE.
6. For formation: would following one source's rule produce a form the other source's rule forbids, for the identical construction? A more detailed or a more abbreviated formula is NOT a conflict.

Also judge LEARNER IMPACT: would a learner reading ONE merged card containing both claims be actively misled (impact "high"), mildly confused (impact "medium"), or unaffected (impact "low")?

Be concrete and quote the dossier. Do not invent text.

Respond with ONLY this JSON and nothing else:
{"verdict": "upheld|false|uncertain", "impact": "high|medium|low", "sameSense": true|false, "reasoning": "<2-4 sentences, citing the dossier>", "disproofAttempt": "<the strongest argument that the flag is FALSE, even if you uphold it>", "trustRecommendation": "<which source a maintainer should follow and why, or empty>"}

Use "uncertain" only when the dossier genuinely does not settle it; say what a human must glance at."""


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

    def call(self, text):
        last = None
        for attempt in range(self.max_attempts):
            try:
                r = self.client.converse(
                    modelId=MODEL,
                    system=[{"text": SYSTEM}],
                    messages=[{"role": "user", "content": [{"text": text}]}],
                    inferenceConfig={"maxTokens": 12000},
                )
                txt = "".join(b.get("text", "") for b in r["output"]["message"]["content"])
                u = r.get("usage", {})
                with self.lock:
                    self.usage["in"] += u.get("inputTokens", 0)
                    self.usage["out"] += u.get("outputTokens", 0)
                    self.usage["calls"] += 1
                return txt, r.get("stopReason")
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(min(60, (2**attempt) + random.random() * 2))
        raise RuntimeError(f"bedrock failed: {last}")


def parse_json(txt):
    txt = txt.strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```(?:json)?\s*", "", txt)
        txt = re.sub(r"\s*```$", "", txt)
    s, e = txt.find("{"), txt.rfind("}")
    if s < 0 or e < s:
        raise ValueError("no JSON")
    body = txt[s : e + 1]
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        # a raw newline or unescaped control char inside a string value is the
        # only malformation observed; repair it rather than dropping the verdict
        return json.loads(re.sub(r"(?<!\\)\n", "\\n", body))


def key_of(f):
    return f"{f['file'].replace('.json','')}-{f['n']}"


def adjudicate(runner, finding):
    fp = OUT / f"{key_of(finding)}.json"
    if fp.exists():
        try:
            if json.loads(fp.read_text(encoding="utf-8")).get("status") == "ok":
                return "cached"
        except Exception:  # noqa: BLE001
            pass
    dossier = (DOSSIERS / finding["file"]).read_text(encoding="utf-8")
    prompt = (
        "CANDIDATE FINDING (from the first pass):\n"
        + json.dumps(
            {
                "class": finding["class"],
                "firstPassConfidence": finding["confidence"],
                "sense": finding["sense"],
                "sideA": finding["sideA"],
                "sideB": finding["sideB"],
                "why": finding["why"],
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n\nFULL VERBATIM DOSSIER:\n"
        + dossier
    )
    rec = {"key": key_of(finding), "file": finding["file"], "entryId": finding["entryId"],
           "class": finding["class"], "firstPassConfidence": finding["confidence"]}
    try:
        txt, stop = runner.call(prompt)
        if stop == "max_tokens":
            rec.update(status="truncated", raw=txt[:2000])
        else:
            rec.update(status="ok", **parse_json(txt))
    except Exception as exc:  # noqa: BLE001
        rec.update(status="error", error=str(exc)[:400])
    fp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return rec["status"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    verified = json.loads(
        (HERE / "evidence" / "verified_findings.json").read_text(encoding="utf-8")
    )
    findings = verified["accepted"]
    if args.limit:
        findings = findings[: args.limit]

    runner = Runner()
    done = {}
    t0 = time.time()
    lock = threading.Lock()

    def work(f):
        st = adjudicate(runner, f)
        with lock:
            done[st] = done.get(st, 0) + 1
            n = sum(done.values())
            if n % 25 == 0 or n == len(findings):
                print(
                    f"[{n}/{len(findings)}] {done} {time.time()-t0:.0f}s "
                    f"in={runner.usage['in']} out={runner.usage['out']}",
                    flush=True,
                )

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(work, findings))

    print(json.dumps({"done": done, "usage": runner.usage, "seconds": round(time.time() - t0)}))
    return 0 if not (done.get("error") or done.get("truncated")) else 1


if __name__ == "__main__":
    sys.exit(main())
