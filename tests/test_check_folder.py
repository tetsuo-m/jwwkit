"""Issue #44: `python -m jwwkit check-folder`. Public fixtures and synthetic drawings only."""
import contextlib
import csv
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jwwkit._commands import check_folder as cf
from jwwkit.line_document import JwwDocument

from test_corpus_check import schema0_jww
from test_old_versions import patch_schemas
from test_v600_schema700 import fixture

CONTENT_MARK = "図面の中の秘密の文字"


def snapshot(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(folder).rglob("*")) if p.is_file()}


def read_list(path):
    raw = Path(path).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "UTF-8 with BOM"
    with open(path, encoding="utf-8-sig", newline="") as stream:
        return list(csv.reader(stream))


class CheckFolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="check-folder-test-"))
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        self.folder = self.temp / "図面"
        (self.folder / "下" / "さらに下").mkdir(parents=True)
        editable = JwwDocument()
        editable.add_line((0, 0), (10, 0))
        editable.add_text((0, 5), content=CONTENT_MARK)
        editable.save(self.folder / "v700_編集できる.jww")
        shutil.copyfile(fixture(600), self.folder / "下" / "v600_Jw_cadのv6.JWW")
        for version in (230, 300, 351, 420):
            shutil.copyfile(fixture(version), self.folder / "下" / f"古い_v{version}.jww")
        (self.folder / "下" / "さらに下" / "他のCAD_schema0.jww").write_bytes(schema0_jww())
        rejected = patch_schemas((self.folder / "v700_編集できる.jww").read_bytes(), 420)
        (self.folder / "拒否_クラスの版.jww").write_bytes(rejected)
        (self.folder / "壊れた_印なし.jww").write_bytes(b"NotAJwwFile" + CONTENT_MARK.encode("utf-8"))
        (self.folder / "壊れた_途中で切れた.jww").write_bytes(fixture(700).read_bytes()[:3000])
        (self.folder / "空.jww").write_bytes(b"")
        shutil.copyfile(self.folder / "拒否_クラスの版.jww", self.folder / "12.jww")  # a name that is also a number
        (self.folder / "下" / "v600_クラスの版600.jww").write_bytes(patch_schemas(fixture(600).read_bytes(), 600))
        (self.folder / "図面でない.txt").write_text(CONTENT_MARK, encoding="utf-8")
        self.before = snapshot(self.folder)

    def run_check(self, **kwargs):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code, counts, output = cf.check_folder(self.folder, **kwargs)
        return code, counts, output, out.getvalue()

    def rows(self, output):
        table = read_list(output)
        self.assertEqual(tuple(table[0]), cf.COLUMNS)
        return {(r[0], r[1]): dict(zip(cf.COLUMNS, r)) for r in table[1:]}

    def assert_drawings_unchanged(self, output=None):
        after = snapshot(self.folder)
        if output is not None and Path(output).parent == self.folder:
            after.pop(Path(output).name)
        self.assertEqual(after, self.before)

    def test_sorts_every_drawing_and_writes_one_list(self):
        code, counts, output, screen = self.run_check()
        self.assertEqual(code, 0)
        self.assertEqual(output.parent, self.folder)
        self.assertRegex(output.name, r"^jwwkit_check_\d{8}_\d{4}\.csv$")
        rows = self.rows(output)
        kinds = {key: row["分け方"] for key, row in rows.items()}
        self.assertEqual(kinds, {
            ("", "v700_編集できる.jww"): cf.EDITABLE,
            ("下", "v600_Jw_cadのv6.JWW"): cf.EDITABLE,
            ("下", "古い_v230.jww"): cf.READ_ONLY,
            ("下", "古い_v300.jww"): cf.READ_ONLY,
            ("下", "古い_v351.jww"): cf.READ_ONLY,
            ("下", "古い_v420.jww"): cf.READ_ONLY,
            ("下/さらに下", "他のCAD_schema0.jww"): cf.EXPLICIT,
            ("", "拒否_クラスの版.jww"): cf.REJECTED,
            ("", "壊れた_印なし.jww"): cf.REJECTED,
            ("", "壊れた_途中で切れた.jww"): cf.REJECTED,
            ("", "空.jww"): cf.REJECTED,
            ("", "12.jww"): cf.REJECTED,
            ("下", "v600_クラスの版600.jww"): cf.EDITABLE,
        })
        self.assertEqual(counts, {cf.EDITABLE: 3, cf.READ_ONLY: 4, cf.EXPLICIT: 1, cf.REJECTED: 5, cf.UNEXPECTED: 0})
        for name in ("壊れた_途中で切れた.jww", "空.jww"):
            self.assertEqual(rows[("", name)]["理由の種類"], "ファイルが途中で切れている（空のファイルを含む）")
        # The rejection message is jwwkit's own, numbers included, even when the file name is a number.
        self.assertEqual(rows[("", "12.jww")]["拒否の文"], rows[("", "拒否_クラスの版.jww")]["拒否の文"])
        self.assertNotIn("<", rows[("", "12.jww")]["拒否の文"])
        self.assertEqual(rows[("下", "古い_v420.jww")]["ファイルの版"], "420")
        self.assertIn("Ver.7.00", rows[("下", "古い_v420.jww")]["理由の種類"])
        self.assertIn("rebro_schema0", rows[("下/さらに下", "他のCAD_schema0.jww")]["理由の種類"])
        self.assertEqual(rows[("", "拒否_クラスの版.jww")]["理由の種類"], "クラスの版が受け付けない値")
        self.assertIn("Unsupported class schema", rows[("", "拒否_クラスの版.jww")]["拒否の文"])
        self.assertEqual(rows[("", "壊れた_印なし.jww")]["理由の種類"], "JWWの印がない（JWWでない可能性）")
        self.assertEqual(rows[("", "壊れた_印なし.jww")]["ファイルの版"], "")
        self.assertEqual(rows[("", "v700_編集できる.jww")]["大きさ（バイト）"],
                         str((self.folder / "v700_編集できる.jww").stat().st_size))
        for row in rows.values():
            if row["分け方"] == cf.EDITABLE:
                self.assertEqual((row["理由の種類"], row["拒否の文"]), ("", ""))
            else:
                self.assertNotEqual(row["理由の種類"], "")
        for kind in cf.KINDS:
            self.assertIn(f"{kind}：{counts[kind]} 件", screen)
        self.assert_drawings_unchanged(output)

    def test_no_text_from_inside_the_drawings_in_the_list_or_on_the_screen(self):
        _code, _counts, output, screen = self.run_check()
        self.assertNotIn(CONTENT_MARK, output.read_text(encoding="utf-8-sig"))
        self.assertNotIn(CONTENT_MARK, screen)
        for name in self.before:
            if not Path(name).stem.isdigit():  # a number-only name could match the counts or the date
                self.assertNotIn(Path(name).stem, screen)

    def test_existing_list_is_never_overwritten_and_no_drawing_is_opened(self):
        output = self.temp / "一覧.csv"
        output.write_bytes(b"keep me")
        with mock.patch.object(cf, "classify") as classify:
            code, counts, _output, screen = self.run_check(output=output)
        classify.assert_not_called()
        self.assertEqual(code, 2)
        self.assertEqual(output.read_bytes(), b"keep me")
        self.assertIn("止めます", screen)
        self.assert_drawings_unchanged()

    def test_default_name_already_present_stops(self):
        fixed = cf.default_output(self.folder)
        fixed.write_bytes(b"old list")
        self.before = snapshot(self.folder)
        with mock.patch.object(cf, "default_output", return_value=fixed):
            code, _counts, _output, _screen = self.run_check()
        self.assertEqual(code, 2)
        self.assertEqual(fixed.read_bytes(), b"old list")

    def test_options(self):
        output = self.temp / "外の一覧.csv"
        _code, counts, _output, _screen = self.run_check(recursive=False, output=output, only_problems=True)
        rows = self.rows(output)
        self.assertTrue(all(key[0] == "" for key in rows))
        self.assertNotIn(("", "v700_編集できる.jww"), rows)
        self.assertEqual(counts[cf.EDITABLE], 1)  # counted on the screen even when left out of the list
        self.assertEqual(sum(counts.values()), 6)
        self.assert_drawings_unchanged()

    def test_unexpected_exception_is_listed_and_the_next_drawing_follows(self):
        from jwwkit import CadDocument
        original = CadDocument.open

        def failing(path, *args, **kwargs):
            if Path(path).name == "v700_編集できる.jww":
                raise RuntimeError("synthetic failure")
            return original(path, *args, **kwargs)

        with mock.patch.object(CadDocument, "open", side_effect=failing):
            _code, counts, output, _screen = self.run_check()
        rows = self.rows(output)
        row = rows[("", "v700_編集できる.jww")]
        self.assertEqual((row["分け方"], row["理由の種類"]), (cf.UNEXPECTED, "予想外の例外"))
        self.assertIn("RuntimeError", row["拒否の文"])
        self.assertEqual(rows[("下", "古い_v420.jww")]["分け方"], cf.READ_ONLY)
        self.assertEqual(sum(counts.values()), 13)

    def test_change_during_the_check_is_noted(self):
        target = self.folder / "下" / "古い_v230.jww"
        original = cf._fingerprint
        calls = {"n": 0}

        def changing(path):
            value = original(path)
            if Path(path) == target:
                calls["n"] += 1
                if calls["n"] == 2:
                    return (value[0], value[1] + 1, value[2])
            return value

        with mock.patch.object(cf, "_fingerprint", changing):
            _code, _counts, output, _screen = self.run_check()
        self.assertIn("途中でファイルが変わった", self.rows(output)[("下", "古い_v230.jww")]["備考"])

    def test_large_drawing_is_announced(self):
        with mock.patch.object(cf, "LARGE_BYTES", 1000):
            _code, _counts, output, screen = self.run_check()
        self.assertIn("50MBを超える図面です", screen)
        self.assertIn("50MBを超える図面", self.rows(output)[("下", "古い_v230.jww")]["備考"])

    def test_output_that_cannot_be_made_stops_before_opening_drawings(self):
        for output in (self.temp / "ないフォルダ" / "一覧.csv", self.temp, self.temp / "一覧.jww"):
            with self.subTest(output=output.name), mock.patch.object(cf, "classify") as classify:
                code, _counts, _output, screen = self.run_check(output=output)
                classify.assert_not_called()
                self.assertEqual(code, 2)
                self.assertIn("止めます", screen)
        self.assertFalse((self.temp / "一覧.jww").exists())
        self.assert_drawings_unchanged()

    @unittest.skipUnless(sys.platform == "win32", "junctions are a Windows feature")
    def test_folder_junction_is_not_followed(self):
        outside = self.temp / "外"
        outside.mkdir()
        shutil.copyfile(fixture(700), outside / "外の図面.jww")
        link = self.folder / "リンク"
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
        if made.returncode != 0:
            self.skipTest("could not make a junction")
        loop = self.folder / "下" / "親へ戻る"
        subprocess.run(["cmd", "/c", "mklink", "/J", str(loop), str(self.folder)], capture_output=True)
        _code, counts, output, screen = self.run_check()
        self.assertNotIn(("リンク", "外の図面.jww"), self.rows(output))
        self.assertEqual(sum(counts.values()), 13)
        self.assertIn("たどらなかったフォルダのリンク・ジャンクション：2 件", screen)

    def test_reason_words(self):
        for message, reason in (
                ("Truncated record at 0; element=header", "ファイルが途中で切れている（空のファイルを含む）"),
                ("Invalid embedded image: gzip stream is truncated", "同梱の画像の形が確かめていない形か、壊れている"),
                ("Embedded image unverified: BMP pixel data is truncated", "同梱の画像の形が確かめていない形か、壊れている"),
                ("Unsupported noncanonical/64-bit sequence count (… is accepted only in v700 drawings …)", "要素の個数が普通と違う書き方"),
                ("Block definitions exceed the ezjww limit: …", "ブロック定義が1万個を超える"),
                ("something new", "その他の拒否")):
            with self.subTest(message=message):
                self.assertEqual(cf.reason_of(message), reason)

    def test_missing_folder(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code, _counts, output = cf.check_folder(self.temp / "ない")
        self.assertEqual((code, output), (2, None))

    def test_command_line(self):
        output = self.temp / "cli.csv"
        result = subprocess.run([sys.executable, "-m", "jwwkit", "check-folder", str(self.folder), "--output", str(output)],
                                capture_output=True, encoding="utf-8", errors="replace",
                                env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(read_list(output)), 14)
        self.assertIn("編集できる：3 件", result.stdout)
        self.assert_drawings_unchanged()
        again = subprocess.run([sys.executable, "-m", "jwwkit", "check-folder", str(self.folder), "--output", str(output)],
                               capture_output=True, encoding="utf-8", errors="replace",
                               env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertEqual(again.returncode, 2)
        self.assertEqual(len(read_list(output)), 14)


if __name__ == "__main__":
    unittest.main()
