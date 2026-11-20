"""Sort the JWW drawings in a folder by whether jwwkit can edit them, and write one CSV list into the folder.

The drawings are only read. The only file written is the list (UTF-8 with BOM, for Excel); an existing file
of the same name is never overwritten. The list holds places, names, sizes, versions and reasons only, never
the text inside the drawings.
"""
import csv
import datetime
import gc
import hashlib
import os
import re
import stat
import struct
from pathlib import Path

LARGE_BYTES = 50 * 1024 * 1024
EDITABLE = "編集できる"
READ_ONLY = "読取り専用"
EXPLICIT = "明示の読み方が要る"
REJECTED = "拒否"
UNEXPECTED = "拒否（予想外）"
KINDS = (EDITABLE, READ_ONLY, EXPLICIT, REJECTED, UNEXPECTED)
COLUMNS = ("相対の場所", "ファイル名", "大きさ（バイト）", "ファイルの版", "分け方", "理由の種類", "拒否の文", "備考")
MESSAGE_LIMIT = 300

# (part of jwwkit's rejection message, reason in plain Japanese). The first match wins.
REASONS = (
    ("rebro_schema0", "他のCADの出力で、扱えない形（クラスの版0）"),
    ("Unsupported class schema", "クラスの版が受け付けない値"),
    ("noncanonical", "要素の個数が普通と違う書き方"),
    ("Extended sequence count unobserved", "要素の個数の大きい書き方が、確かめていない組み合わせ"),
    ("Block definitions exceed", "ブロック定義が1万個を超える"),
    ("point style", "点の線種が確かめていない値"),
    ("Unobserved point form", "点の形が確かめていない形"),
    ("Unobserved solid form", "ソリッドの形が確かめていない形"),
    ("codec can't decode", "文字のコードが正しくない"),
    ("Unsupported JWW version", "対象外の版"),
    ("Invalid JWW signature", "JWWの印がない（JWWでない可能性）"),
    ("Truncated record", "ファイルが途中で切れている（空のファイルを含む）"),
    ("embedded image", "同梱の画像の形が確かめていない形か、壊れている"),
    ("Unsupported class", "対象外の要素の種類"),
    ("ezjww", "標準の読み取り（ezjww）と照合できない"),
    ("Native", "標準の読み取り（ezjww）と照合できない"),
)


def add_arguments(parser):
    parser.add_argument("folder", type=Path, help="調べるフォルダ")
    parser.add_argument("--no-recursive", action="store_true", help="下のフォルダを調べない")
    parser.add_argument("--output", type=Path, help="一覧のファイル（既定：フォルダの中の jwwkit_check_日時.csv）")
    parser.add_argument("--only-problems", action="store_true", help="編集できる図面を一覧から外す")


def default_output(folder, now=None):
    return Path(folder) / f"jwwkit_check_{(now or datetime.datetime.now()).strftime('%Y%m%d_%H%M')}.csv"


_LINK_TAGS = {getattr(stat, "IO_REPARSE_TAG_SYMLINK", 0xA000000C), getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)}


def _is_folder_link(entry):
    """A folder that is a symbolic link or a junction (not followed). Other reparse points (cloud files and the
    like) are ordinary folders and files here."""
    if entry.is_symlink():
        return True
    try:
        return getattr(entry.stat(follow_symlinks=False), "st_reparse_tag", 0) in _LINK_TAGS
    except OSError:
        return False


def find_drawings(folder, *, recursive=True, exclude=()):
    """.jww files (any case) under folder, sorted by relative place. Folder links and junctions are not followed;
    a .jww file is listed whatever it is (a link to a file is read like the file).

    Returns (paths, unreadable_folders, skipped_folder_links)."""
    folder = Path(folder)
    excluded = {os.path.normcase(os.path.abspath(p)) for p in exclude}
    found, unreadable, links = [], 0, 0
    pending = [folder]
    while pending:
        current = pending.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            unreadable += 1
            continue
        for entry in entries:
            try:
                if entry.is_dir():
                    if _is_folder_link(entry):
                        links += 1
                    elif recursive:
                        pending.append(Path(entry.path))
                elif (entry.name.lower().endswith(".jww")
                      and os.path.normcase(os.path.abspath(entry.path)) not in excluded):
                    found.append(Path(entry.path))
            except OSError:
                unreadable += 1
    found.sort(key=lambda p: [part.casefold() for part in p.relative_to(folder).parts])
    return found, unreadable, links


def file_version(path):
    """The version word at the start of a JWW file, or None (read even when the drawing cannot be opened)."""
    try:
        with open(path, "rb") as stream:
            head = stream.read(12)
    except OSError:
        return None
    if head[:8] == b"JwwData." and len(head) == 12:
        return struct.unpack_from("<I", head, 8)[0]
    return None


def _scrub(message, path):
    """Hide full places (the drawing's and any other) in a message, and keep it short. The rest of the message,
    numbers and words included, is kept as jwwkit wrote it (the name is in its own column anyway)."""
    text = " ".join(str(message or "").split())
    path = Path(path)
    for variant in sorted({str(path), path.as_posix(), str(path).replace("\\", "\\\\"),
                           str(path.absolute())}, key=len, reverse=True):
        text = text.replace(variant, "<場所>")
    text = re.sub(r"[A-Za-z]:[\\/][^\s;,)'\"]*|\\\\[^\s;,)'\"]+", "<場所>", text)
    return text if len(text) <= MESSAGE_LIMIT else text[:MESSAGE_LIMIT] + "…"


def reason_of(message):
    for part, reason in REASONS:
        if part.lower() in message.lower():
            return reason
    return "その他の拒否"


