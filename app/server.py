"""서울 심야 약국 조회 API. 실행: python -m uvicorn app.server:app"""

import re
from contextlib import asynccontextmanager
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request

from src.clean import NEXT_DAY, POP, POP_BASES, RAW, clean_pharmacy, hhmm_to_min, open_at


ROOT = Path(__file__).resolve().parents[1]
MINUTES_PER_DAY = 24 * 60
RATE_SCALE = 100_000


@asynccontextmanager
async def lifespan(app: FastAPI):
    raw = pd.read_csv(ROOT / RAW, dtype=str, encoding="utf-8-sig")
    app.state.pharmacies, _ = clean_pharmacy(raw)
    app.state.population = pd.read_csv(ROOT / POP, encoding="utf-8-sig").rename(
        columns={"자치구": "gu"}
    )
    yield


app = FastAPI(title="서울 심야 약국 조회 API", lifespan=lifespan)


def night_minute(time: str) -> int:
    if re.fullmatch(r"[0-9]{2}:[0-5][0-9]", time):
        minute = hhmm_to_min(time.replace(":", ""))
        if minute <= 6 * 60:
            minute += MINUTES_PER_DAY
        if 20 * 60 <= minute <= 30 * 60:
            return minute
    raise HTTPException(422, "기준 시각은 20:00부터 익일 06:00까지 HH:MM 형식으로 입력하세요.")


def pharmacy_details(matches: pd.DataFrame, day: int, minute: int) -> list[dict]:
    closing = matches[f"close_{day}"]
    if minute >= MINUTES_PER_DAY and day in NEXT_DAY:
        closing = closing[(matches[f"open_{day}"] <= minute) & (minute < closing)]
        # 익일 영업시간도 선택 요일의 00:00 기준으로 환산해 종료 시각을 비교한다.
        following_day = NEXT_DAY[day]
        next_matches = open_at(matches, following_day, minute - MINUTES_PER_DAY)
        next_closing = next_matches[f"close_{following_day}"] + MINUTES_PER_DAY
        closing = pd.concat([closing, next_closing]).groupby(level=0).max()

    details = matches[["gu", "hpid", "dutyName", "dutyAddr", "wgs84Lat", "wgs84Lon"]].rename(
        columns={"dutyName": "name", "dutyAddr": "address", "wgs84Lat": "latitude", "wgs84Lon": "longitude"}
    )
    details["close_minute"] = closing.astype(int)
    details[["latitude", "longitude"]] = details[["latitude", "longitude"]].apply(pd.to_numeric, errors="coerce")
    return details.astype(object).where(details.notna(), None).to_dict("records")


@app.get("/api/night-pharmacies", summary="심야 약국과 우선 검토 후보 조회")
def night_pharmacies(
    request: Request,
    day: int = Query(1, ge=1, le=8, description="월요일 1 ~ 일요일 7, 공휴일 8"),
    time: str = Query("22:00", description="20:00 ~ 익일 06:00. 00:00과 24:00은 같은 시각"),
    gu: str = Query("전체", description="서울 자치구 이름 또는 전체"),
    population_base: str = Query("전체", description="전체, 65세이상, 9세이하"),
):
    minute = night_minute(time)
    population = request.app.state.population
    if gu != "전체" and gu not in population["gu"].values:
        raise HTTPException(422, "자치구는 서울 25개 자치구 이름 또는 '전체'를 입력하세요.")
    if population_base not in POP_BASES:
        raise HTTPException(422, "인구 기준은 '전체', '65세이상', '9세이하' 중 하나를 입력하세요.")

    all_matches = open_at(request.app.state.pharmacies, day, minute)
    matches = all_matches if gu == "전체" else all_matches[all_matches["gu"] == gu]
    population_column = POP_BASES[population_base]
    seoul_rate = len(all_matches) / int(population[population_column].sum()) * RATE_SCALE
    response = {
        "count": len(matches),
        "population_base": population_base,
        "seoul_per_100k": round(seoul_rate, 2),
        "districts": [],
        "candidates": [],
        "pharmacies": [],
        "message": None,
    }
    if matches.empty:
        response["message"] = "조건에 맞는 약국이 없습니다"
        return response

    districts = population[["gu", population_column]].rename(columns={population_column: "population"})
    counts = all_matches.groupby("gu").size()
    districts["pharmacy_count"] = districts["gu"].map(counts).fillna(0).astype(int)
    districts["per_100k"] = districts["pharmacy_count"] / districts["population"] * RATE_SCALE
    districts = districts.sort_values(["per_100k", "gu"])
    districts["rank"] = range(1, len(districts) + 1)

    for district in districts.head(3).to_dict("records"):
        reason = (
            f"{district['gu']}는 인구 10만 명당 심야 약국이 {district['per_100k']:.2f}곳입니다. "
            f"서울 전체는 {seoul_rate:.2f}곳이며, 공급이 적은 순으로 서울 25개 구 중 "
            f"{district['rank']}위입니다."
        )
        response["candidates"].append({"gu": district["gu"], "rank": district["rank"], "reason": reason})

    if gu != "전체":
        districts = districts[districts["gu"] == gu]
    response["districts"] = districts.round({"per_100k": 2}).to_dict("records")
    response["pharmacies"] = pharmacy_details(matches, day, minute)
    return response
