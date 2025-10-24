from dataclasses import dataclass, field
from typing import List

# OpenAI Responses API에서 텍스트 생성에 일반적으로 쓰이는 모델 예시
# 참고: 모델 개요/문서 (공식)
# - https://platform.openai.com/docs/models (개요)
# - https://openai.com/index/gpt-4-1/ (GPT-4.1 시리즈)
# - https://openai.com/index/openai-o3-mini/ (o3 mini)
OPENAI_MODEL_CHOICES: List[str] = [
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4.1-mini",
    "gpt-4.1",
    "gpt-4.1-nano",
    "o3-mini",
    "o3",
]

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"

# 톤/길이 프리셋
TONE_CHOICES = ["따뜻한", "친근한", "담백한", "유머러스한", "격려하는", "공감하는"]
LENGTH_CHOICES = ["짧게", "중간", "길게"]
LENGTH_TO_MAX_CHARS = {
    "짧게": 22,
    "중간": 33,
    "길게": 44,   # 하드캡
}

@dataclass
class Config:
    # 자격증명
    naver_id: str = ""
    naver_pw: str = ""
    openai_api_key: str = ""

    # LLM
    openai_model: str = DEFAULT_OPENAI_MODEL
    temperature: float = 0.7
    max_output_tokens: int = 150  # 한 줄 요약/댓글 용

    # 생성 스타일
    tone: str = "따뜻한"
    length_label: str = "중간"

    # 크롤링/액션
    headless: bool = False
    target_links: int = 10
    per_page_cap: int = 50
    max_pages: int = 100
    do_comment: bool = True
    do_like: bool = True
    verbose: str = "INFO"

    # 선택
    communities: list = field(default_factory=list)
    reviews: list = field(default_factory=list)

    # 사이트
    base_url: str = "https://nid.naver.com/nidlogin.login"
    cafe_base: str = "https://cafe.naver.com/f-e/cafes/25228091/menus/{menu_id}"
    post_anchor_selector: str = "tbody tr:not(.board-notice) a.article"
