"""약국 원본 정리 + 인구 결합 + 건수 검증표 생성.

사용법 (저장소 맨 위 폴더에서):
    python src/clean.py
입력:
    data/raw/pharmacy_seoul_raw.csv                 (2026-11-19 21:58 수집, 5,471행)
    data/raw/seoul_population_by_gu_age_202610.csv  (2026년 10월, 25개 구)
출력:
    data/processed/pharmacy_clean.csv               약국 1곳 = 1행, 요일별 시작·종료(분 단위)
    data/processed/gu_summary_월_2200.csv           자치구 1개 = 1행
    reports/count_check.md                          건수 검증표

정리 규칙
    1) 시각(HHMM)은 "시×60+분"의 분 단위 정수로 바꿔 계산
    2) 값이 비어 있는 요일 = 그 요일 휴무
    3) 종료가 2400보다 크면 다음 날 새벽 (2500 = 익일 01:00), 2400 = 하루의 끝
    4) 종료가 시작보다 작으면 다음 날 새벽으로 보고 24시간을 더함 (2000~0300 → 20:00~27:00)
    5) 영업 시간(종료 − 시작)이 30분 미만인 칸은 이상값으로 보고 그 요일 휴무 처리
    6) hpid 중복, 이름·주소·전화가 같은 중복(주소는 괄호 안 내용·쉼표·띄어쓰기를 지우고 비교)은 1곳만 남김
    7) 8개 요일 시각이 모두 비어 있는 약국은 제외 (5번 처리 후 모두 비게 된 약국 포함)

심야 판정 규칙
    - 영업 중 = 시작 ≤ 기준 시각 < 종료
    - 기준 시각이 24:00 이상(자정 이후)이면 선택한 요일 칸과 다음 날 칸(기준 − 24:00)을 함께 봄
      (일요일의 다음 날은 월요일)
    - 공휴일(8)을 고르면 자정 이후에도 공휴일 칸만 봄
"""
import os
import re
import sys

import pandas as pd

RAW = os.path.join("data", "raw", "pharmacy_seoul_raw.csv")
POP = os.path.join("data", "raw", "seoul_population_by_gu_age_202610.csv")
OUT_DIR = os.path.join("data", "processed")
REPORT_DIR = "reports"

DAYS = {1: "월", 2: "화", 3: "수", 4: "목", 5: "금", 6: "토", 7: "일", 8: "공휴일"}
NEXT_DAY = {1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 7: 1}
POP_BASES = {"전체": "총인구수", "65세이상": "65세이상", "9세이하": "9세이하"}
MIN_OPEN_MINUTES = 30


def hhmm_to_min(v):
    """'2130' → 1290분. 비어 있으면 None."""
    if pd.isna(v) or str(v).strip() == "":
        return None
    s = str(v).strip().zfill(4)
    return int(s[:2]) * 60 + int(s[2:])


def norm_addr(a):
    return re.sub(r"[\s,]+", "", re.sub(r"\(.*?\)", "", str(a)))


def clean_pharmacy(raw):
    df = raw.copy()
    st = {"원본": len(df), "보정_2400초과": 0, "보정_종료<시작": 0, "이상값_칸": 0, "이상값_목록": []}
    time_cols = [f"dutyTime{d}{t}" for d in DAYS for t in ("s", "c")]
    originally_empty = df[time_cols].isna().all(axis=1)

    for d in DAYS:
        start = df[f"dutyTime{d}s"].map(hhmm_to_min)
        end = df[f"dutyTime{d}c"].map(hhmm_to_min)
        st["보정_2400초과"] += int((end.notna() & (end > 24 * 60)).sum())
        reverse = start.notna() & end.notna() & (end < start)
        st["보정_종료<시작"] += int(reverse.sum())
        end = end.where(~reverse, end + 24 * 60)
        bad = start.notna() & ((end - start) < MIN_OPEN_MINUTES)
        st["이상값_칸"] += int(bad.sum())
        for i in df.index[bad]:
            st["이상값_목록"].append((df.at[i, "gu"], df.at[i, "dutyName"], DAYS[d],
                                    f"{df.at[i, f'dutyTime{d}s']}~{df.at[i, f'dutyTime{d}c']}"))
        df[f"open_{d}"] = start.where(~bad)
        df[f"close_{d}"] = end.where(~bad)

    dup_id = df["hpid"].duplicated()
    df["addr_norm"] = df["dutyAddr"].map(norm_addr)
    dup_same = df.duplicated(["dutyName", "addr_norm", "dutyTel1"]) & ~dup_id
    now_empty = df[[f"open_{d}" for d in DAYS]].isna().all(axis=1)
    empty_after_bad = now_empty & ~originally_empty

    st["제거_hpid중복"] = int(dup_id.sum())
    st["제거_이름주소전화중복"] = int(dup_same.sum())
    st["제거_원래결측"] = int((originally_empty & ~dup_id & ~dup_same).sum())
    st["제거_이상값후결측"] = int((empty_after_bad & ~dup_id & ~dup_same).sum())
    df = df[~dup_id & ~dup_same & ~now_empty].copy()
    st["정리후"] = len(df)

    keep = ["gu", "hpid", "dutyName", "dutyAddr", "dutyTel1", "wgs84Lat", "wgs84Lon"]
    keep += [f"{k}_{d}" for d in DAYS for k in ("open", "close")]
    return df[keep], st


