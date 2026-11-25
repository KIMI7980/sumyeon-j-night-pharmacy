"""서울 25개 구 약국 정보를 API로 모아 CSV로 저장한다.

사용법:
    python collect.py
결과:
    data/raw/pharmacy_seoul_raw.csv   약국 1곳 = 1행 (API 응답 그대로)
    data/raw/collect_log.csv          구별 API 총건수 vs 실제 수집 건수 (건수 검증표용)
"""
import csv
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime

import requests
from dotenv import load_dotenv

URL = "https://apis.data.go.kr/B552657/ErmctInsttInfoInqireService/getParmacyListInfoInqire"
ROWS_PER_PAGE = 1000

GU_LIST = [
    "종로구", "중구", "용산구", "성동구", "광진구", "동대문구", "중랑구", "성북구",
    "강북구", "도봉구", "노원구", "은평구", "서대문구", "마포구", "양천구", "강서구",
    "구로구", "금천구", "영등포구", "동작구", "관악구", "서초구", "강남구", "송파구", "강동구",
]

# 요일 번호: 1=월 2=화 3=수 4=목 5=금 6=토 7=일 8=공휴일 / s=시작, c=종료 (HHMM)
TIME_COLS = [f"dutyTime{d}{t}" for d in range(1, 9) for t in ("s", "c")]
COLUMNS = (["gu", "hpid", "dutyName", "dutyAddr", "dutyTel1"] + TIME_COLS
           + ["wgs84Lat", "wgs84Lon", "postCdn1", "postCdn2"])

OUT_DIR = os.path.join("data", "raw")


def call_api(key, gu, page):
    """한 페이지를 호출해 (totalCount, items) 를 돌려준다. 실패하면 3번까지 재시도."""
    params = {"serviceKey": key, "Q0": "서울특별시", "Q1": gu,
              "pageNo": page, "numOfRows": ROWS_PER_PAGE}
    for attempt in range(1, 4):
        try:
            res = requests.get(URL, params=params, timeout=20)
            root = ET.fromstring(res.content)
            code = root.findtext(".//resultCode") or root.findtext(".//returnReasonCode")
            if code != "00":
                msg = root.findtext(".//resultMsg") or root.findtext(".//returnAuthMsg")
                raise RuntimeError(f"결과 코드 {code}: {msg}")
            total = int(root.findtext(".//totalCount") or 0)
            items = [{c.tag: (c.text or "").strip() for c in it} for it in root.findall(".//item")]
            return total, items
        except (requests.RequestException, ET.ParseError, RuntimeError) as e:
            print(f"  [재시도 {attempt}/3] {gu} {page}쪽: {e}")
            time.sleep(2 * attempt)
    raise RuntimeError(f"{gu} {page}쪽 호출을 3번 모두 실패했습니다.")


def main():
    load_dotenv()
    key = os.getenv("PHARMACY_API_KEY")
    if not key:
        sys.exit("[오류] .env 파일에 PHARMACY_API_KEY가 없습니다.")

    os.makedirs(OUT_DIR, exist_ok=True)
    all_rows, log_rows, calls = [], [], 0

    for gu in GU_LIST:
        total, items = call_api(key, gu, 1)
        calls += 1
        page = 1
        while len(items) < total:
            page += 1
            _, more = call_api(key, gu, page)
            calls += 1
            if not more:
                break
            items += more
        for it in items:
            all_rows.append({"gu": gu, **{c: it.get(c, "") for c in COLUMNS if c != "gu"}})
        status = "OK" if len(items) == total else "불일치"
        log_rows.append({"gu": gu, "api_totalCount": total, "collected": len(items), "status": status})
        print(f"{gu:5} API 총건수 {total:4} / 수집 {len(items):4}  {status}")
        time.sleep(0.3)

    raw_path = os.path.join(OUT_DIR, "pharmacy_seoul_raw.csv")
    with open(raw_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(all_rows)

    log_path = os.path.join(OUT_DIR, "collect_log.csv")
    with open(log_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["gu", "api_totalCount", "collected", "status"])
        w.writeheader()
        w.writerows(log_rows)

    ids = [r["hpid"] for r in all_rows]
    dup = len(ids) - len(set(ids))
    total_api = sum(r["api_totalCount"] for r in log_rows)
    print("\n=== 요약 ===")
    print("수집 시각:", datetime.now().strftime("%Y-%m-%d %H:%M"))
    print("API 호출 횟수:", calls)
    print("API 총건수 합:", total_api)
    print("수집한 약국 수:", len(all_rows))
    print("hpid 중복 건수:", dup)
    print("저장:", raw_path, "/", log_path)


if __name__ == "__main__":
    main()