def _fingerprint(path):
    info = os.stat(path)
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return info.st_size, info.st_mtime_ns, digest.hexdigest()


def _is_rejection(exc):
    """jwwkit's own refusals are ValueError (RecordError is one); character-code errors are not counted as such."""
    return isinstance(exc, ValueError) and not isinstance(exc, UnicodeError)


def classify(path):
    """Sort one drawing. Returns dict(kind, reason, message, note list). The drawing is only read."""
    from jwwkit import CadDocument
    result = dict(kind=None, reason="", message="", notes=[])
    try:
        before = _fingerprint(path)
    except OSError as exc:
        result.update(kind=UNEXPECTED, reason="ファイルを読めない", message=_scrub(f"{type(exc).__name__}: {exc}", path))
        return result
    if before[0] > LARGE_BYTES:
        result["notes"].append("50MBを超える図面")
    failure = None
    try:
        document = CadDocument.open(path)
        version = document.version
        del document
        if version in (600, 700):
            result["kind"] = EDITABLE
        else:
            result.update(kind=READ_ONLY, reason="古い版（Jw_cadでVer.7.00形式に保存し直せば編集できる）")
    except Exception as exc:  # noqa: BLE001 - every failure is written to the list, then the next drawing
        # Keep only the text: the exception (and what it holds of the drawing) is let go before reading again.
        failure = (_is_rejection(exc), type(exc).__name__, str(exc))
    finally:
        gc.collect()  # hand the drawing back before the next one (#29)
    if failure is not None:
        rejection, name, text = failure
        if rejection:
            explicit = _explicit_reading(path, text)
            if explicit:
                result.update(kind=EXPLICIT, reason=explicit, message=_scrub(text, path))
            else:
                result.update(kind=REJECTED, reason=reason_of(text), message=_scrub(text, path))
        else:
            result.update(kind=UNEXPECTED, reason="予想外の例外", message=_scrub(f"{name}: {text}", path))
    try:
        after = _fingerprint(path)
    except OSError:
        after = None
    if after != before:
        result["notes"].append("調べている途中でファイルが変わった")
    return result


def _explicit_reading(path, message):
    """For a strict refusal: can the explicit rebro_schema0 profile or the schema normalization handle it?"""
    from jwwkit import CadDocument
    from jwwkit.normalization import inspect_schema_normalization
    ways = []
    if "Unsupported class schema" in message:
        try:
            document = CadDocument.open(path, schema_profile="rebro_schema0")
            del document
            ways.append('schema_profile="rebro_schema0"で開ける')
        except Exception:  # noqa: BLE001 - not readable this way either
            pass
        finally:
            gc.collect()
    try:
        if inspect_schema_normalization(path).get("status") == "normalize":
            ways.append("正規化で標準の形にできる")
    except Exception:  # noqa: BLE001 - the inspection itself failing means: not this way
        pass
    finally:
        gc.collect()
    return "他のCADの出力（" + "、".join(ways) + "）" if ways else ""


def check_folder(folder, *, recursive=True, output=None, only_problems=False, log=print):
    """Sort every drawing and write the list. Returns (exit code, counts by kind, output path)."""
    folder = Path(folder)
    if not folder.is_dir():
        log(f"フォルダが見つかりません：{folder}")
        return 2, {}, None
    output = Path(output) if output else default_output(folder)
    if output.suffix.lower() == ".jww":
        log(f"一覧の名前に .jww は使えません（図面と取り違えるため）。止めます（図面は開いていません）：{output}")
        return 2, {}, output
    try:
        stream = open(output, "x", encoding="utf-8-sig", newline="")
    except FileExistsError:
        log(f"同じ名前の一覧がすでにあるので、止めます（図面は開いていません）：{output}")
        return 2, {}, output
    except OSError as exc:
        log(f"一覧のファイルを作れないので、止めます（図面は開いていません。{type(exc).__name__}）：{output}")
        return 2, {}, output
    counts = dict.fromkeys(KINDS, 0)
    with stream:
        writer = csv.writer(stream)
        writer.writerow(COLUMNS)
        stream.flush()
        paths, unreadable, links = find_drawings(folder, recursive=recursive, exclude=[output])
        large = 0
        log(f"図面 {len(paths)} 件を調べます。")
        for number, path in enumerate(paths, 1):
            try:
                size = path.stat().st_size
            except OSError:
                size = None
            if size is not None and size > LARGE_BYTES:
                large += 1
                log(f"  {number} 件目は50MBを超える図面です（{size / 2**20:.0f} MB）。開くのに時間とメモリがかかります。")
            result = classify(path)
            counts[result["kind"]] += 1
            if only_problems and result["kind"] == EDITABLE:
                continue
            relative = path.parent.relative_to(folder).as_posix()
            writer.writerow((relative if relative != "." else "", path.name, "" if size is None else size,
                             file_version(path) or "", result["kind"], result["reason"], result["message"],
                             "、".join(result["notes"])))
            stream.flush()
    log("分けごとの件数：")
    for kind in KINDS:
        log(f"  {kind}：{counts[kind]} 件")
    if large:
        log(f"50MBを超える図面：{large} 件")
    if unreadable:
        log(f"読めなかったフォルダ・項目：{unreadable} 件")
    if links:
        log(f"たどらなかったフォルダのリンク・ジャンクション：{links} 件")
    log(f"一覧：{output}")
    return 0, counts, output


def run(args):
    import sys
    for stream in (sys.stdout, sys.stderr):
        # A console that cannot show Japanese must not stop the check halfway (the list is already open).
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    code, _counts, _output = check_folder(args.folder, recursive=not args.no_recursive, output=args.output,
                                          only_problems=args.only_problems)
    return code
