"""CLI 명령들이 공유하는 오류 출력과 종료 코드."""

import csv
import sys
from functools import wraps
from typing import Callable


def handle_errors(function: Callable[..., int]) -> Callable[..., int]:
    @wraps(function)
    def wrapped(*args, **kwargs) -> int:
        try:
            return function(*args, **kwargs)
        except (ValueError, OSError, UnicodeError, csv.Error) as exc:
            print(f"[오류] {exc}", file=sys.stderr)
            print("[힌트] --help의 입력 형식, 등록 카테고리, UTF-8 파일 내용과 경로/권한을 확인하세요.",
                  file=sys.stderr)
            return 1
        except (EOFError, KeyboardInterrupt):
            print("[오류] 입력이 중단되었습니다.\n[힌트] 명령을 다시 실행해 입력을 완료하세요.",
                  file=sys.stderr)
            return 1
    return wrapped
