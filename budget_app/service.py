"""카테고리, 거래, 예산 규칙. 사용자 입력과 파일 쓰기는 다른 모듈에 맡긴다."""

import csv
from dataclasses import asdict, replace
from heapq import merge
from io import StringIO
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from .models import (CSV_FIELDS, Transaction, positive_int, split_tags,
                     valid_category, valid_date, valid_month)
from .repository import Repository

class BudgetService:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def categories(self) -> set[str]:
        names = set()
        for row in self.repository.read("categories"):
            if set(row) != {"name"} or valid_category(row["name"]) != row["name"]:
                raise ValueError("categories.jsonl의 name 필드가 올바르지 않습니다.")
            names.add(row["name"])
        return names

    def category(self, action: str, name: str) -> None:
        name = valid_category(name)
        names = self.categories()
        if action == "add":
            if name in names:
                raise ValueError(f"이미 등록된 카테고리입니다: {name}")
            names.add(name)
        else:
            if name not in names:
                raise ValueError(f"없는 카테고리입니다: {name}")
            if any(tx.category == name for tx in self.transactions()):
                raise ValueError("사용 중인 카테고리입니다. 해당 거래를 먼저 수정하거나 삭제하세요.")
            names.remove(name)
        self.repository.write("categories", ({"name": value} for value in sorted(names)))

    def transactions(self, reverse: bool = False) -> Iterator[Transaction]:
        previous = None
        for row in self.repository.read("transactions", reverse=reverse):
            tx = Transaction.from_record(row)
            key = (tx.date, tx.id)
            if previous is not None and (key > previous if reverse else key < previous):
                raise ValueError("transactions.jsonl의 날짜/id 정렬이 손상되었습니다.")
            previous = key
            yield tx

    def require_category(self, name: str) -> None:
        if name not in self.categories():
            raise ValueError(f"미등록 카테고리: {name}. category add로 먼저 등록하세요.")

    def add(self, tx: Transaction) -> None:
        self.require_category(tx.category)
        ordered = merge(self.transactions(), [tx], key=lambda t: (t.date, t.id))
        self.repository.write("transactions", (asdict(item) for item in ordered))

    def update(self, identifier: str, changes: dict[str, Any]) -> None:
        old = next((tx for tx in self.transactions() if tx.id == identifier), None)
        if old is None:
            raise ValueError(f"없는 데이터: {identifier}")
        if not changes:
            raise ValueError("수정할 필드를 하나 이상 지정하세요. 예: --amount 2000")
        new = replace(old, **changes)
        self.require_category(new.category)
        remaining = (tx for tx in self.transactions() if tx.id != identifier)
        ordered = merge(remaining, [new], key=lambda t: (t.date, t.id))
        self.repository.write("transactions", (asdict(tx) for tx in ordered))

    def delete(self, identifier: str) -> None:
        def remaining() -> Iterator[dict[str, Any]]:
            found = False
            for tx in self.transactions():
                if tx.id == identifier:
                    found = True
                else:
                    yield asdict(tx)
            if not found:
                raise ValueError(f"없는 데이터: {identifier}")
        self.repository.write("transactions", remaining())

    def search(self, *, start: str | None = None, end: str | None = None,
               month: str | None = None, category: str | None = None,
               kind: str | None = None, q: str | None = None,
               tag: str | None = None) -> Iterator[Transaction]:
        if start is not None:
            valid_date(start)
        if end is not None:
            valid_date(end)
        if start and end and start > end:
            raise ValueError("--from 날짜는 --to 날짜보다 늦을 수 없습니다.")
        if month is not None:
            valid_month(month)
        if category is not None:
            self.require_category(category)
        if kind is not None and kind not in ("income", "expense"):
            raise ValueError("타입은 income 또는 expense여야 합니다.")
        for tx in self.transactions(reverse=True):
            if (not start or tx.date >= start) and (not end or tx.date <= end) \
                    and (not month or tx.date.startswith(month + "-")) \
                    and (category is None or tx.category == category) \
                    and (kind is None or tx.type == kind) \
                    and (q is None or q.casefold() in tx.memo.casefold()) \
                    and (tag is None or tag in tx.tags):
                yield tx

    def summary(self, month: str) -> tuple[int, int, dict[str, int], int]:
        income = expense = count = 0
        categories: dict[str, int] = {}
        for tx in self.search(month=month):
            count += 1
            if tx.type == "income":
                income += tx.amount
            else:
                expense += tx.amount
                categories[tx.category] = categories.get(tx.category, 0) + tx.amount
        return income, expense, categories, count

    def budgets(self) -> dict[str, int]:
        result = {}
        for row in self.repository.read("budgets"):
            if set(row) != {"month", "amount"} or not isinstance(row["month"], str):
                raise ValueError("budgets.jsonl의 필드가 올바르지 않습니다.")
            valid_month(row["month"])
            if type(row["amount"]) is not int or row["amount"] <= 0:
                raise ValueError("저장된 예산은 0보다 큰 정수여야 합니다.")
            result[row["month"]] = row["amount"]
        return result

    def set_budget(self, month: str, amount: int) -> None:
        valid_month(month)
        if type(amount) is not int or amount <= 0:
            raise ValueError("예산은 0보다 큰 정수여야 합니다.")
        budgets = self.budgets()
        budgets[month] = amount
        self.repository.write("budgets", ({"month": key, "amount": value}
                                          for key, value in sorted(budgets.items())))

    def import_csv(self, path: Path) -> int:
        """모든 행 검증 성공 후 한 번 교체한다. 오류가 있으면 전체 취소한다."""
        names = self.categories()
        imported = []
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            if reader.fieldnames != list(CSV_FIELDS):
                raise ValueError("CSV 헤더는 date,type,category,amount,memo,tags 순서여야 합니다.")
            for row in reader:
                try:
                    if None in row or any(value is None for value in row.values()):
                        raise ValueError("CSV 열 개수가 헤더와 다릅니다.")
                    tx = Transaction(id=uuid4().hex, date=row["date"], type=row["type"],
                                     category=row["category"], amount=positive_int(row["amount"]),
                                     memo=row["memo"], tags=split_tags(row["tags"]))
                    if tx.category not in names:
                        raise ValueError(f"미등록 카테고리: {tx.category}. category add로 등록하세요.")
                except ValueError as exc:
                    raise ValueError(f"CSV {reader.line_num}행: {exc} 가져오기를 전부 취소했습니다.") from exc
                imported.append(tx)
        imported.sort(key=lambda tx: (tx.date, tx.id))
        ordered = merge(self.transactions(), imported, key=lambda tx: (tx.date, tx.id))
        self.repository.write("transactions", (asdict(tx) for tx in ordered))
        return len(imported)

    def export_csv(self, path: Path, *, month: str | None = None,
                   start: str | None = None, end: str | None = None) -> int:
        if (month is not None and (start is not None or end is not None)) \
                or (month is None and (start is None or end is None)):
            raise ValueError("export는 --month 또는 --from/--to 두 날짜를 지정하세요.")
        if any(path.resolve() == self.repository.path(name).resolve()
               for name in ("transactions", "categories", "budgets")):
            raise ValueError("내보내기 경로로 앱 저장 파일을 사용할 수 없습니다.")
        count = 0
        with StringIO(newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for tx in self.search(month=month, start=start, end=end):
                writer.writerow({"date": tx.date, "type": tx.type, "category": tx.category,
                                 "amount": tx.amount, "memo": tx.memo, "tags": ",".join(tx.tags)})
                count += 1
            path.write_text(stream.getvalue(), encoding="utf-8")
        return count