def _covers(df, day, minute):
    o, c = df[f"open_{day}"], df[f"close_{day}"]
    return o.notna() & (o <= minute) & (minute < c)


def open_at(df, day, minute):
    """day 요일 밤, minute(0~1799)에 영업 중인 약국. 1440 이상 = 그 밤의 자정 이후."""
    hit = _covers(df, day, minute)
    if minute >= 24 * 60 and day in NEXT_DAY:
        hit = hit | _covers(df, NEXT_DAY[day], minute - 24 * 60)
    return df[hit]


def summarize(clean, pop, day, minute):
    night = open_at(clean, day, minute)
    cnt = night.groupby("gu").size().rename("심야약국수")
    total = clean.groupby("gu").size().rename("전체약국수")
    g = pop[["자치구", "총인구수", "65세이상", "9세이하"]].rename(columns={"자치구": "gu"})
    out = g.merge(total, on="gu", how="left").merge(cnt, on="gu", how="left")
    out[["전체약국수", "심야약국수"]] = out[["전체약국수", "심야약국수"]].fillna(0).astype(int)
    for name, col in POP_BASES.items():
        out[f"10만명당_{name}"] = (out["심야약국수"] / out[col] * 100000).round(2)
    return out.sort_values("10만명당_전체").reset_index(drop=True), len(night)


def main():
    for p in (RAW, POP):
        if not os.path.exists(p):
            sys.exit(f"[오류] 파일이 없습니다: {p}")
    raw = pd.read_csv(RAW, dtype=str, encoding="utf-8-sig")
    pop = pd.read_csv(POP, encoding="utf-8-sig")

    clean, st = clean_pharmacy(raw)
    os.makedirs(OUT_DIR, exist_ok=True)
    clean.to_csv(os.path.join(OUT_DIR, "pharmacy_clean.csv"), index=False, encoding="utf-8-sig")

    gu_ph, gu_pop = set(clean["gu"]), set(pop["자치구"])
    matched = gu_ph & gu_pop

    summ, n22 = summarize(clean, pop, day=1, minute=22 * 60)
    summ.to_csv(os.path.join(OUT_DIR, "gu_summary_월_2200.csv"), index=False, encoding="utf-8-sig")
    n24 = len(open_at(clean, 1, 24 * 60))
    n02 = len(open_at(clean, 1, 26 * 60))

    removed = st["제거_hpid중복"] + st["제거_이름주소전화중복"] + st["제거_원래결측"] + st["제거_이상값후결측"]
    lines = [
        "# 건수 검증표 (clean.py 자동 생성)",
        "",
        "행 단위: 약국 단계는 약국 1곳, 결합 단계는 자치구 1개",
        "",
        "| 단계 | 식 | 건수 |",
        "| --- | --- | --- |",
        f"| 원본 | API 수집 결과 | {st['원본']:,} |",
        f"| 제거: hpid 중복 | | {st['제거_hpid중복']} |",
        f"| 제거: 이름·주소·전화 중복 | | {st['제거_이름주소전화중복']} |",
        f"| 제거: 8개 요일 영업시간 전체 결측 | | {st['제거_원래결측']} |",
        f"| 제거: 이상값(영업 30분 미만) 휴무 처리 후 전체 빈칸 | | {st['제거_이상값후결측']} |",
        f"| 정리 후 | {st['원본']:,} − {removed} | {st['정리후']:,} |",
        f"| 보정: 종료 2400 초과 (요일 칸 수) | 다음 날 새벽으로 해석 | {st['보정_2400초과']} |",
        f"| 보정: 종료 < 시작 (요일 칸 수) | 24시간 더함 | {st['보정_종료<시작']} |",
        f"| 이상값: 영업 30분 미만 (요일 칸 수) | 그 요일 휴무 처리 | {st['이상값_칸']} |",
        f"| 구 단위 집계 합계 | 구별 전체 약국 수의 합 | {int(summ['전체약국수'].sum()):,} |",
        f"| 인구와 결합 | 전체 = 성공 + 실패 | {len(gu_ph)} = {len(matched)} + {len(gu_ph - matched)} |",
        f"| 인구 합계 확인 | 25개 구 총인구 합 | {int(pop['총인구수'].sum()):,} |",
        f"| 예시: 월요일 22시 영업 중 | | {n22} |",
        f"| 예시: 월요일 24시 영업 중 | 다음 날 칸 포함 | {n24} |",
        f"| 예시: 월요일 밤 02시 영업 중 | 다음 날 칸 포함 | {n02} |",
        "",
        "## 이상값(영업 30분 미만) 목록",
        "",
        "| 구 | 약국 | 요일 | 원본 시각 |",
        "| --- | --- | --- | --- |",
    ] + [f"| {g} | {n} | {d} | {t} |" for g, n, d, t in st["이상값_목록"]]
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(os.path.join(REPORT_DIR, "count_check.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("\n".join(lines))
    print("\n=== 월요일 22시, 인구 10만 명당 심야 약국 수 (낮은 순) ===")
    print(summ[["gu", "심야약국수", "총인구수", "10만명당_전체", "10만명당_65세이상", "10만명당_9세이하"]].to_string(index=False))


if __name__ == "__main__":
    main()
