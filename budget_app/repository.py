"""JSONL 스트리밍과 임시 파일을 이용한 원자적 저장만 담당한다."""

import json
import os
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterator, Iterable, TextIO


@contextmanager
def atomic_writer(path: Path) -> Iterator[TextIO]:
    """같은 폴더의 임시 파일을 완성한 후에만 기존 파일을 교체한다."""
    temporary = None
    try:
        with NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent,
                                prefix=".budget-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            yield stream
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


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
        with atomic_writer(self.path(name)) as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
