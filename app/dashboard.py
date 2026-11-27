"""서울 심야 약국 조회 화면. 실행: python -m streamlit run app/dashboard.py"""

import pandas as pd
import requests
import streamlit as st


API_URL = "http://127.0.0.1:8000/api/night-pharmacies"
DAYS = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일", "공휴일"]
DISTRICTS = [
    "강남구", "강동구", "강북구", "강서구", "관악구", "광진구", "구로구", "금천구",
    "노원구", "도봉구", "동대문구", "동작구", "마포구", "서대문구", "서초구", "성동구",
    "성북구", "송파구", "양천구", "영등포구", "용산구", "은평구", "종로구", "중구", "중랑구",
]
POPULATION_BASES = {"전체 인구": "전체", "65세 이상": "65세이상", "9세 이하": "9세이하"}


def display_time(minute):
    days, clock = divmod(minute, 24 * 60)
    hour, minute = divmod(clock, 60)
    prefix = {0: "", 1: "익일 "}.get(days, f"+{days}일 ")
    return f"{prefix}{hour:02d}:{minute:02d}"


def show_dashboard():
    st.set_page_config(page_title="심야 약국을 어느 구에 열까?", layout="wide")
    st.title("심야 약국을 어느 구에 열까?")
    with st.form("night-search"):
        day = st.selectbox("요일", DAYS)
        minute = st.select_slider(
            "심야 기준 시각", options=range(20 * 60, 30 * 60 + 1),
            value=22 * 60, format_func=display_time,
        )
        gu = st.selectbox("자치구", ["전체", *DISTRICTS])
        base = st.selectbox("인구 기준", list(POPULATION_BASES))
        st.form_submit_button("조회")

    hour, minutes = divmod(minute, 60)
    params = {
        "day": DAYS.index(day) + 1, "time": f"{hour:02d}:{minutes:02d}", "gu": gu,
        "population_base": POPULATION_BASES[base],
    }
    try:
        response = requests.get(API_URL, params=params, timeout=5)
    except requests.RequestException:
        st.error("API 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인해 주세요.")
        return

    if response.status_code == 422:
        detail = response.json().get("detail")
        if isinstance(detail, list):
            detail = " / ".join(f"{item['loc'][-1]}: {item['msg']}" for item in detail)
        st.warning(detail or "조회 조건을 확인해 주세요.")
        return
    if not response.ok:
        st.error(f"API 서버가 조회에 실패했습니다. (HTTP {response.status_code})")
        return

    result = response.json()
    if result["is_sample"]:
        st.warning("샘플 데이터로 조회 중입니다. 기준 데이터의 집계와 다를 수 있습니다.")
    if not result["count"]:
        st.info(result["message"] or "조건에 맞는 약국이 없습니다")
        return

    st.subheader("구별 심야 약국")
    st.caption(f"조회 결과 {result['count']:,}곳 · 서울 전체 인구 10만 명당 {result['seoul_per_100k']:.2f}곳 ({base})")
    district_table = pd.DataFrame(result["districts"]).rename(columns={
        "gu": "자치구", "population": "인구", "pharmacy_count": "심야 약국 수",
        "per_100k": "10만 명당 약국 수", "rank": "서울 순위",
    })
    st.dataframe(district_table, hide_index=True)
    st.bar_chart(district_table, x="자치구", y="10만 명당 약국 수")

    st.subheader("우선 검토 후보")
    for candidate in result["candidates"]:
        st.write(f"**{candidate['rank']}위 {candidate['gu']}** · {candidate['reason']}")

    pharmacies = pd.DataFrame(result["pharmacies"])
    st.subheader("심야 약국 지도")
    points = pharmacies.dropna(subset=["latitude", "longitude"])
    if points.empty:
        st.info("지도에 표시할 약국 좌표가 없습니다.")
    else:
        st.map(points, latitude="latitude", longitude="longitude")

    st.subheader("심야 약국 목록")
    pharmacies["종료 시각"] = pharmacies["close_minute"].map(display_time)
    pharmacy_table = pharmacies[["gu", "name", "address", "종료 시각"]].rename(
        columns={"gu": "자치구", "name": "약국명", "address": "주소"}
    )
    st.dataframe(pharmacy_table, hide_index=True)


show_dashboard()
