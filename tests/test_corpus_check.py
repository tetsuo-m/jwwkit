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
from jwwkit.reader.archive import read_records, read_records_bytes
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


def schema0_jww() -> bytes:
    """Line, circle and text only (the three classes rebro_schema0 has always accepted), declarations set to 0."""
    drawing = JwwDocument()
    drawing.add_line((0, 0), (10, 0))
    drawing.add_circle((5, 5), 2)
    drawing.add_text((0, 10), content="synthetic")
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "drawing.jww"
        drawing.save(path)
        data = bytearray(path.read_bytes())
    for declaration in read_records_bytes(bytes(data))["class_declarations"]:
        struct.pack_into("<H", data, declaration["offset"] + 2, 0)
    return bytes(data)


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
        self.assertEqual((jws_ok["class_schema"], jws_ok["extended_counts"]), (None, dict(present=False, sequences=0)))
        self.assertNotIn("images", jws_ok)
        self.assertNotIn("read_only", jws_ok)
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

    def test_records_images_schema_read_only_and_memory(self):
        fixtures = ROOT / "tests" / "fixtures"
        source = self.temp / "見本"
        source.mkdir()
        shutil.copyfile(fixtures / "jwcad_images" / "a5.jww", source / f"{SECRET}_画像.jww")
        shutil.copyfile(fixtures / "jwcad_saved" / "jwcad10036_save_v351.jww", source / f"{SECRET}_古い版.jww")
        shutil.copyfile(fixtures / "jwcad_saved" / "jwcad10036_save_v600.jww", source / f"{SECRET}_v6.jww")
        output = self.temp / "出力2"
        args = corpus_check.parse_args(["--source", str(source), "--output", str(output), "--sample", "0"])
        records = {r["version"]: r for r in corpus_check.run(args, log=lambda *_: None)["records"].values()}
        image = records[700]
        self.assertEqual(image["images"]["count"], 2)
        self.assertEqual(image["images"]["by_format"], {"BMP": 1, "JPEG": 1})
        self.assertEqual((image["images"]["unverified"], image["images"]["noted"]), (0, 0))
        self.assertEqual(image["images"]["shapes"], {"BMP (40, 24, 0, False)": 1, "JPEG ('SOF0', 8, 3)": 1})
        self.assertEqual((image["class_schema"], image["read_only"]), (700, False))
        self.assertEqual(image["extended_counts"], dict(present=False, sequences=0))
        self.assertEqual((records[351]["read_only"], records[351]["class_schema"]), (True, 700))
        self.assertEqual((records[600]["class_schema"], records[600]["read_only"]), (700, False))
        self.assertTrue(all(isinstance(r["peak_memory_mb"], float) for r in records.values()))
        text = json.dumps(list(records.values()), ensure_ascii=False)
        self.assertNotIn(SECRET, text)
        self.assertNotIn("jwwkit_sample", text)  # image names are not recorded
        summary = (output / "summary.md").read_text(encoding="utf-8")
        self.assertIn("| JWW | 600 | 700 | 1 | 0 |", summary)
        self.assertIn("| JWW | 351 | 700 | 1 | 1 |", summary)
        self.assertIn("読取り専用で開いた図面: 1 件", summary)
        self.assertIn("画像のある図面: 1 件、画像: 2 枚", summary)
        self.assertIn("| BMP (40, 24, 0, False) | 1 |", summary)
        self.assertIn("拡張の書き方（65535 以上）がある図面（0 件）", summary)
        self.assertIn("## メモリの最大", summary)
        self.assertNotIn("jwwkit_sample", summary)

    def test_structure_failure_keeps_the_reading_result(self):
        original = corpus_check._structure

        def broken(document, kind):
            raise KeyError("unexpected record shape")
        corpus_check._structure = broken
        self.addCleanup(setattr, corpus_check, "_structure", original)
        source = ROOT / "tests" / "fixtures" / "jwcad_images" / "a1.jww"
        result = corpus_check.inspect_one(source, self.temp / "a1_work.jww")
        self.assertEqual(result["status"], "ok")
        self.assertIn("open", result["stages_completed"])
        self.assertEqual(result["structure_error"], "KeyError: 'unexpected record shape'")
        self.assertNotIn("class_schema", result)

    def test_extended_counts_are_counted_per_sequence(self):
        class Fake:
            version = 700
            _source_records = dict(entities=[None] * 65535, class_schema=700, schema_profile="strict", images=[],
                                   block_defs=[dict(entities=[None] * 3), dict(entities=[None] * 70000)])
        self.assertEqual(corpus_check._structure(Fake(), "jww")["extended_counts"], dict(present=True, sequences=2))
        Fake._source_records["entities"] = [None] * 65534
        self.assertEqual(corpus_check._structure(Fake(), "jww")["extended_counts"], dict(present=True, sequences=1))

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

    def test_size_filter_splits_the_run_into_two_output_folders(self):
        # Issue #27: small drawings with --jobs 4 and large ones with --jobs 1, in separate folders.
        full = self.run_tool(output=self.temp / "全部")
        sizes = {name: record["size"] for name, record in full["records"].items()}
        limit = sorted(sizes.values())[1]  # at least one drawing on each side
        small = self.run_tool("--max-bytes", str(limit), output=self.temp / "小")
        large = self.run_tool("--min-bytes", str(limit + 1), output=self.temp / "大")
        self.assertTrue(small["records"] and large["records"])
        self.assertTrue(all(sizes[n] <= limit for n in small["records"]))
        self.assertTrue(all(sizes[n] > limit for n in large["records"]))
        # Together they are the full run: same masked names, same results, nothing twice.
        self.assertFalse(set(small["records"]) & set(large["records"]))
        self.assertEqual(set(small["records"]) | set(large["records"]), set(full["records"]))
        for name, record in {**small["records"], **large["records"]}.items():
            self.assertEqual((record["sha256"], record["status"]), (full["records"][name]["sha256"],
                                                                    full["records"][name]["status"]))
        summary = (self.temp / "大" / "summary.md").read_text(encoding="utf-8")
        self.assertIn(f"大きさで絞った対象: {limit + 1:,} バイト以上", summary)
        self.assertNotIn("抜き出し", summary)  # every drawing in the range is checked
        self.assertNotIn("大きさで絞った", (self.temp / "全部" / "summary.md").read_text(encoding="utf-8"))
        self.assertEqual(tree_snapshot(self.source), self.before)

    def test_resume_with_size_filter_keeps_the_two_runs_apart(self):
        full = self.run_tool(output=self.temp / "全部")
        limit = sorted(r["size"] for r in full["records"].values())[1]
        small_output, large_output = self.temp / "小", self.temp / "大"
        small = self.run_tool("--max-bytes", str(limit), output=small_output)
        self.run_tool("--min-bytes", str(limit + 1), output=large_output)
        large_files = tree_snapshot(large_output / "results")
        removed = small_output / "results" / f"{sorted(small['records'])[0]}.json"
        removed.unlink()
        # Resuming without the size option keeps the previous one; only the removed drawing is redone.
        again = self.run_tool(resume=True, output=small_output)
        self.assertEqual(again["processed"], 1)
        self.assertEqual(set(again["records"]), set(small["records"]))
        self.assertEqual(sorted(p.stem for p in (small_output / "results").glob("*.json")), sorted(small["records"]))
        self.assertEqual(tree_snapshot(large_output / "results"), large_files)
        # A different size option on resume is refused.
        with self.assertRaises(corpus_check.UsageError):
            self.run_tool("--max-bytes", str(limit + 1), resume=True, output=small_output)
        with self.assertRaises(corpus_check.UsageError):
            self.run_tool("--min-bytes", "0", resume=True, output=small_output)

    def test_resume_of_an_output_folder_made_before_the_size_options(self):
        self.run_tool()
        mapping_path = self.output / "対応表.json"
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        for key in ("min_bytes", "max_bytes"):
            del mapping["settings"][key]
        mapping_path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
        removed = self.output / "results" / "図面001.json"
        removed.unlink()
        result = self.run_tool(resume=True)  # no size option: the folder keeps "no range"
        self.assertEqual(result["processed"], 1)
        self.assertTrue(removed.exists())
        with self.assertRaises(corpus_check.UsageError):
            self.run_tool("--max-bytes", "1000000", resume=True)

    def test_size_range_with_no_drawing_warns(self):
        lines = []
        args = corpus_check.parse_args(["--source", str(self.source), "--output", str(self.output),
                                        "--min-bytes", str(10 ** 12)])
        result = corpus_check.run(args, log=lines.append)
        self.assertEqual(result["records"], {})
        self.assertTrue(any("1 件もありません" in line for line in lines))
        self.assertEqual(tree_snapshot(self.source), self.before)

    def test_size_filter_refuses_impossible_ranges(self):
        with self.assertRaises(corpus_check.UsageError):
            self.run_tool("--min-bytes", "10", "--max-bytes", "9")
        with self.assertRaises(corpus_check.UsageError):
            self.run_tool("--max-bytes", "-1")
        self.assertFalse(self.output.exists())


    def test_declarations_from_bytes_match_the_reader_on_public_samples(self):
        fixtures = sorted((ROOT / "tests" / "fixtures").rglob("*.jww"))
        fixtures.append(ROOT / "src" / "jwwkit" / "resources" / "empty_template.jww")
        self.assertGreaterEqual(len(fixtures), 30)
        for path in fixtures:
            with self.subTest(path=path.name):
                expected = [(d["name"], d["schema"], d["offset"]) for d in read_records(path)["class_declarations"]]
                found = [(d["name"], d["schema"], d["offset"])
                         for d in corpus_check.class_declarations_from_bytes(path.read_bytes())]
                self.assertEqual(found, expected)
                self.assertIs(corpus_check.schema0_summary(path.read_bytes())["all_zero"], False)

    def test_zero_declarations_and_files_without_declarations(self):
        data = schema0_jww()
        summary = corpus_check.schema0_summary(data)
        self.assertIs(summary["all_zero"], True)
        self.assertEqual({name for name, _ in summary["declarations"]}, {"CDataSen", "CDataEnko", "CDataMoji"})
        self.assertEqual({schema for _, schema in summary["declarations"]}, {0})
        # No declaration at all (not a drawing, or cut before the first one) is not "all zero"
        self.assertEqual(corpus_check.schema0_summary(b"not a drawing" * 10), dict(declarations=[], all_zero=None))
        first = corpus_check.class_declarations_from_bytes(data)[0]["offset"]
        self.assertIsNone(corpus_check.schema0_summary(data[:first])["all_zero"])

    def test_rejected_schema0_drawing_gets_declarations_and_normalization_verdict(self):
        (self.source / f"{SECRET}_他のCAD.jww").write_bytes(schema0_jww())
        result = self.run_tool()
        rejected = {r["name"]: r for r in result["records"].values() if r["status"] == "rejected"}
        self.assertEqual(len(rejected), 2)
        zero = [r for r in rejected.values() if r["schema0"]["all_zero"] is True]
        broken = [r for r in rejected.values() if r["schema0"]["all_zero"] is None]
        self.assertEqual((len(zero), len(broken)), (1, 1))
        self.assertEqual(zero[0]["error"]["stage"], "open")  # the reading result is unchanged
        self.assertEqual(zero[0]["normalization"], dict(status="normalize", reason_category="reason: observed_schema0_only"))
        self.assertEqual(broken[0]["normalization"]["status"], "unsupported")
        ok = [r for r in result["records"].values() if r["status"] == "ok"]
        self.assertTrue(ok and all("schema0" not in r and "normalization" not in r for r in ok))
        text = json.dumps(list(result["records"].values()), ensure_ascii=False)
        self.assertNotIn(SECRET, text)
        summary = (self.output / "summary.md").read_text(encoding="utf-8")
        self.assertIn("## 拒否のうち、クラスの宣言がすべて schema 0 の図面（1 件）", summary)
        self.assertIn("  - 宣言がすべて 0: 1 件", summary)
        self.assertIn("  - 宣言が見つからない: 1 件", summary)
        self.assertIn("| 1 | normalize | reason: observed_schema0_only |", summary)
        self.assertNotIn(SECRET, summary)

    def test_extra_inspection_failure_does_not_change_the_rejection(self):
        (self.source / f"{SECRET}_他のCAD.jww").write_bytes(schema0_jww())
        import jwwkit.normalization as normalization
        original = normalization.inspect_schema_normalization

        def failing(source):
            raise RuntimeError(f"inspection failed for {source}")
        normalization.inspect_schema_normalization = failing
        self.addCleanup(setattr, normalization, "inspect_schema_normalization", original)
        source = next(self.source.glob("*他のCAD.jww"))
        result = corpus_check.inspect_one(source, self.temp / "work.jww")
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["normalization"]["status"], "inspection_error")
        self.assertNotIn(SECRET, result["normalization"]["reason_category"])
        self.assertIs(result["schema0"]["all_zero"], True)
        self.assertTrue(result["original_unchanged"])

    def test_select_checks_only_the_listed_drawings(self):
        target = next(self.source.glob(f"{SECRET}_記号.jws"))
        listing = self.temp / "一覧.txt"
        listing.write_text(f"# 抜き出し\n{hashlib.sha256(target.read_bytes()).hexdigest()}  図面A\n\n",
                           encoding="utf-8")
        result = self.run_tool("--select", str(listing))
        self.assertEqual([r["kind"] for r in result["records"].values()], ["jws"])
        summary = (self.output / "summary.md").read_text(encoding="utf-8")
        self.assertIn("今回の対象: 1 件（抜き出し）", summary)
        self.assertIn("一覧（--select）で選んだ図面: 1 件", summary)
        # The masked names are the same as without --select
        full = self.run_tool(output=self.temp / "出力全件")
        jws_name = [r["name"] for r in full["records"].values() if r["kind"] == "jws"]
        self.assertEqual(list(result["records"]), jws_name)
        # Resuming with another list, or without the list, is refused
        other = self.temp / "別の一覧.txt"
        other.write_text("0" * 64 + "\n", encoding="utf-8")
        with self.assertRaises(corpus_check.UsageError):
            self.run_tool("--select", str(other), resume=True)

    def test_select_refuses_bad_or_unknown_lists(self):
        for content in ("", "# only a comment\n", "not-a-hash\n", "0" * 64 + "\n"):
            with self.subTest(content=content):
                listing = self.temp / "一覧.txt"
                listing.write_text(content, encoding="utf-8")
                with self.assertRaises(corpus_check.UsageError):
                    self.run_tool("--select", str(listing), output=self.temp / f"出力{len(content)}")


if __name__ == "__main__":
    unittest.main()
