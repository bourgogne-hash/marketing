"""
ChatGPT에서 'CS대행 추천 회사' 쿼리 시 CS쉐어링(씨에스쉐어링) 언급 여부 및 순위를 모니터링합니다.
결과는 results/chatgpt_cs_sharing_monitor.json 에 누적 저장됩니다.
"""

import os
import re
import json
import datetime

from openai import OpenAI

QUERY = "CS대행을 맡길 수 있을만한 회사를 추천해줘"
TARGET_NAMES = ["cs쉐어링", "씨에스쉐어링", "cssharing", "cs sharing"]
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
RESULTS_FILE = os.path.join(RESULTS_DIR, "chatgpt_cs_sharing_monitor.json")


def call_chatgpt(query: str) -> str:
    client = OpenAI()  # OPENAI_API_KEY 환경변수 사용
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": query}],
        temperature=0.0,
    )
    return response.choices[0].message.content


def extract_ranked_items(text: str) -> list[str]:
    """번호 목록(1. 2. 3. ...) 또는 순서 없는 항목을 파싱해 순서대로 반환합니다."""
    # 번호 매긴 항목: "1.", "1)", "①" 등
    numbered = re.findall(
        r"(?:^|\n)\s*(?:\d+[.)】]|[①-⑳])\s*(.+)", text
    )
    if numbered:
        return [item.strip() for item in numbered]

    # 불릿 항목: "- ", "• ", "* " 등
    bulleted = re.findall(r"(?:^|\n)\s*[-•*]\s*(.+)", text)
    if bulleted:
        return [item.strip() for item in bulleted]

    # 줄 단위로 분리 (폴백)
    return [line.strip() for line in text.splitlines() if line.strip()]


def find_target_rank(items: list[str]) -> int | None:
    """items 목록에서 타겟 회사가 처음 등장하는 1-based 순위를 반환합니다. 없으면 None."""
    for idx, item in enumerate(items, start=1):
        lower = item.lower().replace(" ", "")
        if any(t.replace(" ", "") in lower for t in TARGET_NAMES):
            return idx
    return None


def target_in_text(text: str) -> bool:
    lower = text.lower().replace(" ", "")
    return any(t.replace(" ", "") in lower for t in TARGET_NAMES)


def load_results() -> list[dict]:
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_results(results: list[dict]) -> None:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def run_check() -> dict:
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(f"[{timestamp}] ChatGPT 쿼리 실행 중: {QUERY!r}")

    response_text = call_chatgpt(QUERY)
    items = extract_ranked_items(response_text)
    mentioned = target_in_text(response_text)
    rank = find_target_rank(items) if mentioned else None

    result = {
        "timestamp": timestamp,
        "mentioned": mentioned,
        "rank": rank,
        "total_items": len(items),
        "response": response_text,
    }

    if mentioned:
        print(f"  → CS쉐어링 언급됨! 순위: {rank}/{len(items)}")
    else:
        print(f"  → CS쉐어링 언급 없음 (총 {len(items)}개 항목)")

    return result


def main() -> None:
    result = run_check()

    history = load_results()
    history.append(result)
    save_results(history)

    print(f"  → 결과 저장: {RESULTS_FILE} (누적 {len(history)}건)")


if __name__ == "__main__":
    main()
