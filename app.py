from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date

import streamlit as st

from flight_tracker.config import DEFAULT_CONFIG, load_config, save_config
from flight_tracker.notify import send_line_message


def run_tracker_subprocess(route_id: str, dry_run: bool) -> list[dict]:
    command = [sys.executable, "tracker.py", "--config", str(DEFAULT_CONFIG), "--route", route_id]
    if dry_run:
        command.append("--dry-run")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", env=env, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout or f"tracker.py failed with {completed.returncode}")
    return json.loads(completed.stdout)


st.set_page_config(page_title="機票追蹤器", layout="centered")
st.title("機票價格追蹤器")

config = load_config(DEFAULT_CONFIG)

st.subheader("日期與條件")
trip = config["trip"]
trip["origin"] = st.text_input("出發機場", trip.get("origin", "TPE"))
departure_default = date.fromisoformat(trip.get("departure_date", date.today().isoformat()))
return_default = date.fromisoformat(trip.get("return_date", date.today().isoformat()))
trip["departure_date"] = st.date_input("去程日期", departure_default).isoformat()
trip["return_date"] = st.date_input("回程日期", return_default).isoformat()
trip["direct_only"] = st.checkbox("只看直飛", trip.get("direct_only", True))

left, right = st.columns(2)
with left:
    trip["outbound_time"]["from"] = st.text_input("去程開始時段", trip["outbound_time"].get("from", "06:00"))
    trip["outbound_time"]["to"] = st.text_input("去程結束時段", trip["outbound_time"].get("to", "14:00"))
with right:
    trip["return_time"]["from"] = st.text_input("回程開始時段", trip["return_time"].get("from", "12:00"))
    trip["return_time"]["to"] = st.text_input("回程結束時段", trip["return_time"].get("to", "22:00"))

st.subheader("航線")
for route in config["routes"]:
    cols = st.columns([2, 2, 2])
    route["enabled"] = cols[0].checkbox(route["name"], route.get("enabled", True), key=f"enabled_{route['id']}")
    route["destination"] = cols[1].text_input("目的地", route["destination"], key=f"dest_{route['id']}")
    route["max_price"] = cols[2].number_input(
        "最高價格",
        min_value=0,
        value=int(route.get("max_price", 0)),
        step=500,
        key=f"price_{route['id']}",
    )

st.subheader("航空公司")
include_text = st.text_area("指定航空公司，一行一個", "\n".join(config["airlines"].get("include", [])))
exclude_text = st.text_area("排除航空公司，一行一個", "\n".join(config["airlines"].get("exclude", [])))
config["airlines"]["include"] = [item.strip() for item in include_text.splitlines() if item.strip()]
config["airlines"]["exclude"] = [item.strip() for item in exclude_text.splitlines() if item.strip()]

st.subheader("資料來源")
source_options = ["eztravel", "skyscanner", "mock"]
config["sources"]["enabled"] = st.multiselect("啟用來源", source_options, config["sources"].get("enabled", ["mock"]))
config["sources"]["fallback_to_mock"] = st.checkbox(
    "網站失敗時使用 mock 測流程",
    config["sources"].get("fallback_to_mock", False),
)

st.subheader("通知")
config["line"]["enabled"] = st.checkbox("啟用 LINE Messaging API 通知", config["line"].get("enabled", False))
config["line"]["to"] = st.text_area(
    "LINE_TO 使用者或群組 ID，可填多個，一行一個",
    config["line"].get("to", ""),
    height=90,
)
local_line_token = st.text_input("本機測試用 LINE_CHANNEL_ACCESS_TOKEN（不儲存）", type="password")
config["alerts"]["rise_threshold"] = st.number_input(
    "漲價通知門檻",
    min_value=0,
    value=int(config["alerts"].get("rise_threshold", 500)),
    step=100,
)

if st.button("送出 LINE 測試訊息"):
    save_config(config)
    if local_line_token:
        os.environ["LINE_CHANNEL_ACCESS_TOKEN"] = local_line_token
    if config["line"].get("to"):
        os.environ["LINE_TO"] = config["line"]["to"]

    test_config = json.loads(json.dumps(config, ensure_ascii=False))
    test_config["line"]["enabled"] = True
    try:
        send_line_message("機票追蹤器 LINE 測試訊息：如果你看到這則訊息，通知設定成功。", test_config)
        st.success("LINE 測試訊息已送出")
    except Exception as exc:
        st.error("LINE 測試失敗")
        st.code(str(exc))

if st.button("儲存 config.json", type="primary"):
    save_config(config)
    st.success(f"已儲存：{DEFAULT_CONFIG}")

st.subheader("立即測試查價")
route_options = {route["name"]: route["id"] for route in config["routes"] if route.get("enabled", True)}
selected_route_name = st.selectbox("測試航線", list(route_options.keys()))
dry_run = st.checkbox("測試模式，不發 LINE", value=True)

if st.button("開始查價"):
    save_config(config)
    with st.spinner("查價中，ezTravel 通常需要 20-40 秒..."):
        results = run_tracker_subprocess(route_options[selected_route_name], dry_run=dry_run)

    for result in results:
        if result["status"] != "ok":
            st.error(f"{result['route']} 沒有查到價格")
            if result.get("errors"):
                st.code("\n".join(result["errors"]))
            continue

        quote = result["quote"]
        summary = result["summary"]
        st.success(f"{result['route']}：{quote['airline']} TWD {quote['price']:,}")
        cols = st.columns(3)
        cols[0].metric("目前", f"{summary['current']:,}" if summary["current"] else "-")
        cols[1].metric("30天平均", f"{summary['average']:,}" if summary["average"] else "-")
        cols[2].metric("30天最低", f"{summary['lowest']:,}" if summary["lowest"] else "-")
        st.text_area("LINE 通知預覽", result["message"], height=260)
        st.link_button("打開訂票頁", quote["booking_url"])

        if result.get("errors"):
            with st.expander("其他來源狀態"):
                st.code("\n".join(result["errors"]))

st.subheader("目前設定")
st.code(json.dumps(config, ensure_ascii=False, indent=2), language="json")
