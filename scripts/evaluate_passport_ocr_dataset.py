"""Evaluate the passport OCR/MRZ pipeline against a labelled dataset.

The `passport/` folder holds paired samples: for every `<base>.jpg` passport
image there is a `<base>.txt` file with the ground-truth extraction (Passport
Number, Surname/Given name, Country Code, DOB, Sex, Expiry, and the two MRZ
lines).

This script runs the exact production OCR path -- `PassportFraudAnalyzer.analyze`
(Tesseract text extraction -> `MrzAnalyzer` TD3 parse) -- on a random sample and
compares the MRZ-derived fields the eKYC system actually consumes against the
ground truth. It reports per-field accuracy plus MRZ line/character accuracy.

Usage:
    .venv/bin/python scripts/evaluate_passport_ocr_dataset.py [--sample N] [--seed S] [--dir passport] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services.fraud import PassportFraudAnalyzer  # noqa: E402

MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


@dataclass
class GroundTruth:
    passport_number: str | None = None
    surname: str | None = None
    given_name: str | None = None
    nationality: str | None = None      # 3-letter country code
    date_of_birth: date | None = None
    sex: str | None = None              # "M" / "F"
    expiry_date: date | None = None
    mrz_line1: str | None = None
    mrz_line2: str | None = None


def _field(text: str, label: str) -> str | None:
    m = re.search(rf"^{re.escape(label)}:\s*(.+)$", text, re.MULTILINE)
    if not m:
        return None
    value = m.group(1).strip()
    return value or None


def _romanize(value: str | None) -> str | None:
    """Keep only the ASCII/latin portion of a bilingual field.

    e.g. "ZHANG (张)" -> "ZHANG", "李宁 / LI, NING" -> "LI NING".
    """
    if not value:
        return None
    # Prefer the part after a "/" if present (usually the romanized side).
    if "/" in value:
        value = value.split("/")[-1]
    value = re.sub(r"\([^)]*\)", " ", value)          # drop parentheticals
    value = re.sub(r"[^A-Za-z<,\s-]", " ", value)     # keep latin letters only
    value = value.replace(",", " ").replace("-", " ")
    tokens = [t for t in value.upper().split() if t]
    return " ".join(tokens) or None


def _parse_date(value: str | None, *, prefer_future: bool) -> date | None:
    if not value:
        return None
    text = value.upper()
    year_m = re.search(r"\b(\d{4})\b", text)
    if not year_m:
        return None
    year = int(year_m.group(1))
    # month: english abbreviation, else a standalone 1-2 digit number
    month: int | None = None
    for name, num in MONTHS.items():
        if name in text:
            month = num
            break
    nums = [int(n) for n in re.findall(r"\b(\d{1,2})\b", text)]
    if month is None:
        # of the 1-2 digit numbers, one is the day (1-31) and one the month (1-12)
        candidates = [n for n in nums if 1 <= n <= 12]
        month = candidates[0] if candidates else None
    day = None
    for n in nums:
        if 1 <= n <= 31 and n != month:
            day = n
            break
    if day is None:
        day = next((n for n in nums if 1 <= n <= 31), None)
    if month is None or day is None:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _mrz_date(yymmdd: str, *, expiry: bool) -> date | None:
    if len(yymmdd) < 6 or not yymmdd[:6].isdigit():
        return None
    yy, mm, dd = int(yymmdd[0:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    if expiry:
        year = 2000 + yy                       # passport expiries are this century
    else:
        year = 2000 + yy
        if year > date.today().year:           # birthdays can't be in the future
            year = 1900 + yy
    try:
        return date(year, mm, dd)
    except ValueError:
        return None


def _decode_mrz(line1: str, line2: str, gt: GroundTruth) -> None:
    """Decode canonical fields from clean ground-truth TD3 MRZ lines.

    The dataset's human-readable fields are unreliable (placeholders like
    "SURNAME", ambiguous DD/MM ordering), but the MRZ lines are canonical and
    are exactly what the eKYC pipeline consumes -- so they are the ground truth.
    """
    l1 = line1.ljust(44, "<")
    l2 = line2.ljust(44, "<")
    gt.nationality = l1[2:5].replace("<", "").upper() or l2[10:13].replace("<", "").upper() or None
    names = l1[5:].split("<<", 1)
    gt.surname = " ".join(t for t in names[0].split("<") if t) or None
    gt.given_name = (" ".join(t for t in names[1].split("<") if t) if len(names) > 1 else None) or None
    gt.passport_number = l2[0:9].replace("<", "").upper() or None
    gt.date_of_birth = _mrz_date(l2[13:19], expiry=False)
    sex = l2[20]
    gt.sex = sex if sex in ("M", "F") else None
    gt.expiry_date = _mrz_date(l2[21:27], expiry=True)


def parse_ground_truth(text: str) -> GroundTruth:
    gt = GroundTruth()
    mrz_block = text.split("MRZ Lines:", 1)
    if len(mrz_block) == 2:
        lines = [ln.strip() for ln in mrz_block[1].splitlines() if ln.strip()]
        mrz_lines = [ln for ln in lines if re.fullmatch(r"[A-Z0-9<]{20,}", ln)]
        if len(mrz_lines) >= 2:
            gt.mrz_line1, gt.mrz_line2 = mrz_lines[0], mrz_lines[1]

    if gt.mrz_line1 and gt.mrz_line2:
        _decode_mrz(gt.mrz_line1, gt.mrz_line2, gt)
    else:
        # Fallback to the (noisier) printed fields only when MRZ is absent.
        gt.passport_number = (_field(text, "Passport Number") or "").replace(" ", "").upper() or None
        gt.surname = _romanize(_field(text, "Surname/Family Name") or _field(text, "Surname"))
        gt.given_name = _romanize(_field(text, "Given Name/First Name") or _field(text, "Given Name"))
        gt.nationality = (_field(text, "Country Code") or "").strip().upper() or None
        gt.date_of_birth = _parse_date(_field(text, "Date of Birth"), prefer_future=False)
        sex_raw = _field(text, "Gender/Sex") or _field(text, "Gender") or _field(text, "Sex") or ""
        gt.sex = "F" if re.search(r"\bF\b|FEMALE|女", sex_raw.upper()) else ("M" if re.search(r"\bM\b|MALE|男", sex_raw.upper()) else None)
        gt.expiry_date = _parse_date(_field(text, "Expired Date") or _field(text, "Expiry Date"), prefer_future=True)
    return gt


def _norm_mrz(line: str | None) -> str:
    return re.sub(r"[^A-Z0-9<]", "", (line or "").upper())


def _char_accuracy(expected: str, actual: str) -> float:
    """1 - normalized Levenshtein distance."""
    if not expected and not actual:
        return 1.0
    if not expected or not actual:
        return 0.0
    m, n = len(expected), len(actual)
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        cur = [i] + [0] * n
        for j in range(1, n + 1):
            cost = 0 if expected[i - 1] == actual[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    dist = prev[n]
    return 1.0 - dist / max(m, n)


@dataclass
class Tally:
    considered: int = 0     # ground truth had this field
    correct: int = 0

    def add(self, expected_present: bool, is_correct: bool) -> None:
        if expected_present:
            self.considered += 1
            if is_correct:
                self.correct += 1

    @property
    def pct(self) -> float:
        return 100.0 * self.correct / self.considered if self.considered else float("nan")


def _name_tokens(*parts: str | None) -> set[str]:
    tokens: set[str] = set()
    for p in parts:
        if p:
            tokens.update(t for t in p.upper().split() if t)
    return tokens


def evaluate(sample: int, seed: int, folder: Path, json_out: Path | None) -> None:
    jpgs = {p.stem: p for p in folder.iterdir() if p.suffix.lower() == ".jpg"}
    txts = {p.stem: p for p in folder.iterdir() if p.suffix.lower() == ".txt"}
    paired = sorted(set(jpgs) & set(txts))
    if not paired:
        print("No paired .jpg/.txt samples found in", folder)
        return

    # Split passports (ground truth has MRZ lines) from face-only / non-passport
    # images (the label file says it is not a passport). Non-passport images are
    # not OCR failures, so they are excluded from accuracy scoring and instead
    # checked for correct rejection (the pipeline must NOT read an MRZ from them).
    passport_pairs: list[str] = []
    nonpassport_pairs: list[str] = []
    for base in paired:
        gt = parse_ground_truth(txts[base].read_text(encoding="utf-8", errors="replace"))
        (passport_pairs if (gt.mrz_line1 and gt.mrz_line2) else nonpassport_pairs).append(base)

    rng = random.Random(seed)
    chosen = passport_pairs if sample <= 0 or sample >= len(passport_pairs) else rng.sample(passport_pairs, sample)
    print(f"Dataset: {len(paired)} paired samples "
          f"({len(passport_pairs)} passports, {len(nonpassport_pairs)} face-only/non-passport) in {folder}")
    print(f"Evaluating {len(chosen)} passport sample(s) (seed={seed})\n")

    analyzer = PassportFraudAnalyzer()

    tallies = {name: Tally() for name in
               ("passport_number", "name", "nationality", "date_of_birth", "sex", "expiry_date")}
    mrz_found = 0
    mrz_valid = 0
    line1_exact = line2_exact = 0
    line1_acc: list[float] = []
    line2_acc: list[float] = []
    mrz_gt_count = 0
    per_sample = []

    t0 = time.time()
    for idx, base in enumerate(chosen, 1):
        gt = parse_ground_truth(txts[base].read_text(encoding="utf-8", errors="replace"))
        content = jpgs[base].read_bytes()
        try:
            analysis = analyzer.analyze(content, jpgs[base].name)
            ocr = analysis.ocr
        except Exception as exc:  # noqa: BLE001
            print(f"[{idx}/{len(chosen)}] {base[:24]}... ERROR: {exc}")
            continue

        found = bool(analysis.checks.get("mrz_found"))
        valid = bool(ocr.mrz_valid)
        mrz_found += int(found)
        mrz_valid += int(valid)

        pn_ok = bool(gt.passport_number and ocr.passport_number
                     and gt.passport_number == ocr.passport_number.replace("<", "").upper())
        tallies["passport_number"].add(gt.passport_number is not None, pn_ok)

        gt_name = _name_tokens(gt.surname, gt.given_name)
        got_name = _name_tokens(ocr.full_name)
        name_ok = bool(gt_name) and gt_name == got_name
        tallies["name"].add(bool(gt_name), name_ok)

        nat_ok = bool(gt.nationality and ocr.nationality
                      and gt.nationality == ocr.nationality.upper())
        tallies["nationality"].add(gt.nationality is not None, nat_ok)

        dob_ok = bool(gt.date_of_birth and ocr.date_of_birth and gt.date_of_birth == ocr.date_of_birth)
        tallies["date_of_birth"].add(gt.date_of_birth is not None, dob_ok)

        got_sex = None
        if ocr.extracted_fields.get("sex") in ("M", "F"):
            got_sex = ocr.extracted_fields["sex"]
        sex_ok = bool(gt.sex and got_sex and gt.sex == got_sex)
        tallies["sex"].add(gt.sex is not None, sex_ok)

        exp_ok = bool(gt.expiry_date and ocr.expiry_date and gt.expiry_date == ocr.expiry_date)
        tallies["expiry_date"].add(gt.expiry_date is not None, exp_ok)

        if gt.mrz_line1 and gt.mrz_line2:
            mrz_gt_count += 1
            got_lines = (ocr.mrz_text or "").splitlines()
            got1 = _norm_mrz(got_lines[0] if len(got_lines) > 0 else "")
            got2 = _norm_mrz(got_lines[1] if len(got_lines) > 1 else "")
            exp1, exp2 = _norm_mrz(gt.mrz_line1), _norm_mrz(gt.mrz_line2)
            line1_exact += int(got1 == exp1)
            line2_exact += int(got2 == exp2)
            line1_acc.append(_char_accuracy(exp1, got1))
            line2_acc.append(_char_accuracy(exp2, got2))

        per_sample.append({
            "base": base, "mrz_found": found, "mrz_valid": valid,
            "passport_number": pn_ok, "name": name_ok, "nationality": nat_ok,
            "date_of_birth": dob_ok, "sex": sex_ok, "expiry_date": exp_ok,
        })
        flag = "OK " if valid else ("~  " if found else "XX ")
        print(f"[{idx}/{len(chosen)}] {flag} pn={'Y' if pn_ok else '.'} "
              f"name={'Y' if name_ok else '.'} nat={'Y' if nat_ok else '.'} "
              f"dob={'Y' if dob_ok else '.'} sex={'Y' if sex_ok else '.'} "
              f"exp={'Y' if exp_ok else '.'}  {base[:20]}")

    # Face-only / non-passport handling: the pipeline should NOT read an MRZ.
    nonpass_checked = nonpass_correct = 0
    nonpass_cap = min(len(nonpassport_pairs), max(0, sample)) if sample > 0 else len(nonpassport_pairs)
    nonpass_sample = (nonpassport_pairs if nonpass_cap >= len(nonpassport_pairs)
                      else rng.sample(nonpassport_pairs, nonpass_cap))
    for base in nonpass_sample:
        try:
            analysis = analyzer.analyze(jpgs[base].read_bytes(), jpgs[base].name)
        except Exception:  # noqa: BLE001
            continue
        nonpass_checked += 1
        if not bool(analysis.checks.get("mrz_found")):
            nonpass_correct += 1

    n = len(chosen)
    elapsed = time.time() - t0
    print("\n" + "=" * 64)
    print("PASSPORT OCR / MRZ ACCURACY")
    print("=" * 64)
    print(f"Samples evaluated      : {n}")
    print(f"MRZ detected (found)   : {mrz_found}/{n}  ({100.0*mrz_found/n:.1f}%)")
    print(f"MRZ fully valid        : {mrz_valid}/{n}  ({100.0*mrz_valid/n:.1f}%)")
    print("-" * 64)
    print("Per-field accuracy (of samples where ground truth has the field):")
    labels = {
        "passport_number": "Passport number",
        "name": "Name (surname+given)",
        "nationality": "Nationality (country)",
        "date_of_birth": "Date of birth",
        "sex": "Sex",
        "expiry_date": "Expiry date",
    }
    for key, label in labels.items():
        t = tallies[key]
        print(f"  {label:<24}: {t.correct:>3}/{t.considered:<3}  {t.pct:5.1f}%")
    print("-" * 64)
    if mrz_gt_count:
        print(f"MRZ line 1 exact match : {line1_exact}/{mrz_gt_count}  ({100.0*line1_exact/mrz_gt_count:.1f}%)")
        print(f"MRZ line 2 exact match : {line2_exact}/{mrz_gt_count}  ({100.0*line2_exact/mrz_gt_count:.1f}%)")
        print(f"MRZ line 1 char acc    : {100.0*sum(line1_acc)/len(line1_acc):.1f}%")
        print(f"MRZ line 2 char acc    : {100.0*sum(line2_acc)/len(line2_acc):.1f}%")
    print("-" * 64)
    if nonpass_checked:
        print(f"Face-only images tested: {nonpass_checked}  "
              f"(correctly NOT read as passport: {nonpass_correct}/{nonpass_checked}, "
              f"{100.0*nonpass_correct/nonpass_checked:.1f}%)")
        print("-" * 64)
    print(f"Elapsed                : {elapsed:.1f}s  ({elapsed/max(n,1):.2f}s/image)")

    if json_out:
        summary = {
            "samples": n,
            "mrz_found_pct": 100.0 * mrz_found / n,
            "mrz_valid_pct": 100.0 * mrz_valid / n,
            "nonpassport_checked": nonpass_checked,
            "nonpassport_correctly_rejected": nonpass_correct,
            "fields": {k: {"correct": t.correct, "considered": t.considered, "pct": t.pct}
                       for k, t in tallies.items()},
            "mrz": {
                "gt_count": mrz_gt_count,
                "line1_exact": line1_exact,
                "line2_exact": line2_exact,
                "line1_char_acc": (sum(line1_acc) / len(line1_acc)) if line1_acc else None,
                "line2_char_acc": (sum(line2_acc) / len(line2_acc)) if line2_acc else None,
            },
            "per_sample": per_sample,
        }
        json_out.write_text(json.dumps(summary, indent=2, default=str))
        print(f"\nWrote detailed results to {json_out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", type=int, default=100, help="number of pairs to evaluate (0 = all)")
    ap.add_argument("--seed", type=int, default=20260709)
    ap.add_argument("--dir", type=Path, default=REPO_ROOT / "passport")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()
    evaluate(args.sample, args.seed, args.dir, args.json)


if __name__ == "__main__":
    main()
