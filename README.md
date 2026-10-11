# B2-1 · 용돈 기입장

Python 3.10 이상, 표준 라이브러리만 사용합니다. 프로젝트 폴더에서 실행합니다.

```bash
python -m budget_app --help
python -m budget_app category add  # 카테고리명 대화형 입력
python -m budget_app add           # 날짜/타입/카테고리/금액/메모/태그 입력
python -m budget_app list --limit 10
python -m budget_app search --from 2024-01-01 --to 2024-01-31 --category food --type expense --q 점심 --tag meal
python -m budget_app budget set --month 2024-01 --amount 500000
python -m budget_app budget get --month 2024-01
python -m budget_app summary --month 2024-01 --top 3
python -m budget_app update --id ID --date 2024-01-16 --amount 20000 --memo "점심 수정" --tags "meal,work"
python -m budget_app delete --id ID
python -m budget_app category list
python -m budget_app category remove  # 사용 중이면 삭제 거부
python -m budget_app export --out january.csv --month 2024-01
python -m budget_app export --out period.csv --from 2024-01-01 --to 2024-02-29
python -m budget_app import --from january.csv
python -m budget_app --data-dir ./my-data list
python -m unittest discover -s tests -v
```

모든 명령과 하위 명령에 `--help`를 사용할 수 있습니다. `--data-dir`는 명령 **앞**에 지정합니다. 날짜는 `YYYY-MM-DD`, 월은 `YYYY-MM`, 금액·예산·개수는 양수 정수입니다. 처음에는 카테고리가 없으므로 `category add`로 먼저 등록합니다. `update`는 **옵션 방식**으로 고정하며 `--type`, `--category`도 지원합니다. `--memo ""`, `--tags ""`로 해당 값을 지웁니다.

## 저장과 처리 정책

- 기본 `./data`에 UTF-8 JSONL 3개 파일을 자동 생성합니다. JSONL은 한 줄당 JSON 객체 하나입니다.
- `transactions.jsonl`: `id,type,date,amount,category,memo,tags` (`tags`는 문자열 배열).
- `categories.jsonl`: `name`. `budgets.jsonl`: `month,amount`.
- 거래는 `(date,id)` 오름차순으로 저장하고 뒤에서 제너레이터로 읽습니다. 조회·검색은 날짜 내림차순이며 같은 날짜는 id 내림차순입니다. 기본 목록은 10건, 검색은 일치하는 모든 거래를 출력합니다.
- 수정·삭제와 기타 저장은 같은 폴더의 임시 파일을 완성하고 `os.replace`로 교체합니다. 가져오기는 잘못된 행이 하나라도 있으면 **전체 취소**하며 기존 거래를 유지합니다.
- CSV에는 id가 없으므로 가져올 때 새 id를 생성합니다. 같은 파일을 다시 가져오면 거래가 다시 추가됩니다. 태그는 앞뒤 공백과 중복·빈 항목을 제거합니다.
- 예산 사용률은 `총지출 / 예산 × 100`이며 지출이 예산보다 클 때 경고합니다. 검색 기간은 양 끝 날짜를 포함합니다.
- 정상 종료 코드는 0, 오류는 원인·해결 힌트와 함께 1입니다. 여러 프로세스의 동시 쓰기는 지원하지 않습니다.

## CSV 스키마

UTF-8, 쉼표 구분, 아래 **6개 헤더와 순서**를 사용합니다. `memo`, `tags`는 빈 값이 가능합니다. 가져오기는 UTF-8 BOM도 허용합니다. 쉼표·줄바꿈·따옴표는 표준 CSV 인용 규칙을 따릅니다.

```csv
date,type,category,amount,memo,tags
2024-01-15,expense,food,15000,점심,"meal,work"
```

`date`는 실제 날짜, `type`은 `income`/`expense`, `category`는 등록된 이름, `amount`는 양수 정수입니다. 내보내기는 `--month` 또는 `--from`과 `--to` 쌍을 사용합니다.

구조: `models`(데이터·검증), `repository`(파일), `service`(업무 규칙), `cli`(입출력), `decorators`(공통 오류 처리). PDF와 실행 데이터는 Git에 포함하지 않습니다.
