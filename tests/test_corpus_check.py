"""tools/corpus_check.py の試験。合成の図面だけを使い、非公開の資料は使わない。"""
import hashlib
import importlib.util
import json
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

from jwwkit.line_document import JwwDocument, Line
from jwwkit.reader.jws import JWS700_RESERVED
from jwwkit.writer.mfc import records_bytes

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "corpus_check.py"
SECRET = "秘密の案件名"


def load_tool():
    spec = importlib.util.spec_from_file_location("corpus_check", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


corpus_check = load_tool()


def synthetic_jws() -> bytes:
    header = (b"JwsData." + b"." * 192 + struct.pack("<I2d16d", 700, 0, 0, *([50.0] * 16))
              + JWS700_RESERVED + struct.pack("<4d", 0, 0, 4, 4))
    registry = dict(classes={}, next_index=1)
    data = header + records_bytes([Line((0, 0), (4, 0), layer=3).record(),
                                   Line((4, 0), (4, 4), layer=5, color=4).record()], registry)
    return data + records_bytes([], registry)


def tree_snapshot(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


class CorpusCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="corpus-check-test-"))
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        self.source = self.temp / "図面"
        (self.source / SECRET / "下").mkdir(parents=True)
        drawing = JwwDocument()
        drawing.add_line((0, 0), (10, 0), layer=1)
        drawing.add_line((10, 0), (10, 10), layer=2)
        first = self.source / SECRET / f"{SECRET}_平面図.jww"
        drawing.save(first)
        # 同じ中身の写しと、拡張子が大文字のもの
        shutil.copyfile(first, self.source / SECRET / "下" / f"{SECRET}_写し.JWW")
        (self.source / f"{SECRET}_記号.jws").write_bytes(synthetic_jws())
        (self.source / f"{SECRET}_壊れた.jww").write_bytes(b"not a drawing" * 10)
        # 対象外（自動保存やバックアップ）
        (self.source / f"{SECRET}.jw$").write_bytes(b"x")
        (self.source / f"{SECRET}.bak").write_bytes(b"x")
        self.output = self.temp / "出力"
        self.before = tree_snapshot(self.source)

    def run_tool(self, *extra, output=None, resume=False, timeout=120.0, retry=600.0, sample=0):
        argv = ["--source", str(self.source), "--output", str(output or self.output),
                "--timeout", str(timeout), "--retry-timeout", str(retry), "--sample", str(sample)]
        if resume:
            argv.append("--resume")
        args = corpus_check.parse_args([*argv, *extra])
        return corpus_check.run(args, log=lambda *_: None)

    def test_checks_every_distinct_drawing_and_continues_after_failure(self):
        result = self.run_tool()
        records = result["records"]
        self.assertEqual(len(records), 3)  # 写しは1件にまとめる
        by_kind = {}
        for record in records.values():
            by_kind.setdefault((record["kind"], record["status"]), []).append(record)
        jww_ok = by_kind[("jww", "ok")][0]
        self.assertEqual(jww_ok["copies"], 2)
        self.assertEqual(jww_ok["counts"]["by_type"], {"LINE": 2})
        self.assertTrue(jww_ok["save"]["identical"])
        self.assertTrue(jww_ok["reload"]["same"])
        jws_ok = by_kind[("jws", "ok")][0]
        self.assertEqual((jws_ok["version"], jws_ok["counts"]["entity_count"]), (700, 2))
        self.assertEqual(jws_ok["declared_version"], 700)
        self.assertEqual(jww_ok["declared_version"], jww_ok["version"])
        self.assertTrue(jws_ok["save"]["identical"])
        broken = by_kind[("jww", "rejected")][0]
        self.assertEqual(broken["error"]["stage"], "open")
        self.assertIsNone(broken["declared_version"])
        self.assertTrue(all(r["original_unchanged"] for r in records.values()))
        self.assertEqual(result["unchanged"], dict(checked=4, changed=0, missing=0))

        summary = (self.output / "summary.md").read_text(encoding="utf-8")
        self.assertIn("見つけた図面: 4 件", summary)
        self.assertIn("中身が異なる図面: 3 件", summary)
        self.assertIn("拒否の理由別（1 件）", summary)
        # 原本は読むだけ。作業用のファイルは一致したら残さない
        self.assertEqual(tree_snapshot(self.source), self.before)
        self.assertFalse((self.output / "work").exists())

    def test_real_names_appear_only_in_mapping(self):
        self.run_tool()
        mapping = json.loads((self.output / "対応表.json").read_text(encoding="utf-8"))
        self.assertTrue(any(SECRET in p for item in mapping["items"] for p in item["paths"]))
        others = [p for p in self.output.rglob("*") if p.is_file() and p.name != "対応表.json"]
        self.assertTrue(others)
        for path in others:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(SECRET, text, path.name)
            self.assertNotIn(str(self.source), text, path.name)
            self.assertNotIn(SECRET, path.name)
        names = sorted(p.stem for p in (self.output / "results").glob("*.json"))
        self.assertEqual(names, ["図面001", "図面002", "図面003"])

    def test_refuses_output_inside_repository_or_source(self):
        inside_repo = ROOT / "corpus-check-should-not-exist"
        for output in (inside_repo, self.source / "出力"):
            with self.subTest(output=output.name):
                with self.assertRaises(corpus_check.UsageError):
                    self.run_tool(output=output)
                self.assertFalse(output.exists())
        self.assertEqual(tree_snapshot(self.source), self.before)

    def test_refuses_non_empty_output_without_resume(self):
        self.output.mkdir()
        (self.output / "前の結果.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(corpus_check.UsageError):
            self.run_tool()

    def test_resume_skips_finished_drawings(self):
        self.run_tool()
        removed = self.output / "results" / "図面002.json"
        kept = self.output / "results" / "図面001.json"
        kept_bytes = kept.read_bytes()
        removed.unlink()
        result = self.run_tool(resume=True)
        self.assertEqual(result["processed"], 1)
        self.assertTrue(removed.exists())
        self.assertEqual(kept.read_bytes(), kept_bytes)

    def test_timeout_then_retry_is_counted_separately(self):
        # Python の起動だけで 0.001 秒を超えるので、最初は必ず時間切れになる
        result = self.run_tool(timeout=0.001, retry=120.0)
        for record in result["records"].values():
            self.assertEqual(record["attempts"][0]["status"], "timeout")
            self.assertEqual(len(record["attempts"]), 2)
            self.assertNotEqual(record["status"], "timeout")
        summary = (self.output / "summary.md").read_text(encoding="utf-8")
        self.assertIn("0.001 秒で時間切れ: 3 件", summary)
        self.assertIn("やり直しで完了: 3 件", summary)

    def test_still_timeout_after_retry(self):
        result = self.run_tool(timeout=0.001, retry=0.001, sample=1)
        record, = result["records"].values()
        self.assertEqual([a["status"] for a in record["attempts"]], ["timeout", "timeout"])
        self.assertEqual(record["declared_version"], 700)
        summary = (self.output / "summary.md").read_text(encoding="utf-8")
        self.assertIn("なお時間切れ: 1 件", summary)
        self.assertEqual(tree_snapshot(self.source), self.before)

    def test_error_category_hides_numbers_paths_and_quotes(self):
        category = corpus_check.error_category(
            "RecordError", "Bad class 'CDataSen' at offset=1234; file C:\\x\\図面.jww 「文字」 2.5")
        self.assertEqual(category, "RecordError: Bad class <…> at offset=N; file <path> <…> N")

    def test_error_category_keeps_identifier_digits(self):
        self.assertEqual(corpus_check.error_category("RecordError", "Unobserved JWS700 pattern in v600 at 12"),
                         "RecordError: Unobserved JWS700 pattern in v600 at N")

    def test_unreadable_drawing_message_has_no_real_path(self):
        self.output.mkdir()
        (self.output / "work").mkdir()
        missing = self.source / SECRET / f"{SECRET}_消えた.jww"
        item = dict(name="図面009", kind="jww", sha256="0" * 64, size=0, paths=[str(missing)])
        record = corpus_check.check_item(item, self.output, 120.0)
        self.assertEqual(record["status"], "io_error")
        self.assertIsNone(record["original_unchanged"])
        text = json.dumps(record, ensure_ascii=False)
        self.assertNotIn(SECRET, text)
        self.assertNotIn(str(self.source), text)
        self.assertIn("<図面>", record["error"]["message"])

    def test_resume_refuses_other_tool_version(self):
        self.run_tool(sample=1)
        mapping_path = self.output / "対応表.json"
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        mapping["tool_version"] = corpus_check.TOOL_VERSION - 1
        mapping_path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(corpus_check.UsageError):
            self.run_tool(resume=True, sample=1)

    def test_resume_refuses_different_settings(self):
        self.run_tool(sample=1)
        with self.assertRaises(corpus_check.UsageError):
            self.run_tool(resume=True, sample=2)
        with self.assertRaises(corpus_check.UsageError):
            self.run_tool(resume=True, sample=1, timeout=5.0)

    def test_scrub_paths_hides_name_stem_and_escaped_forms(self):
        path = Path("C:/案件/" + SECRET + ".jww")
        message = f"open failed: {path!r} ({SECRET}) {str(path).replace(chr(92), chr(92) * 2)}"
        scrubbed = corpus_check.scrub_paths(message, [path])
        self.assertNotIn(SECRET, scrubbed)
        folder_only = corpus_check.scrub_paths(f"{SECRET} unreadable", [Path("C:/x") / SECRET / "a.jww"])
        self.assertNotIn(SECRET, folder_only)

    def test_tool_error_is_recorded_and_run_continues(self):
        original = corpus_check.check_item
        calls = []

        def flaky(item, output, timeout):
            calls.append(item["name"])
            if len(calls) == 1:
                raise PermissionError(f"locked: {item['paths'][0]}")
            return original(item, output, timeout)

        corpus_check.check_item = flaky
        self.addCleanup(setattr, corpus_check, "check_item", original)
        result = self.run_tool()
        statuses = sorted(r["status"] for r in result["records"].values())
        self.assertEqual(len(statuses), 3)
        self.assertIn("tool_error", statuses)
        summary = (self.output / "summary.md").read_text(encoding="utf-8")
        self.assertIn("道具自身の問題（1 件）", summary)
        self.assertNotIn(SECRET, json.dumps(list(result["records"].values()), ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
