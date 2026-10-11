"""거래 구조와 입력 검증. 파일이나 화면에 접근하지 않는다."""

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

CSV_FIELDS = ("date", "type", "category", "amount", "memo", "tags")


def valid_date(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다. 예: 2024-01-15")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("존재하지 않는 날짜입니다. 월별 일수와 윤년을 확인하세요.") from exc
    return value


def valid_month(value: str) -> str:
    valid_date(value + "-01")
    return value


def positive_int(value: str) -> int:
    if not re.fullmatch(r"[0-9]+", value) or int(value) <= 0:
        raise ValueError("금액과 개수는 0보다 큰 정수여야 합니다. 예: 15000")
    return int(value)


def split_tags(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(tag.strip() for tag in value.split(",") if tag.strip()))


def valid_category(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError("카테고리는 비어 있지 않은 한 줄의 이름이어야 합니다.")
    return value.strip()


@dataclass(frozen=True)
class Transaction:
    id: str
    type: str
    date: str
    amount: int
    category: str
    memo: str = ""
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("거래 id가 비어 있거나 문자열이 아닙니다.")
        valid_date(self.date)
        if self.type not in ("income", "expense"):
            raise ValueError("타입은 income 또는 expense여야 합니다.")
        if type(self.amount) is not int or self.amount <= 0:
            raise ValueError("금액은 0보다 큰 정수여야 합니다.")
        if valid_category(self.category) != self.category:
            raise ValueError("카테고리 이름의 앞뒤 공백을 제거하세요.")
        if not isinstance(self.memo, str):
            raise ValueError("메모는 문자열이어야 합니다.")
        if not isinstance(self.tags, tuple) or any(
            not isinstance(tag, str) or not tag or "," in tag for tag in self.tags
        ):
            raise ValueError("태그는 쉼표를 포함하지 않은 문자열 목록이어야 합니다.")

    @classmethod
    def from_record(cls, row: dict[str, Any]) -> "Transaction":
        row = dict(row)
        if not isinstance(row.get("tags", []), list):
            raise ValueError("저장된 tags는 JSON 배열이어야 합니다.")
        row["tags"] = tuple(row.get("tags", []))
        try:
            return cls(**row)
        except TypeError as exc:
            raise ValueError("거래 저장 필드가 올바르지 않습니다.") from exc
