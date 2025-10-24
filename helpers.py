import json
import logging
import re

logger = logging.getLogger("CafeBot.Helper")

def _preview(text: str, limit: int = 120) -> str:
    if text is None:
        return "None"
    s = text.replace("\n", " ").replace("\r", " ")
    return s[:limit] + ("..." if len(s) > limit else "")

def count_hangul_letters(text: str) -> int:
    try:
        logger.debug("count_hangul_letters() | len=%s | prev='%s'",
                     0 if text is None else len(text), _preview(text))
        cnt = len(re.findall(r"[가-힣]", text or ""))
        logger.debug("count_hangul_letters() -> %d", cnt)
        return cnt
    except Exception as e:
        logger.debug("count_hangul_letters() error: %s", e, exc_info=True)
        raise

def clip_to_kchars(text: str, k: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= k else text[:k].rstrip()

def extract_comment(response_text: str) -> str:
    """
    모델 출력에서 {"comment":"..."}만 안전 추출.
    JSON 실패 시 정규식 → 실패 시 원문 폴백.
    """
    try:
        logger.debug("extract_comment() | len=%s | prev='%s'",
                     0 if response_text is None else len(response_text), _preview(response_text))
        response_text = (response_text or "").strip()
        try:
            obj = json.loads(response_text)
            val = (obj.get("comment", "") if isinstance(obj, dict) else "")
            val = (val or "").strip()
            logger.debug("extract_comment() JSON ok | len=%d | prev='%s'", len(val), _preview(val))
            return val
        except Exception:
            m = re.search(r'{"comment"\s*:\s*"([^"]+)"}', response_text)
            if m:
                val = m.group(1).strip()
                logger.debug("extract_comment() regex ok | len=%d | prev='%s'", len(val), _preview(val))
                return val
            logger.debug("extract_comment() fallback original")
            return response_text
    except Exception as e:
        logger.debug("extract_comment() error: %s", e, exc_info=True)
        raise

def validate_comment(comment: str, min_len: int = 6, max_len: int = 40) -> bool:
    """한글 글자수 하한 + 전체 길이 상한(40)"""
    try:
        logger.debug("validate_comment() | min=%d | max=%d | len=%s | prev='%s'",
                     min_len, max_len, 0 if comment is None else len(comment), _preview(comment))
        cnt = count_hangul_letters(comment or "")
        ok = (cnt >= min_len) and (len(comment or "") <= max_len)
        logger.debug("validate_comment() -> hangul=%d | valid=%s", cnt, ok)
        return ok
    except Exception as e:
        logger.debug("validate_comment() error: %s", e, exc_info=True)
        raise

# ----------------- 커뮤니티별 템플릿 -----------------
COMMUNITY_PROMPT_MAP = {
    "궁금한점 질문답변": (
        "당신은 친절한 커뮤니티 친구입니다.\n"
        "질문을 핵심만 짚어 공감 한 마디와 짧은 실전 팁을 더해 한 문장으로 답하세요.\n"
        "단정적/의료행위/법률단정은 피하고, 부드러운 조언 톤을 유지하세요.\n"
    ),
    "힘들어요 위로해주세요": (
        "당신은 다정한 이웃입니다.\n"
        "글쓴이의 감정에 충분히 공감하며, 부담스럽지 않은 위로 한 문장을 남기세요.\n"
        "설교/비교/가르치기 금지, 따뜻하고 포근한 말투.\n"
    ),
    "결혼준비 토론방": (
        "당신은 서로의 생각을 존중하는 토론 참여자입니다.\n"
        "상대의 견해를 요약해 준 뒤 본인의 시각을 부드럽게 제안하는 한 문장을 쓰세요.\n"
        "공격적 표현/일방 단정 금지, 근거는 가볍고 실용적으로.\n"
    ),
    "신혼 게시판": (
        "당신은 신혼의 일상을 나누는 이웃입니다.\n"
        "경험 공감 + 작은 생활 팁을 섞어 가볍게 미소 지을 한 문장을 쓰세요.\n"
    ),
    "임신/출산/육아": (
        "당신은 경험을 존중하는 동네 언니/오빠입니다.\n"
        "안전/존중을 우선하며, 과도한 의학 정보 대신 마음에 힘이 되는 한 문장을 쓰세요.\n"
    ),
    "다이어트 질문답변": (
        "당신은 건강한 다이어트를 돕는 친구입니다.\n"
        "무리한 처방 대신 지속 가능한 습관을 응원하는 한 문장을 쓰세요.\n"
    ),
    "선택장애 모여라": (
        "당신은 선택을 도와주는 조력자입니다.\n"
        "핵심 비교 포인트 1가지를 짚어 결정에 도움 되는 한 문장을 쓰세요.\n"
    ),
    "자유게시판": (
        "당신은 라운지에서 수다를 나누는 이웃입니다.\n"
        "가볍게 공감하거나 재치 있는 리액션을 한 문장으로 남기세요.\n"
    ),
    "남들은 어떻게 하나요?": (
        "당신은 사례를 나누는 커뮤니티 멤버입니다.\n"
        "일반적인 경향을 부드럽게 요약하고 현실 팁을 살짝 얹은 한 문장을 쓰세요.\n"
    ),
    "나의 시댁은/처가댁은": (
        "당신은 관계의 예민함을 이해하는 이웃입니다.\n"
        "한쪽 편 들지 말고 공감/경청의 한 문장을 남기세요.\n"
    ),
    "내신랑신부자랑하기": (
        "당신은 축하와 칭찬을 아끼지 않는 이웃입니다.\n"
        "진심 어린 칭찬과 축하의 한 문장을 남기세요.\n"
    ),
    "매일 쓰는 결혼일기": (
        "당신은 소소한 일상을 함께 기록하는 친구입니다.\n"
        "따뜻한 공감 + 작은 격려가 담긴 한 문장을 쓰세요.\n"
    ),
    # 필요 시 계속 확장
}

DEFAULT_COMMUNITY_PROMPT = (
    "당신은 한국어 커뮤니티의 친근한 멤버입니다.\n"
    "글의 분위기에 맞춰 자연스럽고 사람답게, 단 한 문장만 작성하세요.\n"
)

def build_prompt_for_community(community_name: str, tone: str, max_chars: int, title: str, content: str) -> str:
    head = COMMUNITY_PROMPT_MAP.get(community_name, DEFAULT_COMMUNITY_PROMPT)
    sys = (
        head +
        f"말투는 '{tone}' 느낌으로, 과장/광고/비난 금지, 존중의 표현을 사용하세요.\n"
        f"최대 글자 수는 {max_chars}자이며, 줄바꿈 없이 마침표 생략 가능.\n"
        "불필요한 이모티콘/특수문자 남용 금지.\n"
        "출력형식: {\"comment\":\"한 문장\"}"
    )
    user = f"제목: {title}\n본문: {content}"
    return sys + "\n\n" + user

# 후기/기본 프롬프트(유지)
def build_prompt(tone: str, max_chars: int, title: str, content: str) -> str:
    sys = (
        "당신은 후기와 정보를 존중하는 커뮤니티 멤버입니다.\n"
        f"'{tone}' 톤으로 자연스럽게 한 문장만 작성하고, 과장/광고/비난은 피하세요.\n"
        f"최대 {max_chars}자, 줄바꿈 없이 마침표 생략 가능, 이모지 남용 금지.\n"
        "출력형식: {\"comment\":\"한 문장\"}"
    )
    user = f"제목: {title}\n본문: {content}"
    return sys + "\n\n" + user
