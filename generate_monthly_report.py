"""
월간 보고 자동 생성 스크립트

Google Sheets에 작성된 주간 보고(3~5개)를 읽어
월간 보고 시트를 자동으로 생성합니다.

사용법:
  python generate_monthly_report.py              # 이번 달 월간 보고 생성
  python generate_monthly_report.py 2026 3       # 특정 연/월 지정
"""

import json
import sys
from calendar import monthrange
from datetime import date, timedelta

from google.oauth2 import service_account
from googleapiclient.discovery import build

CONFIG_FILE = "config.json"
SERVICE_ACCOUNT_FILE = "service_account.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


# ---------------------------------------------------------------------------
# Google Sheets 연결
# ---------------------------------------------------------------------------

def get_sheets_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return build("sheets", "v4", credentials=creds).spreadsheets()


def load_config():
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 주간 보고 시트 탐색
# ---------------------------------------------------------------------------

def get_iso_weeks_in_month(year: int, month: int) -> list[int]:
    """해당 월에 속하는 ISO 주차 번호 목록 반환 (목요일 기준)."""
    weeks = set()
    _, last_day = monthrange(year, month)
    for day in range(1, last_day + 1):
        d = date(year, month, day)
        iso_week = d.isocalendar()[1]
        # 해당 주의 목요일이 같은 달에 속할 때만 포함
        thursday = d + timedelta(days=(3 - d.weekday()))
        if thursday.month == month:
            weeks.add(iso_week)
    return sorted(weeks)


def find_weekly_sheets(service, spreadsheet_id: str, year: int, month: int, pattern: str) -> list[dict]:
    """해당 월의 주간 보고 시트를 찾아 반환."""
    weeks = get_iso_weeks_in_month(year, month)
    target_names = {
        pattern.format(year=year, week=w): w for w in weeks
    }

    meta = service.get(spreadsheetId=spreadsheet_id).execute()
    found = []
    for sheet in meta.get("sheets", []):
        title = sheet["properties"]["title"]
        if title in target_names:
            found.append({
                "title": title,
                "week": target_names[title],
                "sheet_id": sheet["properties"]["sheetId"],
            })
    return sorted(found, key=lambda s: s["week"])


# ---------------------------------------------------------------------------
# 주간 데이터 읽기
# ---------------------------------------------------------------------------

def read_sheet(service, spreadsheet_id: str, sheet_title: str) -> list[list]:
    result = (
        service.values()
        .get(spreadsheetId=spreadsheet_id, range=sheet_title)
        .execute()
    )
    return result.get("values", [])


def parse_weekly_data(rows: list[list], columns: dict) -> list[dict]:
    """헤더 행 기준으로 각 행을 dict로 변환."""
    if not rows:
        return []

    header = rows[0]
    col_index = {col_key: None for col_key in columns}
    for col_key, col_name in columns.items():
        for i, h in enumerate(header):
            if h.strip() == col_name:
                col_index[col_key] = i
                break

    records = []
    for row in rows[1:]:
        if not any(cell.strip() for cell in row if cell):
            continue
        record = {}
        for col_key, idx in col_index.items():
            if idx is not None and idx < len(row):
                record[col_key] = row[idx].strip()
            else:
                record[col_key] = ""
        records.append(record)
    return records


def to_number(value: str) -> float:
    try:
        return float(value.replace(",", "").replace("원", "").strip())
    except (ValueError, AttributeError):
        return 0.0


# ---------------------------------------------------------------------------
# 집계
# ---------------------------------------------------------------------------

def aggregate_by_channel(all_records: list[dict], channels: list[str]) -> dict:
    """채널별로 수치 합산."""
    agg: dict[str, dict] = {}
    for ch in channels:
        agg[ch] = {"impressions": 0, "clicks": 0, "conversions": 0, "revenue": 0, "cost": 0}

    for rec in all_records:
        ch = rec.get("channel", "기타")
        if ch not in agg:
            ch = "기타"
        agg[ch]["impressions"] += to_number(rec.get("impressions", "0"))
        agg[ch]["clicks"] += to_number(rec.get("clicks", "0"))
        agg[ch]["conversions"] += to_number(rec.get("conversions", "0"))
        agg[ch]["revenue"] += to_number(rec.get("revenue", "0"))
        agg[ch]["cost"] += to_number(rec.get("cost", "0"))

    return agg


def compute_totals(agg: dict) -> dict:
    totals = {"impressions": 0, "clicks": 0, "conversions": 0, "revenue": 0, "cost": 0}
    for ch_data in agg.values():
        for key in totals:
            totals[key] += ch_data[key]
    return totals


def ctr(clicks, impressions):
    return clicks / impressions * 100 if impressions else 0


def cvr(conversions, clicks):
    return conversions / clicks * 100 if clicks else 0


def roas(revenue, cost):
    return revenue / cost * 100 if cost else 0


# ---------------------------------------------------------------------------
# 월간 보고 시트 작성
# ---------------------------------------------------------------------------

