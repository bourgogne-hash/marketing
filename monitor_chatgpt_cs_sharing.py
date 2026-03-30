"""
모니터링 항목:
  1. ChatGPT에 'CS대행을 맡길 수 있을만한 회사를 추천해줘' 쿼리 시 CS쉐어링 언급 여부 및 순위
  2. 네이버에서 'cs대행' 검색 시 CS쉐어링 노출 여부 및 순위

결과는 results/chatgpt_cs_sharing_monitor.json 에 누적 저장됩니다.
"""

import os
import re
import json
import datetime
import time
import random

import requests
from bs4 import BeautifulSoup
from openai import OpenAI

# ── 공통 설정 ──────────────────────────────────────────────
TARGET_NAMES = ["cs쉐어링", "씨에스쉐어링", "cssharing", "cs sharing"]
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
RESULTS_FILE = os.path.join(RESULTS_DIR, "chatgpt_cs_sharing_monitor.json")

# ── ChatGPT 설정 ───────────────────────────────────────────
CHATGPT_QUERY = "CS대행을 맡길 수 있을만한 회사를 추천해줘"

# ── 네이버 설정 ────────────────────────────────────────────
NAVER_QUERY = "cs대행"
NAVER_SEARCH_URL = "https://search.naver.com/search.naver"
NAVER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://www.naver.com/",
}


# ── 공통 유틸 ──────────────────────────────────────────────

def target_in_text(text: str) -> bool:
    lower = text.lower().replace(" ", "")
    return any(t.replace(" ", "") in lower for t in TARGET_NAMES)


def find_target_rank(items: list[str]) -> int | None:
    for idx, item in enumerate(items, start=1):
        if target_in_text(item):
            return idx
    return None


# ── ChatGPT ────────────────────────────────────────────────

def call_chatgpt(query: str) -> str:
    client = OpenAI()  # OPENAI_API_KEY 환경변수 사용
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": query}],
        temperature=0.0,
    )
    return response.choices[0].message.content


def extract_ranked_items(text: str) -> list[str]:
    """번호 목록(1. 2. 3. ...) 또는 불릿 항목을 파싱해 순서대로 반환합니다."""
    numbered = re.findall(r"(?:^|\n)\s*(?:\d+[.)】]|[①-⑳])\s*(.+)", text)
    if numbered:
        return [item.strip() for item in numbered]
    bulleted = re.findall(r"(?:^|\n)\s*[-•*]\s*(.+)", text)
    if bulleted:
        return [item.strip() for item in bulleted]
    return [line.strip() for line in text.splitlines() if line.strip()]


def check_chatgpt() -> dict:
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(f"[{timestamp}] [ChatGPT] 쿼리: {CHATGPT_QUERY!r}")

    response_text = call_chatgpt(CHATGPT_QUERY)
    items = extract_ranked_items(response_text)
    mentioned = target_in_text(response_text)
    rank = find_target_rank(items) if mentioned else None

    if mentioned:
        print(f"  → CS쉐어링 언급됨! 순위: {rank}/{len(items)}")
    else:
        print(f"  → CS쉐어링 언급 없음 (총 {len(items)}개 항목)")

    return {
        "mentioned": mentioned,
        "rank": rank,
        "total_items": len(items),
        "response": response_text,
    }


# ── 네이버 검색 ────────────────────────────────────────────

def fetch_naver_results(query: str) -> list[str]:
    """
    네이버 통합검색 결과에서 텍스트 항목(제목+설명)을 순서대로 반환합니다.
    웹문서, 블로그, 지식iN, 쇼핑 등 모든 섹션 포함.
    """
    params = {"query": query, "sm": "top_hty", "fbm": "1"}
    resp = requests.get(
        NAVER_SEARCH_URL,
        params=params,
        headers=NAVER_HEADERS,
        timeout=15,
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    items: list[str] = []

    # 통합검색: 각 결과 카드의 제목 + 설명 텍스트를 수집
    # 네이버 HTML 구조 — 주요 셀렉터
    selectors = [
        # 웹문서·블로그·카페 결과
        "li.bx a.title_link",
        "a.title_link",
        # 파워링크(광고) 제목
        "a.lnk_tit",
        # 지식iN 제목
        "a.question",
        # 쇼핑 제품명
        "a.tit_area",
        # 일반 검색 결과 제목
        ".total_tit a",
        ".result_title a",
    ]

    seen: set[str] = set()
    for selector in selectors:
        for tag in soup.select(selector):
            text = tag.get_text(separator=" ", strip=True)
            if text and text not in seen:
                seen.add(text)
                items.append(text)

    # 폴백: 위 셀렉터로 아무것도 못 잡으면 모든 <a> 태그 텍스트
    if not items:
        for tag in soup.find_all("a"):
            text = tag.get_text(strip=True)
            if len(text) > 5 and text not in seen:
                seen.add(text)
                items.append(text)

    return items


def check_naver() -> dict:
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(f"[{timestamp}] [네이버] 검색어: {NAVER_QUERY!r}")

    # 봇 차단 방지용 짧은 랜덤 딜레이
    time.sleep(random.uniform(1.0, 2.5))

    try:
        items = fetch_naver_results(NAVER_QUERY)
        mentioned = any(target_in_text(item) for item in items)
        rank = find_target_rank(items) if mentioned else None
        error = None
    except Exception as e:
        items = []
        mentioned = False
        rank = None
        error = str(e)
        print(f"  → 오류 발생: {e}")

    if mentioned:
        print(f"  → CS쉐어링 노출됨! 순위: {rank}/{len(items)}")
    elif error is None:
        print(f"  → CS쉐어링 노출 없음 (총 {len(items)}개 항목 확인)")

    return {
        "mentioned": mentioned,
        "rank": rank,
        "total_items": len(items),
        "error": error,
    }


# ── 저장/로드 ──────────────────────────────────────────────

def load_results() -> list[dict]:
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_results(results: list[dict]) -> None:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


# ── 메인 ──────────────────────────────────────────────────

def main() -> None:
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    chatgpt_result = check_chatgpt()
    naver_result = check_naver()

    record = {
        "timestamp": timestamp,
        "chatgpt": chatgpt_result,
        "naver": naver_result,
    }

    history = load_results()
    history.append(record)
    save_results(history)

    print(f"\n결과 저장: {RESULTS_FILE} (누적 {len(history)}건)")


if __name__ == "__main__":
    main()
