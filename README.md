# 심야 약국을 어느 구에 열까? (J팀)

서울 25개 자치구의 심야 영업 약국 수를 인구(전체·65세 이상·9세 이하)와 비교해,
심야 약국을 우선 늘려야 할 구를 찾는 서비스입니다.

- 팀원: 김희원, 이가영, 유태정
- 데이터 기준: 약국 2026-11-19 21:58 수집 (5,471행 → 정리 후 5,462행), 인구 2026년 10월

## 사용 데이터
| 데이터 | 출처 | 방식 |
| --- | --- | --- |
| 약국 정보 | 국립중앙의료원_전국 약국 정보 조회 서비스 (공공데이터포털) | 공공 API, 인증키 필요 |
| 연령별 인구 | 행정안전부 주민등록 인구통계 | CSV |

## 폴더 구조
```
src/            수집·정리 코드 (collect.py, clean.py)
data/raw/       기준 원본 데이터
data/processed/ clean.py 실행 결과 (저장소에는 올리지 않음)
data/sample/    기준 CSV가 없을 때 쓰는 샘플
reports/        건수 검증표
docs/           요구사항 정의서, AI 작업 기록
app/            API 서버(server.py), Streamlit 화면(dashboard.py)
```

## 설치
```bash
git clone https://github.com/KIMI7980/sumyeon-j-night-pharmacy.git
cd sumyeon-j-night-pharmacy
python -m pip install -r requirements.txt
```

## 서버 실행

저장소 폴더에서 실행합니다.

```bash
python -m uvicorn app.server:app
```

## 화면 실행

서버를 켜 둔 채, 새 터미널에서 같은 폴더로 이동해 실행합니다.

```bash
python -m streamlit run app/dashboard.py
```

브라우저에서 [Streamlit 화면](http://localhost:8501)을 엽니다.

## 인증키 없이 샘플 실행

`data/raw/`의 약국·인구 기준 CSV가 모두 있으면 인증키 없이 기준 데이터로 실행됩니다.
샘플을 확인하려면 별도 작업 복사본에서 `data/raw` 폴더 이름을 임시로 `raw_backup`으로 바꾼 뒤,
위와 같은 명령으로 서버와 화면을 실행합니다. 서버는 `data/sample/`의 CSV 두 개를 읽고 화면에는 샘플 안내가 표시됩니다.
기준 데이터로 돌아가려면 폴더 이름을 `raw`로 되돌린 뒤 서버를 다시 시작합니다.

## 기준 건수 검증

`python src/clean.py`를 실행하면 정리 후 5,462곳, 월요일 22시 208곳, 월요일 24시 46곳이 출력됩니다.

## 인증키 (선택)
데이터를 새로 수집할 때만 필요합니다. 인증키가 없어도 위 실행은 그대로 됩니다.
1. 공공데이터포털에서 "국립중앙의료원_전국 약국 정보 조회 서비스" 활용신청
2. `.env.example`을 복사해 `.env`를 만들고 `PHARMACY_API_KEY=`에 키 입력
3. `python src/collect.py`

새로 수집한 약국 데이터는 `data/raw/pharmacy_seoul_raw_YYYYMMDD_HHMMSS.csv`에 저장됩니다.
서버와 건수 검증은 기존 `data/raw/pharmacy_seoul_raw.csv`(2026-11-19 기준 파일)를 사용합니다.

`.env`는 GitHub에 올리지 않습니다.
