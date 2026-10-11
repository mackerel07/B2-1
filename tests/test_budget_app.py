"""임시 폴더에서 실제 CLI와 데이터 보존/스트리밍 경계를 검증한다."""

import csv
import inspect
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from budget_app.models import CSV_FIELDS, Transaction
from budget_app.repository import Repository, reverse_lines
from budget_app.service import BudgetService

ROOT = Path(__file__).resolve().parents[1]


class BudgetAppTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.data = self.directory / "data"
        self.service = BudgetService(Repository(self.data))
        for name in ("food", "salary", "transport"):
            self.service.category("add", name)

    def run_cli(self, *arguments, text=None, success=True):
        result = subprocess.run([sys.executable, "-m", "budget_app", "--data-dir", str(self.data),
                                 *arguments], input=text, text=True, capture_output=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0 if success else 1, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        if not success:
            self.assertIn("[오류]", result.stderr)
            self.assertIn("[힌트]", result.stderr)
        return result

    def tx(self, identifier="a", day="2024-01-15", amount=15000, kind="expense",
           category="food", memo="점심", tags=("meal", "work")):
        return Transaction(identifier, kind, day, amount, category, memo, tags)

    def csv_file(self, rows, fields=CSV_FIELDS):
        path = self.directory / "import.csv"
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(fields)
            writer.writerows(rows)
        return path

    def test_initialization_empty_category_and_persistence(self):
        empty = self.directory / "new"
        result = subprocess.run([sys.executable, "-m", "budget_app", "--data-dir", str(empty), "add"],
                                capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 1)
        self.assertIn("category add", result.stderr)
        self.assertEqual(len(list(empty.glob("*.jsonl"))), 3)
        self.run_cli("category", "add", text="rent\n")
        self.run_cli("budget", "set", "--month", "2024-01", "--amount", "10000")
        self.run_cli("add", text="2024-01-15\nexpense\nfood\n15000\n점심\nmeal,work\n")
        self.assertIn("food", self.run_cli("category", "list").stdout)
        self.assertIn("rent", self.run_cli("category", "list").stdout)
        self.assertIn("점심", self.run_cli("list").stdout)
        self.assertIn("10000", self.run_cli("budget", "get", "--month", "2024-01").stdout)

    def test_all_help_commands(self):
        for arguments in [(), *((c,) for c in ("add", "list", "search", "summary", "budget",
                                               "category", "update", "delete", "import", "export")),
                          ("budget", "set"), ("budget", "get"), ("category", "add"),
                          ("category", "list"), ("category", "remove")]:
            with self.subTest(arguments=arguments):
                self.assertIn("usage:", self.run_cli(*arguments, "--help").stdout)

    def test_list_latest_date_and_limit(self):
        for tx in (self.tx("b", "2024-03-01"), self.tx("a", "2023-01-01"), self.tx("c", "2024-03-01")):
            self.service.add(tx)
        lines = self.run_cli("list", "--limit", "2").stdout.splitlines()
        self.assertEqual([line.split(" | ")[0] for line in lines], ["c", "b"])
        self.assertEqual([tx.id for tx in self.service.transactions()], ["a", "b", "c"])

    def test_search_combined_filters_and_inclusive_dates(self):
        self.service.add(self.tx(memo="Lunch 점심"))
        self.service.add(self.tx("b", "2024-02-01"))
        self.service.add(self.tx("c", kind="income", category="salary"))
        output = self.run_cli("search", "--from", "2024-01-15", "--to", "2024-01-15",
                              "--category", "food", "--type", "expense", "--q", "lunch", "--tag", "meal").stdout
        self.assertEqual(len(output.splitlines()), 1)
        self.assertTrue(output.startswith("a |"))
        self.assertIn("데이터 없음", self.run_cli("search", "--tag", "mea").stdout)

    def test_summary_totals_top_and_budget_warning(self):
        self.service.add(self.tx())
        self.service.add(self.tx("b", amount=30000, kind="income", category="salary"))
        self.service.add(self.tx("c", amount=1000, category="transport"))
        self.service.set_budget("2024-01", 10000)
        output = self.run_cli("summary", "--month", "2024-01", "--top", "1").stdout
        for expected in ("총 수입: 30000원", "총 지출: 16000원", "잔액: 14000원",
                         "사용률 160.0%", "예산 초과: 6000원", "1) food 15000원"):
            self.assertIn(expected, output)
        self.assertNotIn("2)", output)
        self.assertIn("데이터 없음", self.run_cli("summary", "--month", "2025-01").stdout)

    def test_budget_equal_no_warning_and_empty_month_rate(self):
        self.service.add(self.tx(amount=10000))
        self.service.set_budget("2024-01", 10000)
        output = self.run_cli("summary", "--month", "2024-01").stdout
        self.assertIn("100.0%", output)
        self.assertNotIn("[경고]", output)
        self.service.set_budget("2025-01", 10000)
        self.assertIn("사용률 0.0%", self.run_cli("summary", "--month", "2025-01").stdout)

    def test_category_duplicate_used_missing_and_remove(self):
        self.service.add(self.tx())
        before = (self.data / "categories.jsonl").read_bytes()
        for name in ("food", "missing"):
            self.run_cli("category", "remove", text=name + "\n", success=False)
            self.assertEqual((self.data / "categories.jsonl").read_bytes(), before)
        self.run_cli("category", "add", text="food\n", success=False)
        self.run_cli("category", "remove", text="transport\n")
        self.assertNotIn("transport", self.service.categories())

    def test_update_fields_clear_optionals_and_reorder(self):
        self.service.add(self.tx())
        self.service.add(self.tx("b", "2024-02-01"))
        self.run_cli("update", "--id", "a", "--date", "2024-03-01", "--type", "income",
                     "--category", "salary", "--amount", "30000", "--memo", "", "--tags", "")
        rows = list(self.service.transactions())
        self.assertEqual([tx.id for tx in rows], ["b", "a"])
        self.assertEqual(rows[-1], self.tx("a", "2024-03-01", 30000, "income", "salary", "", ()))

    def test_delete_and_unknown_id_preserve_file(self):
        self.service.add(self.tx())
        original = (self.data / "transactions.jsonl").read_bytes()
        for command in ("delete", "update"):
            self.run_cli(command, "--id", "missing", success=False)
            self.assertEqual((self.data / "transactions.jsonl").read_bytes(), original)
        self.run_cli("delete", "--id", "a")
        self.assertEqual(list(self.service.transactions()), [])

    def test_invalid_values_and_options(self):
        cases = [("list", "--limit", "0"), ("list", "--limit", "-1"),
                 ("summary", "--month", "2024-13"), ("summary", "--month", "2024-1"),
                 ("summary", "--month", ""), ("search", "--from", ""), ("search", "--to", ""),
                 ("summary", "--month", "2024-01", "--top", "0"),
                 ("budget", "set", "--month", "2024-01", "--amount", "1.5"),
                 ("search", "--from", "2024-02-30"), ("search", "--type", "other"),
                 ("search", "--category", "unknown"),
                 ("search", "--from", "2024-02-01", "--to", "2024-01-01"),
                 ("list", "--unknown"), ("export", "--out", str(self.directory / "out.csv"))]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                self.run_cli(*arguments, success=False)
        for values in [("2024-02-30", "expense", "food", "10"),
                       ("2024-01-01", "bad", "food", "10"),
                       ("2024-01-01", "expense", "other", "10"),
                       ("2024-01-01", "expense", "food", "0")]:
            self.run_cli("add", text="\n".join((*values, "", "")) + "\n", success=False)
        self.assertEqual(list(self.service.transactions()), [])

    def test_update_invalid_leaves_original(self):
        self.service.add(self.tx())
        original = (self.data / "transactions.jsonl").read_bytes()
        for options in [(), ("--date", "2024-02-30"), ("--category", "bad"), ("--amount", "0")]:
            self.run_cli("update", "--id", "a", *options, success=False)
            self.assertEqual((self.data / "transactions.jsonl").read_bytes(), original)

    def test_csv_round_trip_unicode_quotes_commas_newlines(self):
        tx = self.tx(memo='점심, "맛집"\n두 번째 줄', tags=("식사", "work"))
        self.service.add(tx)
        path = self.directory / "out.csv"
        self.run_cli("export", "--out", str(path), "--month", "2024-01")
        with path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(tuple(rows[0]), CSV_FIELDS)
        self.assertEqual(rows[0]["memo"], tx.memo)
        self.assertEqual(rows[0]["tags"], "식사,work")
        self.assertIn("imported=1", self.run_cli("import", "--from", str(path)).stdout)
        transactions = list(self.service.transactions())
        self.assertEqual(len(transactions), 2)
        self.assertEqual(len({tx.id for tx in transactions}), 2)
        for imported in transactions:
            self.assertEqual(imported.memo, tx.memo)
            self.assertEqual(imported.tags, tx.tags)

    def test_import_bad_row_rolls_back_with_line_number(self):
        self.service.add(self.tx())
        before = (self.data / "transactions.jsonl").read_bytes()
        path = self.csv_file([["2024-01-01", "expense", "food", "10", "ok", ""],
                              ["2024-01-02", "expense", "food", "0", "bad", ""]])
        output = self.run_cli("import", "--from", str(path), success=False).stderr
        self.assertIn("CSV 3행", output)
        self.assertIn("전부 취소", output)
        self.assertEqual((self.data / "transactions.jsonl").read_bytes(), before)

    def test_import_bad_header_columns_encoding_and_missing_file(self):
        for fields, row in [(CSV_FIELDS[::-1], []), (CSV_FIELDS, ["2024-01-01"]),
                            (CSV_FIELDS, ["2024-01-01", "expense", "food", "10", "", "", "extra"]),
                            (CSV_FIELDS, ["2024-01-01", "expense", "unknown", "10", "", ""])]:
            path = self.csv_file([row], fields)
            self.run_cli("import", "--from", str(path), success=False)
        path.write_bytes(b"\xff")
        self.run_cli("import", "--from", str(path), success=False)
        self.run_cli("import", "--from", str(self.directory / "missing.csv"), success=False)
        self.assertEqual(list(self.service.transactions()), [])

    def test_import_bom_and_empty_csv(self):
        path = self.csv_file([["2024-01-01", "expense", "food", "10", "", " meal,meal, ,work "]])
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
        self.run_cli("import", "--from", str(path))
        self.assertEqual(next(self.service.transactions()).tags, ("meal", "work"))
        self.assertIn("imported=0", self.run_cli("import", "--from", str(self.csv_file([]))).stdout)

    def test_export_range_constraints_and_protect_storage(self):
        self.service.add(self.tx())
        path = self.directory / "out.csv"
        self.assertIn("1 records", self.run_cli("export", "--out", str(path), "--from", "2024-01-15",
                                               "--to", "2024-01-15").stdout)
        before = path.read_bytes()
        for options in [("--from", "2024-01-01"), ("--month", "2024-01", "--to", "2024-01-31"),
                        ("--month", "bad"), ("--from", "2024-02-01", "--to", "2024-01-01")]:
            self.run_cli("export", "--out", str(path), *options, success=False)
            self.assertEqual(path.read_bytes(), before)
        for name in ("transactions", "categories", "budgets"):
            target = self.data / f"{name}.jsonl"
            original = target.read_bytes()
            self.run_cli("export", "--out", str(target), "--month", "2024-01", success=False)
            self.assertEqual(target.read_bytes(), original)

    def test_partial_rewrite_failure_preserves_original(self):
        path = self.data / "transactions.jsonl"
        path.write_text(json.dumps(asdict(self.tx())) + "\n{broken}\n", encoding="utf-8")
        before = path.read_bytes()
        self.run_cli("delete", "--id", "a", success=False)
        self.assertEqual(path.read_bytes(), before)

    def test_corrupt_metadata_and_model_report_errors(self):
        for name, contents, arguments in [
            ("categories", '{"wrong":1}\n', ("category", "list")),
            ("budgets", '{"month":"2024-01","amount":true}\n', ("budget", "get", "--month", "2024-01")),
            ("transactions", '{"id":"a","tags":"bad"}\n', ("list",))]:
            path = self.data / f"{name}.jsonl"
            path.write_text(contents, encoding="utf-8")
            self.run_cli(*arguments, success=False)

    def test_reverse_stream_utf8_block_boundary_and_long_line(self):
        path = self.directory / "lines.txt"
        lines = ["가" * 9000, "점심" * 3000, "last"]
        for trailing in ("", "\n"):
            path.write_text("\n".join(lines) + trailing, encoding="utf-8")
            self.assertEqual(list(reverse_lines(path)), lines[::-1])

    def test_list_is_lazy_and_does_not_read_all_records(self):
        path = self.data / "transactions.jsonl"
        self.service.add(self.tx())
        valid = path.read_text(encoding="utf-8")
        path.write_text("{broken}\n" + valid, encoding="utf-8")
        self.assertTrue(inspect.isgenerator(self.service.transactions()))
        self.assertTrue(inspect.isgenerator(self.service.search()))
        self.assertTrue(self.run_cli("list", "--limit", "1").stdout.startswith("a |"))
        self.run_cli("search", success=False)

    def test_eof_is_friendly(self):
        self.run_cli("add", text="", success=False)


if __name__ == "__main__":
    unittest.main()
