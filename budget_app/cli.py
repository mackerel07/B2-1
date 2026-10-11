"""명령 해석, 대화형 입력, 출력. 업무 규칙은 BudgetService에 둔다."""

import argparse
from itertools import islice
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from .decorators import handle_errors
from .models import Transaction, positive_int, split_tags, valid_month
from .repository import Repository
from .service import BudgetService


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def parser() -> Parser:
    root = Parser(description="용돈 기입장 (Python 3.10+, 표준 라이브러리)", allow_abbrev=False)
    root.add_argument("--data-dir", type=Path, default=Path("data"), help="저장 폴더 (기본: ./data)")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("add", help="대화형 거래 추가", allow_abbrev=False)
    listing = commands.add_parser("list", help="날짜 최신순 목록", allow_abbrev=False)
    listing.add_argument("--limit", type=positive_int, default=10, help="출력 개수 (기본: 10)")
    search = commands.add_parser("search", help="조건에 맞는 거래 검색", allow_abbrev=False)
    search.add_argument("--from", dest="start", help="시작일 YYYY-MM-DD (포함)")
    search.add_argument("--to", dest="end", help="종료일 YYYY-MM-DD (포함)")
    search.add_argument("--category")
    search.add_argument("--type", dest="kind", choices=("income", "expense"))
    search.add_argument("--q", help="메모 부분 검색 (대소문자 무시)")
    search.add_argument("--tag", help="정확히 일치하는 태그")
    summary = commands.add_parser("summary", help="월별 요약과 예산 사용률", allow_abbrev=False)
    summary.add_argument("--month", required=True, help="YYYY-MM")
    summary.add_argument("--top", type=positive_int, default=3)
    budget = commands.add_parser("budget", help="예산 설정/조회", allow_abbrev=False)
    budget_actions = budget.add_subparsers(dest="action", required=True)
    for action in ("set", "get"):
        command = budget_actions.add_parser(action, allow_abbrev=False)
        command.add_argument("--month", required=True, help="YYYY-MM")
        if action == "set":
            command.add_argument("--amount", type=positive_int, required=True)
    category = commands.add_parser("category", help="카테고리 관리", allow_abbrev=False)
    category_actions = category.add_subparsers(dest="action", required=True)
    for action in ("add", "list", "remove"):
        category_actions.add_parser(action, allow_abbrev=False)
    update = commands.add_parser("update", help="옵션 기반 거래 수정", allow_abbrev=False)
    update.add_argument("--id", required=True)
    update.add_argument("--date")
    update.add_argument("--type", choices=("income", "expense"))
    update.add_argument("--category")
    update.add_argument("--amount", type=positive_int)
    update.add_argument("--memo", help="빈 문자열로 메모 삭제 가능")
    update.add_argument("--tags", help="쉼표 구분, 빈 문자열로 태그 삭제 가능")
    delete = commands.add_parser("delete", help="id로 거래 삭제", allow_abbrev=False)
    delete.add_argument("--id", required=True)
    importing = commands.add_parser("import", help="CSV 전체 검증 후 가져오기", allow_abbrev=False)
    importing.add_argument("--from", dest="source", type=Path, required=True)
    export = commands.add_parser("export", help="월 또는 기간 CSV 내보내기", allow_abbrev=False)
    export.add_argument("--out", type=Path, required=True)
    export.add_argument("--month", help="YYYY-MM (--from/--to와 함께 사용 불가)")
    export.add_argument("--from", dest="start", help="YYYY-MM-DD (--to도 필수)")
    export.add_argument("--to", dest="end", help="YYYY-MM-DD (--from도 필수)")
    return root


def show_transactions(transactions: Iterable[Transaction]) -> None:
    count = 0
    for tx in transactions:
        print(f"{tx.id} | {tx.date} | {tx.type} | {tx.category} | {tx.amount} | "
              f"{tx.memo!r} | {','.join(tx.tags)!r}")
        count += 1
    if not count:
        print("데이터 없음")


@handle_errors
def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    service = BudgetService(Repository(args.data_dir))
    if args.command == "add":
        names = service.categories()
        if not names:
            raise ValueError("카테고리가 없습니다. category add를 먼저 실행하세요.")
        print("등록 카테고리: " + ", ".join(sorted(names)))
        tx = Transaction(id=uuid4().hex,
                         date=input("날짜(YYYY-MM-DD): ").strip(),
                         type=input("타입(income/expense): ").strip(),
                         category=input("카테고리: ").strip(),
                         amount=positive_int(input("금액(양수 정수): ").strip()),
                         memo=input("메모(선택): "),
                         tags=split_tags(input("태그(쉼표 구분, 선택): ")))
        service.add(tx)
        print(f"[저장 완료] id={tx.id}")
    elif args.command == "list":
        show_transactions(islice(service.transactions(reverse=True), args.limit))
    elif args.command == "search":
        show_transactions(service.search(start=args.start, end=args.end, category=args.category,
                                         kind=args.kind, q=args.q, tag=args.tag))
    elif args.command == "summary":
        income, expense, categories, count = service.summary(args.month)
        if not count:
            print("데이터 없음")
        print(f"총 수입: {income}원\n총 지출: {expense}원\n잔액: {income - expense}원")
        amount = service.budgets().get(args.month)
        if amount is not None:
            print(f"예산: {amount}원 (사용률 {expense / amount * 100:.1f}%)")
            if expense > amount:
                print(f"[경고] 예산 초과: {expense - amount}원")
        print(f"지출 TOP {args.top}")
        for i, (name, value) in enumerate(sorted(categories.items(), key=lambda item: (-item[1], item[0]))[:args.top], 1):
            print(f"{i}) {name} {value}원")
    elif args.command == "budget":
        if args.action == "set":
            service.set_budget(args.month, args.amount)
            print(f"[저장 완료] {args.month} 예산 {args.amount}원")
        else:
            valid_month(args.month)
            amount = service.budgets().get(args.month)
            print("예산 미설정" if amount is None else f"예산: {amount}원")
    elif args.command == "category":
        if args.action == "list":
            names = sorted(service.categories())
            print("\n".join(f"- {name}" for name in names) if names else "카테고리 없음: category add로 등록하세요.")
        else:
            name = input("카테고리명: ").strip()
            service.category(args.action, name)
            print(f"[완료] category {args.action}: {name}")
    elif args.command == "update":
        changes = {field: getattr(args, field) for field in
                   ("date", "type", "category", "amount", "memo", "tags")
                   if getattr(args, field) is not None}
        if "tags" in changes:
            changes["tags"] = split_tags(changes["tags"])
        service.update(args.id, changes)
        print(f"[수정 완료] id={args.id}")
    elif args.command == "delete":
        service.delete(args.id)
        print(f"[삭제 완료] id={args.id}")
    elif args.command == "import":
        count = service.import_csv(args.source)
        print(f"[완료] imported={count}, skipped=0")
    elif args.command == "export":
        count = service.export_csv(args.out, month=args.month, start=args.start, end=args.end)
        print(f"[완료] {args.out} ({count} records)")
    return 0
