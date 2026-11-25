"""약국 원본 정리 + 인구 결합 + 건수 검증표 생성.

사용법:
    python clean.py
입력:
    data/raw/pharmacy_seoul_raw.csv          (collect.py 결과)
    data/raw/seoul_population_by_gu_age_202610.csv
출력:
    data/processed/pharmacy_clean.csv        약국 1곳 = 1행, 요일별 시작·종료(분 단위로 정규화)
    data/processed/gu_summary_<요일>_<시각>.csv  자치구 1개 = 1행
    reports/count_check.md                   건수 검증표

영업시간 정리 규칙
    1) 값이 비어 있는 요일 = 그 요일 휴무
    2) 종료가 2400보다 크면 다음 날 새벽 (2500 = 익일 01:00)
    3) 종료가 시작보다 작으면 다음 날 새벽으로 보고 24시간을 더함 (2000~0300 → 20:00~27:00)
    4) 8개 요일 시각이 모두 비어 있는 약국은 영업시간 정보가 없어 제외
    6) hpid가 다르더라도 이름·주소·전화가 모두 같으면 중복으로 보고 1곳만 남김
       (주소는 괄호 안 내용·쉼표·띄어쓰기를 지우고 비교)
    5) "기준 시각에 영업 중" = 시작 ≤ 기준 시각 < 종료
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
POP_BASES = {"전체": "총인구수", "65세이상": "65세이상", "9세이하": "9세이하"}


def hhmm_to_min(v):
    """'2130' → 1290분. 비어 있으면 None."""
    if pd.isna(v) or str(v).strip() == "":
        return None
    s = str(v).strip().zfill(4)
    return int(s[:2]) * 60 + int(s[2:])


def clean_pharmacy(raw):
    df = raw.copy()
    stats = {"원본": len(df), "다음날로_보정_2400초과": 0, "다음날로_보정_종료<시작": 0}

    for d in DAYS:
        s_col, c_col = f"dutyTime{d}s", f"dutyTime{d}c"
        start = df[s_col].map(hhmm_to_min)
        end = df[c_col].map(hhmm_to_min)
        over = end.notna() & (end > 24 * 60)
        stats["다음날로_보정_2400초과"] += int(over.sum())
        reverse = start.notna() & end.notna() & (end < start)
        stats["다음날로_보정_종료<시작"] += int(reverse.sum())
        end = end.where(~reverse, end + 24 * 60)
        df[f"open_{d}"] = start
        df[f"close_{d}"] = end

    no_hours = df[[f"open_{d}" for d in DAYS]].isna().all(axis=1)
    stats["제거_영업시간_전체결측"] = int(no_hours.sum())
    dup = df["hpid"].duplicated()
    stats["제거_hpid중복"] = int(dup.sum())
    # hpid는 다르지만 이름·주소·전화가 모두 같은 약국 = 같은 약국이 두 번 등록된 것으로 보고 1곳만 남김
    df["addr_norm"] = df["dutyAddr"].map(lambda a: re.sub(r"[\s,]+", "", re.sub(r"\(.*?\)", "", str(a))))
    dup2 = df.duplicated(["dutyName", "addr_norm", "dutyTel1"]) & ~dup
    stats["제거_이름주소전화중복"] = int(dup2.sum())
    stats["제거_중복_목록"] = df.loc[dup2, ["gu", "dutyName", "hpid"]].values.tolist()
    df = df[~no_hours & ~dup & ~dup2].copy()
    stats["정리후"] = len(df)

    keep = ["gu", "hpid", "dutyName", "dutyAddr", "dutyTel1", "wgs84Lat", "wgs84Lon"]
    keep += [f"{k}_{d}" for d in DAYS for k in ("open", "close")]
    return df[keep], stats


def open_at(df, day, minute):
    """day 요일, minute(0~1799) 시각에 영업 중인 약국만 돌려준다. 1440 이상 = 다음 날 새벽."""
    o, c = df[f"open_{day}"], df[f"close_{day}"]
    return df[o.notna() & (o <= minute) & (minute < c)]


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

    # 결합 검증
    gu_ph = set(clean["gu"])
    gu_pop = set(pop["자치구"])
    matched = gu_ph & gu_pop

    summ, n_night = summarize(clean, pop, day=1, minute=22 * 60)
    summ.to_csv(os.path.join(OUT_DIR, "gu_summary_월_2200.csv"), index=False, encoding="utf-8-sig")

    lines = [
        "# 건수 검증표",
        "",
        "행 단위: 약국 단계는 약국 1곳, 결합 단계는 자치구 1개",
        "",
        "| 단계 | 식 | 건수 |",
        "| --- | --- | --- |",
        f"| 원본 | API 수집 결과 | {st['원본']:,} |",
        f"| 제거: hpid 중복 | | {st['제거_hpid중복']} |",
        f"| 제거: 이름·주소·전화 중복 | | {st['제거_이름주소전화중복']} |",
        f"| 제거: 8개 요일 영업시간 전체 결측 | | {st['제거_영업시간_전체결측']} |",
        f"| 정리 후 | {st['원본']:,} − {st['제거_hpid중복']} − {st['제거_이름주소전화중복']} − {st['제거_영업시간_전체결측']} | {st['정리후']:,} |",
        f"| 보정: 종료 2400 초과 (요일 칸 수) | 다음 날 새벽으로 해석 | {st['다음날로_보정_2400초과']} |",
        f"| 보정: 종료 < 시작 (요일 칸 수) | 24시간 더함 | {st['다음날로_보정_종료<시작']} |",
        f"| 구 단위 집계 합계 | 구별 전체 약국 수의 합 | {int(summ['전체약국수'].sum()):,} |",
        f"| 인구와 결합 | 전체 = 성공 + 실패 | {len(gu_ph)} = {len(matched)} + {len(gu_ph - matched)} |",
        f"| 인구 합계 확인 | 25개 구 총인구 합 | {int(pop['총인구수'].sum()):,} |",
        f"| 예시: 월요일 22시 영업 중 | | {n_night} |",
    ]
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(os.path.join(REPORT_DIR, "count_check.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("\n".join(lines))
    print("\n=== 월요일 22시, 인구 10만 명당 심야 약국 수 (낮은 순) ===")
    print(summ[["gu", "심야약국수", "총인구수", "10만명당_전체", "10만명당_65세이상", "10만명당_9세이하"]].to_string(index=False))


if __name__ == "__main__":
    main()
