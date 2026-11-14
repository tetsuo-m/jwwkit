"""手元の図面フォルダで、jwwkit の読込み・無編集保存・読み直しを一括で確かめる開発用の道具。

配布物には入れない（tools/release_files.txt に載せない）。

使い方:
    python -B tools/corpus_check.py --source <図面フォルダ> [--source <別のフォルダ>]
        --output <出力フォルダ> [--timeout 120] [--retry-timeout 600] [--jobs 1]
        [--sample 20] [--resume]

- 図面の原本は読むだけ。書くのは出力フォルダの中だけ。
- 出力フォルダがリポジトリや図面フォルダの中なら拒否する。
- 中身（SHA256）が同じ図面は1件にまとめ、図面001… の伏せた名前で記録する。
  本当のパスは出力フォルダの「対応表.json」にだけ書く。
- 1件ごとに別のプロセスで調べ、時間の上限を過ぎたら打ち切って次へ進む。
  時間切れのものだけ、長い上限でやり直す。
- --resume で、中断した出力フォルダの続きから再開する（終わった図面は飛ばす）。
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures
import datetime
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

# 記録の項目を変えたら上げる。版の違う出力フォルダは --resume で続けない
TOOL_VERSION = 2
EXTENSIONS = {".jww", ".jws"}
MAPPING_NAME = "対応表.json"
SUMMARY_NAME = "summary.md"
RESULTS_DIR = "results"
WORK_DIR = "work"
REPO_ROOT = Path(__file__).resolve().parent.parent
CHUNK = 1 << 20


class UsageError(Exception):
    """利用者の指定が安全の条件を満たさないとき。"""


# ---------------------------------------------------------------------------
# 共通の小道具

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            chunk = stream.read(CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def jwwkit_info() -> dict:
    import importlib.metadata
    import jwwkit
    try:
        version = importlib.metadata.version("jwwkit")
    except importlib.metadata.PackageNotFoundError:
        version = None
    return dict(version=version, location=str(Path(jwwkit.__file__).resolve().parent))


def write_json_atomic(path: Path, data) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="backslashreplace", newline="\n") as stream:
            stream.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"|「[^」]*」|『[^』]*』")
_PATH = re.compile(r"[A-Za-z]:[\\/][^\s;,)]*|\\\\[^\s;,)]+|(?<![\w.])/(?:[^\s/;,)]+/)+[^\s;,)]*")
_HEX = re.compile(r"\b0x[0-9A-Fa-f]+\b")
# 英字に続く数字（JWS700、v600 など識別子の一部）は伏せない
_NUMBER = re.compile(r"(?<![A-Za-z_\d.])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def scrub_paths(message: str, paths: list[str | Path]) -> str:
    """例外のメッセージから、本当のパス・ファイル名・フォルダ名を伏せる。"""
    text = message or ""
    variants: set[str] = set()
    for value in paths:
        path = Path(value)
        for form in (str(path), path.as_posix()):
            variants.update({form, form.replace("\\", "\\\\"), repr(form)[1:-1]})
        if path.suffix:
            variants.update({path.name, path.stem})
        # 案件名などのフォルダ名は、パスの形をとらずに出ることがある。日本語などを含む名前を伏せる
        variants.update(parent.name for parent in path.parents if not parent.name.isascii())
    for variant in sorted((v for v in variants if len(v) >= 2), key=len, reverse=True):
        text = text.replace(variant, "<図面>")
    return _PATH.sub("<path>", text)


def error_category(class_name: str, message: str) -> str:
    """例外の種類と、数字・パス・引用を伏せた決まり文句で、拒否の理由を分ける。"""
    text = (message or "").strip().splitlines()[0] if (message or "").strip() else ""
    text = _QUOTED.sub("<…>", text)
    text = _PATH.sub("<path>", text)
    text = _HEX.sub("N", text)
    text = _NUMBER.sub("N", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 160:
        text = text[:160] + "…"
    return f"{class_name}: {text}" if text else class_name


def is_rejection(exc: BaseException) -> bool:
    """ライブラリが意図して拒否したもの（ValueError 系）か。文字コードの例外は予想外として扱う。"""
    return isinstance(exc, ValueError) and not isinstance(exc, UnicodeError)


def code_frames(exc: BaseException, limit: int = 6) -> list[str]:
    """例外の起きた場所（モジュール:関数:行）だけを残す。ソースの行や値は残さない。"""
    frames = traceback.extract_tb(exc.__traceback__)
    rows = []
    for frame in frames[-limit:]:
        module = Path(frame.filename).as_posix()
        for marker in ("/jwwkit/", "/ezjww/"):
            if marker in module:
                module = marker.strip("/") + "/" + module.split(marker, 1)[1]
                break
        else:
            module = Path(frame.filename).name
        rows.append(f"{module}:{frame.name}:{frame.lineno}")
    return rows


# ---------------------------------------------------------------------------
# 1件を調べる（子プロセスで動く）

def _counts_jww(document) -> dict:
    by_type = collections.Counter(e.entity_type for e in document.entities)
    definitions = [
        dict(number=d.number, entity_count=len(d.entities),
             by_type=dict(sorted(collections.Counter(e.entity_type for e in d.entities).items())))
        for d in document.block_definitions
    ]
    return dict(entity_count=len(document.entities), by_type=dict(sorted(by_type.items())),
                block_definition_count=len(document.block_definitions),
                block_definition_entity_count=sum(x["entity_count"] for x in definitions),
                block_definitions=definitions,
                metadata_settings_count=len(document.metadata_settings),
                diagnostics_count=len(document.diagnostics))


def _counts_jws(document) -> dict:
    by_type = collections.Counter(e.entity_type for e in document.entities)
    definitions = [
        dict(number=d.number, entity_count=len(d.entities),
             by_type=dict(sorted(collections.Counter(e.entity_type for e in d.entities).items())))
        for d in document.block_definitions
    ]
    return dict(entity_count=len(document.entities), by_type=dict(sorted(by_type.items())),
                block_definition_count=len(document.block_definitions),
                block_definition_entity_count=sum(x["entity_count"] for x in definitions),
                block_definitions=definitions)


def _first_difference(a: bytes, b: bytes) -> int | None:
    limit = min(len(a), len(b))
    step = 4096
    for start in range(0, limit, step):
        if a[start:start + step] != b[start:start + step]:
            for i in range(start, min(start + step, limit)):
                if a[i] != b[i]:
                    return i
    return None if len(a) == len(b) else limit


def _compare_counts(before: dict, after: dict) -> dict:
    keys = ("entity_count", "by_type", "block_definition_count", "block_definition_entity_count",
            "block_definitions")
    differences = {k: dict(before=before.get(k), after=after.get(k))
                   for k in keys if before.get(k) != after.get(k)}
    return dict(same=not differences, differences=differences)


def declared_version(data: bytes) -> int | None:
    """ファイルの先頭に書かれた版の数字（読めるかどうかとは別。拒否された図面の版を数えるため）。"""
    import struct
    if data[:8] == b"JwwData." and len(data) >= 12:
        return struct.unpack_from("<I", data, 8)[0]
    if data[:8] == b"JwsData." and len(data) >= 204:
        return struct.unpack_from("<I", data, 200)[0]
    return None


def declared_version_of_file(path: str | Path) -> int | None:
    """親プロセスで作る記録（時間切れなど）用。先頭 204 バイトだけを読む。"""
    try:
        with open(path, "rb") as stream:
            return declared_version(stream.read(204))
    except OSError:
        return None


def inspect_one(source: Path, work_file: Path, stage_file: Path | None = None) -> dict:
    """1件の図面を、読込み→無編集保存→バイト比較→読み直しの順に確かめる。

    source は読むだけ。書くのは work_file（と stage_file）だけ。
    """
    def stage(name: str) -> None:
        if stage_file is not None:
            stage_file.write_text(name, encoding="utf-8")

    result: dict = dict(kind=source.suffix.lower().lstrip("."), jwwkit=jwwkit_info(),
                        timings={}, stages_completed=[])
    current = "read_source"
    original = b""
    try:
        stage("hash_before")
        original = source.read_bytes()
        result["size"] = len(original)
        result["sha256_before"] = hashlib.sha256(original).hexdigest()
        result["declared_version"] = declared_version(original)
        current = "open"
        stage("open")
        started = time.perf_counter()
        if result["kind"] == "jww":
            from jwwkit import CadDocument
            document = CadDocument.open(source)
            counts = _counts_jww(document)
        else:
            from jwwkit.cad_model import JwsDocument
            document = JwsDocument.open(source)
            counts = _counts_jws(document)
        result["timings"]["open"] = round(time.perf_counter() - started, 4)
        result["version"] = document.version
        result["counts"] = counts
        result["stages_completed"].append("open")

        current = "save"
        stage("save")
        started = time.perf_counter()
        if work_file.exists():
            work_file.unlink()
        if result["kind"] == "jww":
            document.save(work_file)
        else:
            with open(work_file, "xb") as stream:
                stream.write(document.to_bytes())
        result["timings"]["save"] = round(time.perf_counter() - started, 4)
        saved = work_file.read_bytes()
        identical = saved == original
        result["save"] = dict(identical=identical, saved_size=len(saved),
                              size_difference=len(saved) - len(original),
                              first_difference_offset=None if identical else _first_difference(original, saved))
        result["stages_completed"].append("save")

        current = "reload"
        stage("reload")
        started = time.perf_counter()
        if result["kind"] == "jww":
            from jwwkit import CadDocument
            reloaded_counts = _counts_jww(CadDocument.open(work_file))
        else:
            from jwwkit.cad_model import JwsDocument
            reloaded_counts = _counts_jws(JwsDocument.open(work_file))
        result["timings"]["reload"] = round(time.perf_counter() - started, 4)
        result["reload"] = _compare_counts(counts, reloaded_counts)
        result["stages_completed"].append("reload")
        result["status"] = "ok"
    except Exception as exc:  # noqa: BLE001 - 1件の失敗は記録して次へ進むため
        name = type(exc).__name__
        if isinstance(exc, OSError):
            result["status"] = "io_error"  # ファイルの読み書きの問題。ライブラリの問題と分ける
        else:
            result["status"] = "rejected" if is_rejection(exc) else "unexpected"
        message = scrub_paths(str(exc), [source, work_file])
        result["error"] = dict(stage=current, exception=name,
                               category=error_category(name, message),
                               module=type(exc).__module__,
                               frames=code_frames(exc),
                               message=message)
    stage("hash_after")
    try:
        result["sha256_after"] = sha256_file(source)
    except OSError:
        result["sha256_after"] = None
    before = result.get("sha256_before")
    # 調べる前に読めなかったときは、変わったかどうかを判定できない（None）
    result["original_unchanged"] = None if before is None else result["sha256_after"] == before
    return result


def worker_main(argv: list[str]) -> int:
    source, work_file, stage_file, result_file = map(Path, argv)
    started = time.perf_counter()
    result = inspect_one(source, work_file, stage_file)
    result["timings"]["total_in_worker"] = round(time.perf_counter() - started, 4)
    write_json_atomic(result_file, result)
    return 0


# ---------------------------------------------------------------------------
# 図面を探して、伏せた名前を付ける

def scan_sources(sources: list[Path], output: Path, log=lambda *_: None) -> tuple[list[dict], list[dict]]:
    """拡張子 .jww/.jws の図面を探し、SHA256 が同じものをまとめる。"""
    found: list[tuple[int, str, Path]] = []
    scan_errors: list[dict] = []
    for index, root in enumerate(sources):
        def onerror(error, root_index=index):
            scan_errors.append(dict(source_index=root_index, path=str(getattr(error, "filename", "")),
                                    exception=type(error).__name__))
        for folder, dirnames, filenames in os.walk(root, onerror=onerror, followlinks=False):
            folder_path = Path(folder)
            if is_within(folder_path.resolve(), output):
                dirnames[:] = []
                continue
            dirnames.sort(key=lambda s: (s.casefold(), s))
            for filename in filenames:
                path = folder_path / filename
                # is_file() は長いパスで黙って False になり得るので使わない（読めなければ scan_errors に残す）
                if path.suffix.lower() in EXTENSIONS:
                    found.append((index, path.relative_to(root).as_posix(), path))
    found.sort(key=lambda row: (row[0], row[1].casefold(), row[1]))
    groups: dict[str, dict] = {}
    log(f"対象の拡張子のファイル {len(found)} 件の SHA256 を計ります")
    for position, (index, relative, path) in enumerate(found, 1):
        if position % 200 == 0:
            log(f"  SHA256 {position}/{len(found)}")
        try:
            digest = sha256_file(path)
            size = path.stat().st_size
        except OSError as exc:
            scan_errors.append(dict(source_index=index, path=str(path), exception=type(exc).__name__))
            continue
        entry = groups.get(digest)
        if entry is None:
            entry = groups[digest] = dict(sha256=digest, size=size, kind=path.suffix.lower().lstrip("."),
                                          paths=[])
        entry["paths"].append(str(path))
    items = list(groups.values())
    width = max(3, len(str(len(items))))
    for number, entry in enumerate(items, 1):
        entry["name"] = f"図面{number:0{width}d}"
    return items, scan_errors


def choose_sample(items: list[dict], count: int) -> list[str]:
    """全体から等間隔に選ぶ（同じフォルダに偏らないように）。"""
    if count <= 0 or count >= len(items):
        return [item["name"] for item in items]
    step = len(items) / count
    return [items[int(i * step)]["name"] for i in range(count)]


# ---------------------------------------------------------------------------
# 1件を子プロセスで調べる

def run_attempt(item: dict, output: Path, timeout: float) -> dict:
    work = output / WORK_DIR
    name = item["name"]
    work_file = work / f"{name}.{item['kind']}"
    stage_file = work / f"{name}.stage"
    result_file = work / f"{name}.worker.json"
    for path in (stage_file, result_file):
        if path.exists():
            path.unlink()
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "--worker",
               item["paths"][0], str(work_file), str(stage_file), str(result_file)]
    started = time.perf_counter()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        completed = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, timeout=timeout, env=env)
        elapsed = time.perf_counter() - started
        if completed.returncode == 0 and result_file.exists():
            result = json.loads(result_file.read_text(encoding="utf-8"))
        else:
            tail = completed.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
            last = scrub_paths(tail[0], [*item["paths"], work_file])
            exception = last.split(":", 1)[0] if ":" in last else "ChildProcessError"
            result = dict(status="crashed", kind=item["kind"],
                          error=dict(stage=_read_stage(stage_file), exception=exception,
                                     category=error_category(exception, last.split(":", 1)[-1]),
                                     returncode=completed.returncode, message=last))
    except subprocess.TimeoutExpired:
        elapsed = time.perf_counter() - started
        result = dict(status="timeout", kind=item["kind"], timeout_stage=_read_stage(stage_file))
    if "declared_version" not in result:
        result["declared_version"] = declared_version_of_file(item["paths"][0])
    result["timeout_seconds"] = timeout
    result["elapsed_seconds"] = round(elapsed, 3)
    for path in (stage_file, result_file):
        if path.exists():
            path.unlink()
    keep = result.get("status") == "ok" and not (result["save"]["identical"] and result["reload"]["same"])
    if work_file.exists() and not keep:
        work_file.unlink()
    result["kept_work_file"] = keep and work_file.exists()
    return result


def _read_stage(stage_file: Path) -> str | None:
    try:
        return stage_file.read_text(encoding="utf-8")
    except OSError:
        return None


def check_item(item: dict, output: Path, timeout: float) -> dict:
    attempt = run_attempt(item, output, timeout)
    record = dict(name=item["name"], kind=item["kind"], sha256=item["sha256"], size=item["size"],
                  copies=len(item["paths"]), attempts=[_attempt_brief(attempt)], **_final_fields(attempt))
    return record


def retry_item(record: dict, item: dict, output: Path, timeout: float) -> dict:
    attempt = run_attempt(item, output, timeout)
    record = dict(record)
    record["attempts"] = record["attempts"] + [_attempt_brief(attempt)]
    for key in list(record):
        if key not in ("name", "kind", "sha256", "size", "copies", "attempts"):
            del record[key]
    record.update(_final_fields(attempt))
    return record


def _attempt_brief(attempt: dict) -> dict:
    return dict(timeout_seconds=attempt["timeout_seconds"], status=attempt["status"],
                elapsed_seconds=attempt["elapsed_seconds"], timeout_stage=attempt.get("timeout_stage"))


_RECORD_KEYS = ("name", "kind", "sha256", "size", "copies", "attempts")


def _final_fields(attempt: dict) -> dict:
    return {k: v for k, v in attempt.items()
            if k not in ("timeout_seconds", "elapsed_seconds", *_RECORD_KEYS)}


# ---------------------------------------------------------------------------
# 集計

def _ratio(part: int, whole: int) -> str:
    return f"{part}/{whole}（{part / whole * 100:.1f}%）" if whole else f"{part}/0"


def _names(names: list[str], limit: int = 20) -> str:
    shown = "、".join(names[:limit])
    return shown + (f" ほか{len(names) - limit}件" if len(names) > limit else "")


def _opened(r: dict) -> bool:
    """読めたか。開いた後の段階で時間切れになったものも含める。"""
    return ("open" in r.get("stages_completed", [])
            or (r["status"] == "timeout" and r.get("timeout_stage") in ("save", "reload", "hash_after")))


def build_summary(mapping: dict, records: dict[str, dict], unchanged_check: dict | None,
                  interrupted: bool = False) -> str:
    items = [i for i in mapping["items"] if i["name"] in mapping["selected"]]
    found = sum(len(i["paths"]) for i in mapping["items"])
    done = [records[i["name"]] for i in items if i["name"] in records]
    lines = ["# jwwkit 一括確認の集計", "",
             f"- 作成: {datetime.datetime.now().isoformat(timespec='seconds')}",
             f"- jwwkit: {mapping['environment']['jwwkit']['version']}、Python {mapping['environment']['python']}",
             f"- 時間の上限: {mapping['settings']['timeout']} 秒（やり直し {mapping['settings']['retry_timeout']} 秒）",
             "- 図面の名前は伏せています（対応表は出力フォルダの中だけ）。",
             *(["- **途中で中断しました。--resume で続きから再開できます。**"] if interrupted else []), "",
             "## 件数", "",
             f"- 見つけた図面: {found} 件（.jww {sum(len(i['paths']) for i in mapping['items'] if i['kind'] == 'jww')}、"
             f".jws {sum(len(i['paths']) for i in mapping['items'] if i['kind'] == 'jws')}）",
             f"- 中身が異なる図面: {len(mapping['items'])} 件",
             f"- 今回の対象: {len(items)} 件" + ("（抜き出し）" if len(items) != len(mapping["items"]) else ""),
             f"- 調べ終わった: {len(done)} 件",
             f"- 探すときに読めなかったファイル・フォルダ: {len(mapping.get('scan_errors', []))} 件", ""]

    def kind_rows(title: str, selector) -> None:
        lines.extend([f"## {title}", "", "| | JWW | JWS | 計 |", "|---|---:|---:|---:|"])
        for label, test in selector:
            values = [sum(1 for r in done if r["kind"] == k and test(r)) for k in ("jww", "jws")]
            lines.append(f"| {label} | {values[0]} | {values[1]} | {sum(values)} |")
        lines.append("")

    ok = [r for r in done if r["status"] == "ok"]
    kind_rows("結果の内訳", [
        ("読めた", _opened),
        ("拒否", lambda r: r["status"] == "rejected"),
        ("予想外の例外", lambda r: r["status"] == "unexpected"),
        ("時間切れ（最終）", lambda r: r["status"] == "timeout"),
        ("子プロセスの異常終了", lambda r: r["status"] == "crashed"),
        ("ファイルの読み書きの問題", lambda r: r["status"] == "io_error"),
        ("道具自身の問題", lambda r: r["status"] == "tool_error"),
        ("全段階を完了", lambda r: r["status"] == "ok"),
        ("無編集保存がバイト一致", lambda r: r["status"] == "ok" and r["save"]["identical"]),
        ("読み直しで数が同じ", lambda r: r["status"] == "ok" and r["reload"]["same"]),
    ])

    opened = [r for r in done if _opened(r)]
    lines.extend(["## 割合", "",
                  f"- 読めた割合: {_ratio(len(opened), len(done))}",
                  f"- 無編集保存が一致した割合（読めたもののうち）: "
                  f"{_ratio(sum(1 for r in ok if r['save']['identical']), len(opened))}",
                  f"- 読み直して数が変わらなかった割合（読めたもののうち）: "
                  f"{_ratio(sum(1 for r in ok if r['reload']['same']), len(opened))}", ""])

    def version_of(r: dict):
        return r.get("version", r.get("declared_version"))

    versions = collections.Counter((r["kind"], version_of(r)) for r in done)
    lines.extend(["## 版ごとの内訳", "",
                  "読めなかったものは、ファイルの先頭に書かれた版で数えています（不明は None）。", "",
                  "| 種類 | 版 | 件数 | 読めた | 拒否 | 保存一致 |", "|---|---:|---:|---:|---:|---:|"])
    for (kind, version), count in sorted(versions.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        rows = [r for r in done if r["kind"] == kind and version_of(r) == version]
        lines.append(f"| {kind.upper()} | {version} | {count} | {sum(1 for r in rows if _opened(r))} | "
                     f"{sum(1 for r in rows if r['status'] == 'rejected')} | "
                     f"{sum(1 for r in rows if r['status'] == 'ok' and r['save']['identical'])} |")
    lines.append("")

    def category_table(title: str, status: str) -> None:
        rows = [r for r in done if r["status"] == status]
        lines.extend([f"## {title}（{len(rows)} 件）", ""])
        if not rows:
            lines.extend(["なし", ""])
            return
        groups: dict[tuple, list[str]] = collections.defaultdict(list)
        for r in rows:
            e = r.get("error", {})
            groups[(e.get("stage"), e.get("category"))].append(r["name"])
        lines.extend(["| 件数 | 段階 | 種類 | 図面 |", "|---:|---|---|---|"])
        for (stage, category), names in sorted(groups.items(), key=lambda kv: (-len(kv[1]), str(kv[0]))):
            cell = str(category).replace("|", "\\|")
            lines.append(f"| {len(names)} | {stage} | {cell} | {_names(names, 10)} |")
        lines.append("")

    category_table("拒否の理由別", "rejected")
    category_table("予想外の例外", "unexpected")
    category_table("子プロセスの異常終了", "crashed")
    category_table("ファイルの読み書きの問題", "io_error")
    category_table("道具自身の問題", "tool_error")

    first_timeouts = [r for r in done if r["attempts"][0]["status"] == "timeout"]
    retried = [r for r in first_timeouts if len(r["attempts"]) > 1]
    recovered = [r for r in retried if r["attempts"][-1]["status"] != "timeout"]
    still = [r for r in retried if r["attempts"][-1]["status"] == "timeout"]
    waiting = [r for r in first_timeouts if len(r["attempts"]) == 1]
    lines.extend([f"## 時間切れ", "",
                  f"- {mapping['settings']['timeout']} 秒で時間切れ: {len(first_timeouts)} 件",
                  f"  - やり直しで完了: {len(recovered)} 件 {_names([r['name'] for r in recovered])}",
                  *([f"    - 完了後の結果: " + "、".join(f"{k} {v}件" for k, v in sorted(
                      collections.Counter(r["status"] for r in recovered).items()))] if recovered else []),
                  f"  - なお時間切れ: {len(still)} 件 {_names([r['name'] for r in still])}",
                  f"  - やり直し前: {len(waiting)} 件", ""])
    stages = collections.Counter(r.get("timeout_stage") for r in done if r["status"] == "timeout")
    if stages:
        lines.extend(["最終的な時間切れの段階: " + "、".join(f"{k} {v}件" for k, v in stages.items()), ""])

    mismatched = [r for r in ok if not r["save"]["identical"]]
    lines.extend([f"## 無編集保存が一致しなかった図面（{len(mismatched)} 件）", ""])
    if mismatched:
        lines.extend(["| 図面 | 版 | 大きさの差 | 最初に違う位置 |", "|---|---:|---:|---:|"])
        for r in mismatched:
            lines.append(f"| {r['name']} | {r.get('version')} | {r['save']['size_difference']} | "
                         f"{r['save']['first_difference_offset']} |")
    else:
        lines.append("なし")
    lines.append("")
    reload_diff = [r for r in ok if not r["reload"]["same"]]
    lines.extend([f"## 読み直しで数が変わった図面（{len(reload_diff)} 件）", ""])
    lines.append(_names([f"{r['name']}（{'、'.join(r['reload']['differences'])}）" for r in reload_diff])
                 if reload_diff else "なし")
    lines.append("")

    timed = [r for r in done if r["status"] not in ("timeout", "tool_error")]
    durations = [r["attempts"][-1]["elapsed_seconds"] for r in timed]
    lines.extend(["## かかった時間（1件あたり、子プロセスの起動を含む）", ""])
    if durations:
        slowest = sorted(((r["attempts"][-1]["elapsed_seconds"], r["name"]) for r in timed), reverse=True)[:5]
        lines.extend([f"- 中央値: {statistics.median(durations):.2f} 秒、最大: {max(durations):.2f} 秒",
                      "- 長くかかった図面: " + "、".join(f"{n}（{s:.1f} 秒）" for s, n in slowest)])
    lines.append("")

    types = collections.Counter()
    for r in opened:
        types.update(r.get("counts", {}).get("by_type", {}))
    lines.extend(["## 要素の種類ごとの数（読めたもの全体の合計）", ""])
    lines.append("、".join(f"{k} {v}" for k, v in sorted(types.items(), key=lambda kv: -kv[1])) or "なし")
    lines.append("")

    changed = [r["name"] for r in done if r.get("original_unchanged") is False]
    lines.extend(["## 原本が変わっていないことの確認", "",
                  f"- 1件ごとの確認（調べる前後）で変わった図面: {len(changed)} 件 {_names(changed)}"])
    if unchanged_check is not None:
        lines.append(f"- 最後に全ファイル（写しを含む {unchanged_check['checked']} 件）の SHA256 を計り直した結果、"
                     f"変わっていたもの: {unchanged_check['changed']} 件、読めなかったもの: {unchanged_check['missing']} 件")
    else:
        lines.append("- 全ファイルの計り直し: 未実施（途中で中断）")
    lines.append("")
    return "\n".join(lines)


def verify_all_unchanged(mapping: dict) -> dict:
    checked = changed = missing = 0
    for item in mapping["items"]:
        for path in item["paths"]:
            checked += 1
            try:
                if sha256_file(Path(path)) != item["sha256"]:
                    changed += 1
            except OSError:
                missing += 1
    return dict(checked=checked, changed=changed, missing=missing)


# ---------------------------------------------------------------------------
# 全体の流れ

def prepare_output(sources: list[Path], output: Path, resume: bool) -> None:
    for source in sources:
        if not source.is_dir():
            raise UsageError("図面のフォルダが見つかりません（--source の指定を確かめてください）")
        if is_within(output, source):
            raise UsageError("出力フォルダが図面のフォルダの中にあります。図面のフォルダには書き込みません")
        if is_within(source, output):
            raise UsageError("図面のフォルダが出力フォルダの中にあります")
    if is_within(output, REPO_ROOT):
        raise UsageError("出力フォルダがリポジトリの中にあります。リポジトリの外を指定してください")
    if resume:
        if not (output / MAPPING_NAME).is_file():
            raise UsageError("--resume の出力フォルダに、前回の対応表がありません")
        return
    if output.exists() and any(output.iterdir()):
        raise UsageError("出力フォルダが空ではありません。新しいフォルダを指定するか、--resume で再開してください")


def run(args: argparse.Namespace, log=print) -> dict:
    sources = [Path(s).resolve() for s in args.source]
    output = Path(args.output).resolve()
    prepare_output(sources, output, args.resume)
    results_dir = output / RESULTS_DIR
    if args.resume:
        mapping = json.loads((output / MAPPING_NAME).read_text(encoding="utf-8"))
        if mapping.get("tool_version") != TOOL_VERSION:
            raise UsageError("前回とこの道具の版が違うため再開できません。新しい出力フォルダで始めてください")
        if [str(s) for s in sources] != mapping["sources"]:
            raise UsageError("--resume の図面フォルダが前回と違います")
        settings = mapping["settings"]
        for key, value in (("timeout", args.timeout), ("retry_timeout", args.retry_timeout),
                           ("sample", args.sample)):
            if value is not None and value != settings[key]:
                raise UsageError(f"--resume では前回の設定（{key}={settings[key]}）を使います。"
                                 "設定を変えるときは新しい出力フォルダで始めてください")
        log(f"再開します: 対象 {len(mapping['selected'])} 件")
    else:
        output.mkdir(parents=True, exist_ok=True)
        log("図面を探して SHA256 を計っています…")
        items, scan_errors = scan_sources(sources, output, log)
        settings = dict(timeout=120.0 if args.timeout is None else args.timeout,
                        retry_timeout=600.0 if args.retry_timeout is None else args.retry_timeout,
                        sample=0 if args.sample is None else args.sample)
        mapping = dict(tool_version=TOOL_VERSION, created=datetime.datetime.now().isoformat(timespec="seconds"),
                       sources=[str(s) for s in sources], settings=settings,
                       environment=dict(jwwkit=jwwkit_info(), python=sys.version.split()[0]),
                       items=items, selected=choose_sample(items, settings["sample"]), scan_errors=scan_errors)
        write_json_atomic(output / MAPPING_NAME, mapping)
        log(f"見つけた図面 {sum(len(i['paths']) for i in items)} 件、中身が異なるもの {len(items)} 件、"
            f"今回の対象 {len(mapping['selected'])} 件")
    if mapping["environment"]["jwwkit"] != jwwkit_info():
        raise UsageError("前回と jwwkit の版または場所が違うため再開できません")
    info = mapping["environment"]["jwwkit"]
    log(f"調べる jwwkit: 版 {info['version']}、場所 {info['location']}")
    results_dir.mkdir(exist_ok=True)
    (output / WORK_DIR).mkdir(exist_ok=True)
    by_name = {i["name"]: i for i in mapping["items"]}
    selected = [by_name[n] for n in mapping["selected"]]

    def load(name: str) -> dict | None:
        path = results_dir / f"{name}.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save(record: dict) -> None:
        write_json_atomic(results_dir / f"{record['name']}.json", record)

    records = {n: r for n in mapping["selected"] if (r := load(n)) is not None}
    pending = [i for i in selected if i["name"] not in records]
    log(f"調べ終わり {len(records)} 件、これから {len(pending)} 件")
    processed = retried = 0
    interrupted = False
    try:
        processed = _run_parallel(pending, lambda item: check_item(item, output, settings["timeout"]),
                                  save, records, args.jobs, log)
        retry_targets = [by_name[n] for n, r in records.items()
                         if r["status"] == "timeout" and len(r["attempts"]) == 1]
        if settings["retry_timeout"] and retry_targets:
            log(f"時間切れの {len(retry_targets)} 件を、上限 {settings['retry_timeout']} 秒でやり直します")
            retried = _run_parallel(retry_targets,
                                    lambda item: retry_item(records[item["name"]], item, output,
                                                            settings["retry_timeout"]),
                                    save, records, args.jobs, log)
        log("全ファイルの SHA256 を計り直して、原本が変わっていないことを確かめます")
        unchanged = verify_all_unchanged(mapping)
    except KeyboardInterrupt:
        interrupted = True
        unchanged = None
        log("中断しました。調べ終わった分の結果は残っています。--resume で続きから再開できます")
    summary = build_summary(mapping, records, unchanged, interrupted)
    (output / SUMMARY_NAME).write_text(summary + "\n", encoding="utf-8", errors="backslashreplace",
                                       newline="\n")
    try:
        (output / WORK_DIR).rmdir()
    except OSError:
        pass
    if unchanged is not None:
        log(f"集計を書きました: {SUMMARY_NAME}（原本が変わったもの {unchanged['changed']} 件）")
    else:
        log(f"途中までの集計を書きました: {SUMMARY_NAME}")
    return dict(processed=processed, retried=retried, records=records, unchanged=unchanged, output=output,
                interrupted=interrupted)


def _run_parallel(items, function, save, records, jobs, log) -> int:
    count = 0
    total = len(items)
    def guarded(item):
        try:
            return function(item)
        except Exception as exc:  # noqa: BLE001 - 道具自身の問題でも1件として記録し、次へ進む
            message = scrub_paths(str(exc), item["paths"])
            previous = records.get(item["name"], {}).get("attempts", [])
            return dict(name=item["name"], kind=item["kind"], sha256=item["sha256"], size=item["size"],
                        copies=len(item["paths"]),
                        attempts=[*previous, dict(timeout_seconds=None, status="tool_error",
                                                  elapsed_seconds=0.0, timeout_stage=None)],
                        status="tool_error", declared_version=declared_version_of_file(item["paths"][0]),
                        error=dict(stage="tool", exception=type(exc).__name__,
                                   category=error_category(type(exc).__name__, message),
                                   frames=code_frames(exc), message=message))

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs))
    try:
        futures = {pool.submit(guarded, item): item for item in items}
        for future in concurrent.futures.as_completed(futures):
            record = future.result()
            save(record)
            records[record["name"]] = record
            count += 1
            log(f"[{count}/{total}] {record['name']} {record['status']}")
    finally:
        # 中断されたら、まだ始めていない図面は取り消す（実行中の1件は打ち切りか終了を待つ）
        pool.shutdown(wait=True, cancel_futures=True)
    return count


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", action="append", required=True, help="図面のフォルダ（複数指定可）")
    parser.add_argument("--output", required=True, help="出力フォルダ（リポジトリの外）")
    parser.add_argument("--timeout", type=float, default=None, help="1件あたりの時間の上限（秒、既定120）")
    parser.add_argument("--retry-timeout", type=float, default=None,
                        help="時間切れのものをやり直すときの上限（秒、既定600、0でやり直さない）")
    parser.add_argument("--jobs", type=int, default=1,
                        help="同時に調べる件数（既定1。増やすと1件あたりの時間が長く出ることがある）")
    parser.add_argument("--sample", type=int, default=None, help="全体から等間隔に選ぶ件数（既定0で全件）")
    parser.add_argument("--resume", action="store_true", help="中断した出力フォルダの続きから再開する")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--worker"]:
        return worker_main(argv[1:])
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        result = run(parse_args(argv))
    except UsageError as exc:
        print(f"中止: {exc}", file=sys.stderr)
        return 2
    return 130 if result["interrupted"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