def build_monthly_rows(
    year: int,
    month: int,
    weekly_sheets: list[dict],
    agg: dict,
    totals: dict,
    columns: dict,
) -> list[list]:
    """월간 보고 시트에 쓸 행 목록 구성."""
    rows = []

    # 제목
    rows.append([f"{year}년 {month}월 월간 마케팅 보고"])
    rows.append([f"집계 기간: {year}-{month:02d}-01 ~ {year}-{month:02d}-{monthrange(year, month)[1]:02d}"])
    rows.append([f"포함된 주간 보고: {', '.join(s['title'] for s in weekly_sheets)}"])
    rows.append([])

    # --- 채널별 요약 ---
    rows.append(["[채널별 실적 요약]"])
    rows.append([
        "채널",
        columns["impressions"],
        columns["clicks"],
        "CTR(%)",
        columns["conversions"],
        "CVR(%)",
        columns["revenue"],
        columns["cost"],
        "ROAS(%)",
    ])

    for ch, data in agg.items():
        rows.append([
            ch,
            int(data["impressions"]),
            int(data["clicks"]),
            round(ctr(data["clicks"], data["impressions"]), 2),
            int(data["conversions"]),
            round(cvr(data["conversions"], data["clicks"]), 2),
            int(data["revenue"]),
            int(data["cost"]),
            round(roas(data["revenue"], data["cost"]), 1),
        ])

    # 합계 행
    rows.append([
        "합계",
        int(totals["impressions"]),
        int(totals["clicks"]),
        round(ctr(totals["clicks"], totals["impressions"]), 2),
        int(totals["conversions"]),
        round(cvr(totals["conversions"], totals["clicks"]), 2),
        int(totals["revenue"]),
        int(totals["cost"]),
        round(roas(totals["revenue"], totals["cost"]), 1),
    ])
    rows.append([])

    # --- 핵심 KPI ---
    rows.append(["[핵심 KPI]"])
    rows.append(["지표", "값"])
    rows.append(["총 노출수", int(totals["impressions"])])
    rows.append(["총 클릭수", int(totals["clicks"])])
    rows.append(["전체 CTR", f"{ctr(totals['clicks'], totals['impressions']):.2f}%"])
    rows.append(["총 전환수", int(totals["conversions"])])
    rows.append(["전체 CVR", f"{cvr(totals['conversions'], totals['clicks']):.2f}%"])
    rows.append(["총 매출", f"{int(totals['revenue']):,}원"])
    rows.append(["총 광고비", f"{int(totals['cost']):,}원"])
    rows.append(["전체 ROAS", f"{roas(totals['revenue'], totals['cost']):.1f}%"])
    rows.append([])

    return rows


def write_monthly_sheet(service, spreadsheet_id: str, sheet_name: str, rows: list[list]):
    """월간 보고 시트가 없으면 생성, 있으면 데이터 덮어쓰기."""
    meta = service.get(spreadsheetId=spreadsheet_id).execute()
    existing_ids = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta.get("sheets", [])}

    requests = []
    if sheet_name not in existing_ids:
        requests.append({
            "addSheet": {
                "properties": {"title": sheet_name}
            }
        })

    if requests:
        service.batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()

    # 데이터 쓰기
    service.values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet_name}'!A1",
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()

    print(f"월간 보고 시트 '{sheet_name}' 작성 완료")


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    today = date.today()
    if len(sys.argv) == 3:
        year, month = int(sys.argv[1]), int(sys.argv[2])
    else:
        year, month = today.year, today.month

    print(f"대상: {year}년 {month}월 월간 보고 생성 중...")

    config = load_config()
    service = get_sheets_service()
    spreadsheet_id = config["spreadsheet_id"]
    columns = config["columns"]
    channels = config["channels"]

    # 1. 주간 보고 시트 탐색
    weekly_sheets = find_weekly_sheets(
        service, spreadsheet_id, year, month, config["weekly_sheet_name_pattern"]
    )

    if not weekly_sheets:
        print(f"오류: {year}년 {month}월 주간 보고 시트를 찾을 수 없습니다.")
        print(f"시트 이름 형식 확인: {config['weekly_sheet_name_pattern']}")
        sys.exit(1)

    print(f"발견된 주간 보고 시트 ({len(weekly_sheets)}개):")
    for ws in weekly_sheets:
        print(f"  - {ws['title']}")

    # 2. 전체 주간 데이터 수집
    all_records = []
    for ws in weekly_sheets:
        rows = read_sheet(service, spreadsheet_id, ws["title"])
        records = parse_weekly_data(rows, columns)
        print(f"  {ws['title']}: {len(records)}행 읽음")
        all_records.extend(records)

    if not all_records:
        print("오류: 집계할 데이터가 없습니다.")
        sys.exit(1)

    # 3. 집계
    agg = aggregate_by_channel(all_records, channels)
    totals = compute_totals(agg)

    # 4. 월간 보고 시트 작성
    monthly_sheet_name = config["monthly_sheet_name_pattern"].format(year=year, month=month)
    report_rows = build_monthly_rows(year, month, weekly_sheets, agg, totals, columns)
    write_monthly_sheet(service, spreadsheet_id, monthly_sheet_name, report_rows)

    print(f"\n완료: '{monthly_sheet_name}' 시트가 생성되었습니다.")


if __name__ == "__main__":
    main()
