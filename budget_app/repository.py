"""JSONL 스트리밍과 검증 완료 후 전체 파일 재작성을 담당한다."""

import json
import os
from pathlib import Path
from typing import Any, Iterator, Iterable


def reverse_lines(path: Path) -> Iterator[str]:
    """UTF-8 문자가 블록 경계에 걸려도 완전한 한 줄이 된 뒤 해독한다."""
    with path.open("rb") as stream:
        position = stream.seek(0, os.SEEK_END)
        remainder = b""
        while position:
            size = min(8192, position)
            position -= size
            stream.seek(position)
            lines = (stream.read(size) + remainder).split(b"\n")
            remainder = lines[0]
            for line in reversed(lines[1:]):
                if line:
                    yield line.decode("utf-8")
        if remainder:
            yield remainder.decode("utf-8")


class Repository:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        for name in ("transactions", "categories", "budgets"):
            (directory / f"{name}.jsonl").touch(exist_ok=True)

    def path(self, name: str) -> Path:
        return self.directory / f"{name}.jsonl"

    def read(self, name: str, reverse: bool = False) -> Iterator[dict[str, Any]]:
        path = self.path(name)
        with path.open(encoding="utf-8") as stream:
            lines = reverse_lines(path) if reverse else stream
            for number, line in enumerate(lines, 1):
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError("JSON 객체가 필요합니다.")
                except ValueError as exc:
                    location = f"끝에서 {number}번째" if reverse else f"{number}행"
                    raise ValueError(f"{path.name} {location}의 JSON이 손상되었습니다.") from exc
                yield row

    def write(self, name: str, rows: Iterable[dict[str, Any]]) -> None:
        # 모든 행을 읽고 검증·직렬화한 뒤에만 원본을 쓰기 모드로 연다.
        content = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        self.path(name).write_text(content, encoding="utf-8")
