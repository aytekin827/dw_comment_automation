import json
import re


def count_hangul_letters(text: str) -> int:
    """가~힣 글자만 세기 (이모지, 특수문자, 공백 제외)"""
    return len(re.findall(r"[가-힣]", text))

def extract_comment(response_text: str) -> str:
    """
    모델 출력에서 {"comment":"..."} 부분만 안전하게 추출.
    JSON형태가 아닐 경우 대비용 정규식도 포함.
    """
    response_text = response_text.strip()
    try:
        obj = json.loads(response_text)
        return obj.get("comment", "").strip()
    except Exception:
        # JSON이 아닌 경우 정규식으로 추출 시도
        match = re.search(r'{"comment"\s*:\s*"([^"]+)"}', response_text)
        if match:
            return match.group(1).strip()
        return response_text

def validate_comment(comment: str, min_len: int = 10) -> bool:
    """가-힣 글자 기준으로 길이 검증"""
    return count_hangul_letters(comment) >= min_len