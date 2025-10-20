import json
import logging
import os
import random
import time
# GUI
import tkinter as tk
from dataclasses import asdict, dataclass
from tkinter import messagebox, ttk
from typing import Dict, Iterable, List, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import boto3  # AWS Bedrock
# Selenium
import pyperclip
# Local modules
from activity_logger import (fetch_action_status, filter_unprocessed, init_db,
                             log_action)
from helper import extract_comment, validate_comment
# LLM Providers
from openai import OpenAI  # OpenAI
from selenium import webdriver
from selenium.webdriver import ActionChains, Keys
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# ---------------------- Communities ----------------------
communities_dict: Dict[str, str] = {
    "자유게시판":"114",
    "궁금한점 질문답변":"34",
    "힘들어요 위로해주세요":"191",
    "매일 쓰는 결혼일기":"458",
    "결혼준비 전문정보":"459",
    "남들은 어떻게 하나요?":"437",
    "자주묻는질문(FAQ)":"142",
    "다이어트 질문답변":"190",
    "결혼준비 토론방":"113",
    "나의 시댁은/처가댁은":"192",
    "선택장애 모여라":"115",
    "내신랑신부자랑하기":"160",
    "나만의 요리비법":"193",
    "신랑신부 갈등과 해소":"194",
    "내가 결혼하는 이유":"195",
    "허니문지역선정이유":"161",
    "결혼준비 자료실":"91",
    "다이렉트블로거":"121",
    "데이트 맛집 소개":"196",
    "신혼 게시판":"154",
    "임신/출산/육아":"155",
    "미용/시술/건강관리":"453",
}

# 후기 전용 메뉴(리뷰)
review_dict: Dict[str, str] = {
    "업체후기(다이렉트)": "134",
    "타사와 비교한 다이렉트": "351",
    "업체후기(박람회)": "144",
    "업체후기(웨딩홀)": "147",
    "업체후기(웨딩통합)": "135",
    "업체후기(스튜디오)": "41",
    "업체후기(드레스)": "157",
    "업체후기(메이크업)": "158",
    "업체후기(혼수)": "136",
    "후기(가전)": "280",
    "후기(신혼혼수)": "328",
    "후기(프로포즈)": "148",
    "후기(상견례)": "149",
    "후기(신혼집)": "150",
    "후기(인테리어)": "151",
    "후기(다이어트)": "189",
    "후기(온라인박람회)": "139",
    "후기(신혼생활)": "456",
    "후기(임신출산육아)": "457",
    "예식완료 후 총평가": "350",
    "본식허니문리얼중계": "159",
    "내 웨딩사진 자랑하기": "170",
    "우리 결혼합니다": "123",
    "우리 결혼했어요": "124",
    "내 계약내용 공개": "125",
    "담당자 칭찬과 추천 ": "126",
}

# ---------------------- Prompt Templates (Communities) ----------------------
PROMPT_MAP: Dict[str, str] = {
    "결혼준비 토론방": (
        "당신은 결혼을 앞둔 사람들이 서로의 생각을 나누는 토론방에 참여하고 있습니다.\n"
        "글의 내용을 읽고, 상대방의 입장을 공감하면서 자연스럽게 의견이나 조언을 덧붙이는 한 문장을 써보세요.\n"
        "딱딱하지 않게, 따뜻하고 대화하듯 표현하세요.\n"
        "제목: {title}\n본문: {content}\n"
        '출력형식: {{"comment":"한 문장"}}'
    ),
    "궁금한점 질문답변": (
        "당신은 친절한 커뮤니티 친구입니다.\n"
        "질문을 보고 자연스럽고 따뜻하게, 너무 길지 않게 답변해 주세요.\n"
        "조언을 건네되, '저도 비슷했어요'처럼 공감을 살짝 섞으면 좋아요.\n"
        "제목: {title}\n본문: {content}\n"
        '출력형식: {{"comment":"한 문장"}}'
    ),
    "힘들어요 위로해주세요": (
        "당신은 다정한 위로를 건네는 친구입니다.\n"
        "글쓴이의 마음에 공감하며, 따뜻하고 부드럽게 위로하는 말을 한 문장으로 적어주세요.\n"
        "너무 무겁거나 설교조가 되지 않게, 자연스럽게 감정을 담아주세요.\n"
        "제목: {title}\n본문: {content}\n"
        '출력형식: {{"comment":"한 문장"}}'
    ),
    "신혼 게시판": (
        "당신은 신혼생활을 함께 이야기하는 커뮤니티 멤버입니다.\n"
        "글의 분위기에 맞춰, 현실적이지만 따뜻한 응원이나 공감의 한마디를 써주세요.\n"
        "가볍게 웃을 수 있는 표현도 괜찮습니다.\n"
        "제목: {title}\n본문: {content}\n"
        '출력형식: {{"comment":"한 문장"}}'
    ),
    "임신/출산/육아": (
        "당신은 엄마들의 커뮤니티에서 서로 힘을 주고받는 이웃입니다.\n"
        "글쓴이의 상황을 이해하고, 공감 또는 짧은 격려 한마디를 따뜻하게 적어주세요.\n"
        "의학적 조언보다 마음을 나누는 말이 좋아요.\n"
        "제목: {title}\n본문: {content}\n"
        '출력형식: {{"comment":"한 문장"}}'
    ),
    "다이어트 질문답변": (
        "당신은 건강한 다이어트를 함께 이야기하는 커뮤니티 친구입니다.\n"
        "글을 읽고 공감하면서, 긍정적이고 힘이 되는 말을 한 문장으로 해주세요.\n"
        "훈수보다는 응원, 비판보다는 경험을 나누듯 표현하세요.\n"
        "제목: {title}\n본문: {content}\n"
        '출력형식: {{"comment":"한 문장"}}'
    ),
    "__default__": (
        "당신은 따뜻하고 공감 어린 커뮤니티 멤버입니다.\n"
        "글의 내용을 보고 자연스럽게 한 문장을 써주세요.\n"
        "너무 형식적이지 않게, 대화하듯 공감과 긍정의 톤으로 표현하세요.\n"
        "제목: {title}\n본문: {content}\n"
        '출력형식: {{"comment":"한 문장"}}'
    ),
}

# ---------------------- Prompt Templates (Reviews) ----------------------
# 후기 글은 카테고리별로 결을 살려 보다 개별화된 톤&내용 유도
PROMPT_REVIEW_MAP: Dict[str, str] = {
    # 공급업체/상품군 리뷰(사실/경험/비교 포인트를 자연스럽게)
    "업체후기(웨딩홀)": (
        "당신은 웨딩홀 후기를 읽고 공감과 감사의 말 한마디를 전하는 커뮤니티 친구입니다.\n"
        "장단점 중 1가지를 짧게 짚어주고, 실제 사용 팁이나 참고 포인트를 부드럽게 덧붙여 한 문장을 써주세요.\n"
        "과장/광고 표현 금지, 자연스러운 대화체.\n"
        "제목: {title}\n본문: {content}\n"
        '출력형식: {{"comment":"한 문장"}}'
    ),
    "업체후기(스튜디오)": (
        "스튜디오 촬영 후기를 읽고, 사진 분위기나 촬영 동선 등 실사용에서 느낀 점에 공감하며 한 문장을 써주세요.\n"
        "칭찬+현실 팁 한 가지(예: 컨셉 상의, 예약 시간대) 정도를 자연스럽게 곁들여 주세요.\n"
        "제목: {title}\n본문: {content}\n"
        '출력형식: {{"comment":"한 문장"}}'
    ),
    "업체후기(드레스)": (
        "드레스 피팅/본식 후기를 보고, 핏/원단/동선 같은 체감 포인트에 공감하며 한 문장을 부드럽게 남겨주세요.\n"
        "취향 존중, 몸매 비교 표현 지양.\n"
        "제목: {title}\n본문: {content}\n"
        '출력형식: {{"comment":"한 문장"}}'
    ),
    "업체후기(메이크업)": (
        "메이크업/헤어 후기를 읽고, 자연스러움/지속력/서비스 응대 중 하나를 짚어 공감의 한 문장을 남겨주세요.\n"
        "지나친 제품 홍보 표현은 피합니다.\n"
        "제목: {title}\n본문: {content}\n"
        '출력형식: {{"comment":"한 문장"}}'
    ),
    "업체후기(혼수)": (
        "혼수 선택/구매 후기를 읽고, 실제 생활에서 체감되는 포인트(AS, 설치, 소음 등)에 공감하며 한 문장을 남겨주세요.\n"
        "가성비/내구성처럼 실용 키워드를 가볍게 섞어도 좋습니다.\n"
        "제목: {title}\n본문: {content}\n"
        '출력형식: {{"comment":"한 문장"}}'
    ),
    "후기(가전)": (
        "신혼 가전 사용 후기를 보고, 소음/전기요금/청소 편의 같은 생활 포인트에 공감하며 한 문장을 부드럽게 남겨주세요.\n"
        "특정 브랜드 과장 금지.\n"
        "제목: {title}\n본문: {content}\n"
        '출력형식: {{"comment":"한 문장"}}'
    ),
    "후기(신혼집)": (
        "신혼집 준비/거주 후기를 읽고, 예산이나 수납/동선 같은 생활 디테일에 공감하며 한 문장을 남겨주세요.\n"
        "비교/비판보다 응원과 현실 팁을 가볍게.\n"
        "제목: {title}\n본문: {content}\n"
        '출력형식: {{"comment":"한 문장"}}'
    ),
    "후기(인테리어)": (
        "인테리어/홈스타일링 후기를 읽고, 공사 동선/자재/빛감 등 체감 포인트에 공감하며 한 문장을 써주세요.\n"
        "광고성 어조는 피하고, 감사+응원 톤.\n"
        "제목: {title}\n본문: {content}\n"
        '출력형식: {{"comment":"한 문장"}}'
    ),
    "후기(프로포즈)": (
        "프로포즈 경험담을 읽고, 따뜻한 축하와 작게 참고할만한 팁(분위기/장소/준비물)을 한 문장에 담아주세요.\n"
        "사생활 침해성 질문은 금지.\n"
        "제목: {title}\n본문: {content}\n"
        '출력형식: {{"comment":"한 문장"}}'
    ),
    "후기(상견례)": (
        "상견례 후기를 읽고, 배려/진행 팁 등 부드러운 포인트에 공감하며 한 문장을 남겨주세요.\n"
        "예의/존중의 어조 유지, 비교/비난 금지.\n"
        "제목: {title}\n본문: {content}\n"
        '출력형식: {{"comment":"한 문장"}}'
    ),
    "본식허니문리얼중계": (
        "본식/허니문 리얼 후기에서 현장감과 감정을 존중하며, 힘이 되는 한마디를 담아 한 문장을 남겨주세요.\n"
        "구체적 일정/개인정보는 묻지 않도록 합니다.\n"
        "제목: {title}\n본문: {content}\n"
        '출력형식: {{"comment":"한 문장"}}'
    ),
    "예식완료 후 총평가": (
        "예식 전체를 돌아본 총평에서 수고와 성취에 공감하며, 도움되는 키포인트 1개를 살짝 요약해 한 문장을 남겨주세요.\n"
        "과도한 평가/비교 표현은 피합니다.\n"
        "제목: {title}\n본문: {content}\n"
        '출력형식: {{"comment":"한 문장"}}'
    ),
    "내 계약내용 공개": (
        "계약/비용 공개 후기에서 용기에 공감하며, 도움이 될만한 체크포인트 1가지를 부드럽게 덧붙여 한 문장을 남겨주세요.\n"
        "개인정보/세부 계약 강요 금지.\n"
        "제목: {title}\n본문: {content}\n"
        '출력형식: {{"comment":"한 문장"}}'
    ),
    "담당자 칭찬과 추천 ": (
        "담당자 칭찬 후기를 읽고, 감사의 마음과 실무적인 장점 1가지를 자연스럽게 요약해 한 문장을 남겨주세요.\n"
        "과장/홍보성 멘트는 지양합니다.\n"
        "제목: {title}\n본문: {content}\n"
        '출력형식: {{"comment":"한 문장"}}'
    ),
    # 기본값 (리뷰 범주)
    "__default__": (
        "당신은 후기 글을 읽고 따뜻하게 공감하며, 도움이 될만한 작고 현실적인 포인트를 한 문장에 담아 남깁니다.\n"
        "광고/비교/비난 어조는 피하고, 자연스러운 대화체로 표현하세요.\n"
        "제목: {title}\n본문: {content}\n"
        '출력형식: {{"comment":"한 문장"}}'
    ),
}

# ---------------------- Logging ----------------------
class TkinterTextHandler(logging.Handler):
    def __init__(self, text_widget: tk.Text):
        super().__init__()
        self.text_widget = text_widget
    def emit(self, record):
        try:
            msg = self.format(record)
            self.text_widget.configure(state="normal")
            self.text_widget.insert("end", msg + "\n")
            self.text_widget.see("end")
            self.text_widget.configure(state="disabled")
        except Exception:
            pass

def setup_logger(level=logging.INFO, tk_text: Optional[tk.Text] = None) -> logging.Logger:
    logger = logging.getLogger("CafeBot")
    logger.setLevel(level)
    logger.handlers.clear()
    fmt = logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s", "%H:%M:%S")

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    ch.setLevel(level)
    logger.addHandler(ch)

    if tk_text is not None:
        th = TkinterTextHandler(tk_text)
        th.setFormatter(fmt)
        th.setLevel(level)
        logger.addHandler(th)

    return logger

# ---------------------- Config ----------------------
@dataclass
class Config:
    headless: bool = False
    # Credentials (set via GUI menubar, not env)
    naver_id: str = ""
    naver_pw: str = ""
    openai_api_key: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "ap-northeast-2"  # default Seoul

    # LLM settings (set via menubar)
    llm_provider: str = "openai"          # "openai" | "bedrock"
    openai_model: str = "gpt-4o-mini"
    bedrock_model_id: str = "anthropic.claude-3-haiku-20240307-v1:0"
    temperature: float = 0.7

    # Site settings
    base_url: str = "https://nid.naver.com/nidlogin.login"
    cafe_base: str = "https://cafe.naver.com/f-e/cafes/25228091/menus/{menu_id}"
    post_anchor_selector: str = "tbody tr:not(.board-notice) a.article"

    # Crawl settings
    target_links: int = 10
    per_page_cap: int = 50
    max_pages: int = 100
    do_comment: bool = True
    do_like: bool = True
    verbose: str = "INFO"  # DEBUG/INFO/WARNING/ERROR

    # selections
    communities: List[str] = None
    reviews: List[str] = None

# ---------------------- LLM Abstraction ----------------------
class LLMClient:
    """
    Abstraction layer for OpenAI and AWS Bedrock (Claude 3 family).
    Uses GUI-provided keys directly (no .env).
    """
    def __init__(self, cfg: Config, logger: logging.Logger):
        self.cfg = cfg
        self.logger = logger
        self._openai: Optional[OpenAI] = None
        self._bedrock = None

    # ---------- OpenAI ----------
    def _ensure_openai(self):
        if self._openai is None:
            if not self.cfg.openai_api_key:
                raise RuntimeError("OpenAI API Key가 설정되지 않았습니다. (메뉴 > 설정 > 자격증명)")
            self._openai = OpenAI(api_key=self.cfg.openai_api_key)

    def _openai_generate(self, prompt: str) -> str:
        self._ensure_openai()
        resp = self._openai.responses.create(
            model=self.cfg.openai_model,
            input=prompt,
            temperature=self.cfg.temperature,
            max_tokens=160,
        )
        return getattr(resp, "output_text", "").strip()

    # ---------- Bedrock (Anthropic Claude 3) ----------
    def _ensure_bedrock(self):
        if self._bedrock is None:
            if not (self.cfg.aws_access_key_id and self.cfg.aws_secret_access_key):
                raise RuntimeError("AWS 자격증명이 설정되지 않았습니다. (메뉴 > 설정 > 자격증명)")
            self._bedrock = boto3.client(
                "bedrock-runtime",
                region_name=self.cfg.aws_region or "ap-northeast-2",
                aws_access_key_id=self.cfg.aws_access_key_id,
                aws_secret_access_key=self.cfg.aws_secret_access_key,
            )

    def _bedrock_generate(self, prompt: str) -> str:
        self._ensure_bedrock()
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 160,
            "temperature": self.cfg.temperature,
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": prompt}]}
            ],
        }
        response = self._bedrock.invoke_model(
            modelId=self.cfg.bedrock_model_id,
            body=json.dumps(body),
        )
        raw = response.get("body").read()
        data = json.loads(raw)
        try:
            return data["content"][0]["text"].strip()
        except Exception:
            # Return raw JSON to surface issues in the log window
            return json.dumps(data)

    # ---------- Public API ----------
    def generate(self, prompt: str) -> str:
        provider = (self.cfg.llm_provider or "openai").lower()
        if provider == "bedrock":
            return self._bedrock_generate(prompt)
        return self._openai_generate(prompt)

# ---------------------- Bot ----------------------
class NaverCafeBot:
    def __init__(self, cfg: Config, logger: logging.Logger):
        self.cfg = cfg
        self.logger = logger
        self.driver: Optional[webdriver.Chrome] = None
        self._llm = LLMClient(cfg, logger)
        self._seen: set[str] = set()
        self.current_page = 1

    # ---------- Browser ----------
    def open_browser(self):
        chrome_options = webdriver.ChromeOptions()
        if self.cfg.headless:
            chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        service = ChromeService(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.logger.info("Chrome session started.")

    def close_browser(self):
        if self.driver:
            self.driver.quit()
            self.driver = None
            self.logger.info("Chrome session closed.")

    # ---------- Login ----------
    def login(self):
        assert self.driver
        self.driver.get(self.cfg.base_url)
        time.sleep(2)

        user = self.cfg.naver_id
        pw = self.cfg.naver_pw
        if not user or not pw:
            raise RuntimeError("NAVER ID/Password가 설정되지 않았습니다. (메뉴 > 설정 > 자격증명)")

        id_input = self.driver.find_element(By.ID, "id")
        id_input.click()
        pyperclip.copy(user)
        ActionChains(self.driver).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
        time.sleep(0.8)

        pw_input = self.driver.find_element(By.ID, "pw")
        pw_input.click()
        pyperclip.copy(pw)
        ActionChains(self.driver).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
        time.sleep(0.8)

        self.driver.find_element(By.ID, "log.login").click()
        time.sleep(2)
        self.logger.info("Logged in successfully.")

    # ---------- Navigation ----------
    def go_to_menu(self, menu_id: str):
        assert self.driver
        url = self.cfg.cafe_base.format(menu_id=menu_id)
        self.driver.get(url)
        time.sleep(2)
        self.current_page = 1
        self.logger.debug(f"Navigated to menu {menu_id}: {url}")

    # ----------------- Link Collection -----------------
    def collect_post_links(self, target_count: int, per_page_cap: int, max_pages: int, skip_fully_processed: bool = True) -> List[str]:
        assert self.driver
        results: List[str] = []
        page_idx = 0

        while len(results) < target_count and page_idx < max_pages:
            page_idx += 1
            page_links = self._scrape_links_on_current_page(per_page_cap=per_page_cap)

            page_links = [u.split('?')[0] for u in page_links if u]
            unique_new = [u for u in page_links if u not in self._seen]
            self._seen.update(unique_new)

            if skip_fully_processed and unique_new:
                unique_new = filter_unprocessed(unique_new)

            for u in unique_new:
                if u not in results:
                    results.append(u)
                    if len(results) >= target_count:
                        break

            self.logger.debug(f"Page {self.current_page} collected {len(unique_new)} new links. Total: {len(results)}")

            if len(results) >= target_count:
                break

            if not self._go_to_next_page():
                self.logger.debug("No more pages or failed to move next.")
                break

        return results

    def _scrape_links_on_current_page(self, per_page_cap: int = 50) -> List[str]:
        links: List[str] = []
        try:
            self.driver.switch_to.frame("cafe_main")
        except Exception:
            pass

        try:
            anchors = self.driver.find_elements(By.CSS_SELECTOR, self.cfg.post_anchor_selector)
            for a in anchors[:per_page_cap]:
                try:
                    href = a.get_attribute("href")
                    if href:
                        links.append(href)
                except Exception:
                    continue
        finally:
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass
        return links

    def _go_to_next_page(self) -> bool:
        assert self.driver
        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass

        current_url = self.driver.current_url
        parsed = urlparse(current_url)
        q = parse_qs(parsed.query)

        if self.current_page <= 0:
            try:
                self.current_page = int(q.get("page", ["1"])[0])
            except Exception:
                self.current_page = 1

        next_page = self.current_page + 1
        q["page"] = [str(next_page)]
        new_query = urlencode(q, doseq=True)
        new_url = urlunparse(parsed._replace(query=new_query))

        self.logger.debug(f"[Pagination] Move {self.current_page} -> {next_page}: {new_url}")
        try:
            self.driver.get(new_url)
            time.sleep(1.4)
            self.current_page = next_page
            return True
        except Exception as e:
            self.logger.warning(f"[Pagination] failed to move page: {e}")
            return False

    # ---------- Comment / Like ----------
    def _community_prompt(self, community_name: str, title: str, content: str) -> str:
        tmpl = PROMPT_MAP.get(community_name) or PROMPT_MAP["__default__"]
        return tmpl.format(title=title, content=content)[:6000]

    def _review_prompt(self, review_name: str, title: str, content: str) -> str:
        tmpl = PROMPT_REVIEW_MAP.get(review_name) or PROMPT_REVIEW_MAP["__default__"]
        return tmpl.format(title=title, content=content)[:6000]

    def _generate_comment(self, prompt: str) -> str:
        text = self._llm.generate(prompt)
        comment = extract_comment(text).strip()
        if not validate_comment(comment, min_len=15):
            # 모델이 한 문장만 생성하지 않았을 수 있으니 안전하게 첫 문장만 자르기 시도
            comment = comment.split('\n')[0].strip()
        if not validate_comment(comment, min_len=15):
            raise ValueError("생성 댓글이 길이/형식 규칙을 충족하지 않습니다.")
        return comment

    def write_comment(self, prompt_builder, category_name: str) -> int:
        """prompt_builder: callable(title, content) -> prompt string"""
        assert self.driver
        url = self.driver.current_url.split("?")[0]
        try:
            with log_action(post_url=url, action_type="comment", attempt_no=1,
                            selector_used="textarea.comment_inbox_text") as meta:
                try:
                    self.driver.switch_to.frame("cafe_main")
                except Exception:
                    pass

                title_el = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "h3.title_text"))
                )
                title = title_el.text
                content_el = self.driver.find_element(By.CSS_SELECTOR, "div.se-module.se-module-text")
                content = content_el.text

                prompt = prompt_builder(category_name, title, content)
                comment = self._generate_comment(prompt)

                meta["model"] = f"{self.cfg.llm_provider}:{self.cfg.openai_model if self.cfg.llm_provider=='openai' else self.cfg.bedrock_model_id}"
                meta["prompt_chars"] = len(title) + len(content)
                meta["comment_chars"] = len(comment)
                meta["comment_text"] = comment

                comment_box = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "textarea.comment_inbox_text"))
                )
                comment_box.click()
                pyperclip.copy(comment)
                ActionChains(self.driver).key_down(Keys.CONTROL).send_keys("v").key_up(Keys.CONTROL).perform()

                submit_btn = self.driver.find_element(By.CSS_SELECTOR, "a.button.btn_register")
                submit_btn.click()
                time.sleep(1.6)
                self.logger.info("Comment posted.")
                return 1
        except Exception as e:
            self.logger.warning(f"[write_comment] error: {e}")
            return 0
        finally:
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass

    def press_like(self) -> int:
        assert self.driver
        url = self.driver.current_url.split("?")[0]
        try:
            with log_action(post_url=url, action_type="like", attempt_no=1,
                            selector_used="div.ReplyBox a.like_no.u_likeit_list_btn._button.off span.u_ico._icon"):
                try:
                    self.driver.switch_to.frame("cafe_main")
                except Exception:
                    pass

                like_buttons = self.driver.find_elements(By.CSS_SELECTOR, "div.ReplyBox a.like_no.u_likeit_list_btn._button.off span.u_ico._icon")
                count = 0
                for like_button in like_buttons:
                    like_button.click()
                    count += 1
                    time.sleep(random.uniform(1, 2.0))
                self.logger.info(f"Liked {count} items on page.")
                return 1
        except Exception as e:
            self.logger.warning(f"[press_like] error: {e}")
            return 0
        finally:
            try:
                self.driver.switch_to.default_content()
            except Exception:
                pass

# ---------------------- GUI ----------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Naver Cafe Auto Comment & Like")
        self.geometry("1120x760")

        # state vars
        self.cfg = Config()

        # General controls
        self.var_headless = tk.BooleanVar(value=False)
        self.var_target = tk.IntVar(value=10)
        self.var_perpage = tk.IntVar(value=50)
        self.var_maxpages = tk.IntVar(value=100)
        self.var_do_comment = tk.BooleanVar(value=True)
        self.var_do_like = tk.BooleanVar(value=True)
        self.var_verbose = tk.StringVar(value="INFO")

        # multi-select holders
        self.comm_listbox = None
        self.review_listbox = None

        self._build_ui()
        self._build_menubar()

        # Logger
        self.logger = setup_logger(self._level_from_name(self.var_verbose.get()), self.txt_log)

        self.bot: Optional[NaverCafeBot] = None

    # ----- menubar -----
    def _build_menubar(self):
        mbar = tk.Menu(self)

        m_settings = tk.Menu(mbar, tearoff=False)
        m_settings.add_command(label="자격증명...", command=self._menu_credentials)
        m_settings.add_command(label="LLM 설정...", command=self._menu_llm)
        mbar.add_cascade(label="설정", menu=m_settings)

        self.config(menu=mbar)

    def _menu_credentials(self):
        win = tk.Toplevel(self)
        win.title("자격증명 설정")
        win.geometry("420x420")
        win.grab_set()

        # NAVER
        ttk.Label(win, text="NAVER ID").grid(row=0, column=0, sticky="w", padx=10, pady=(12,4))
        e_id = ttk.Entry(win)
        e_id.grid(row=1, column=0, sticky="ew", padx=10)
        e_id.insert(0, self.cfg.naver_id)

        ttk.Label(win, text="NAVER PASSWD").grid(row=2, column=0, sticky="w", padx=10, pady=(12,4))
        e_pw = ttk.Entry(win, show="*")
        e_pw.grid(row=3, column=0, sticky="ew", padx=10)
        e_pw.insert(0, self.cfg.naver_pw)

        # OpenAI
        ttk.Label(win, text="OpenAI API Key").grid(row=4, column=0, sticky="w", padx=10, pady=(12,4))
        e_oa = ttk.Entry(win, show="*")
        e_oa.grid(row=5, column=0, sticky="ew", padx=10)
        e_oa.insert(0, self.cfg.openai_api_key)

        # AWS
        ttk.Label(win, text="AWS Access Key ID").grid(row=6, column=0, sticky="w", padx=10, pady=(12,4))
        e_ak = ttk.Entry(win, show="*")
        e_ak.grid(row=7, column=0, sticky="ew", padx=10)
        e_ak.insert(0, self.cfg.aws_access_key_id)

        ttk.Label(win, text="AWS Secret Access Key").grid(row=8, column=0, sticky="w", padx=10, pady=(12,4))
        e_sk = ttk.Entry(win, show="*")
        e_sk.grid(row=9, column=0, sticky="ew", padx=10)
        e_sk.insert(0, self.cfg.aws_secret_access_key)

        ttk.Label(win, text="AWS Region").grid(row=10, column=0, sticky="w", padx=10, pady=(12,4))
        e_rg = ttk.Entry(win)
        e_rg.grid(row=11, column=0, sticky="ew", padx=10)
        e_rg.insert(0, self.cfg.aws_region)

        win.columnconfigure(0, weight=1)

        def save_and_close():
            self.cfg.naver_id = e_id.get().strip()
            self.cfg.naver_pw = e_pw.get().strip()
            self.cfg.openai_api_key = e_oa.get().strip()
            self.cfg.aws_access_key_id = e_ak.get().strip()
            self.cfg.aws_secret_access_key = e_sk.get().strip()
            self.cfg.aws_region = e_rg.get().strip() or self.cfg.aws_region
            messagebox.showinfo("저장", "자격증명 설정을 저장했습니다.")
            win.destroy()

        ttk.Button(win, text="저장", command=save_and_close).grid(row=12, column=0, sticky="e", padx=10, pady=12)

    def _menu_llm(self):
        win = tk.Toplevel(self)
        win.title("LLM 설정")
        win.geometry("420x320")
        win.grab_set()

        provider = tk.StringVar(value=self.cfg.llm_provider)
        openai_model = tk.StringVar(value=self.cfg.openai_model)
        bedrock_model = tk.StringVar(value=self.cfg.bedrock_model_id)
        temperature = tk.DoubleVar(value=self.cfg.temperature)

        ttk.Label(win, text="Provider (openai/bedrock)").grid(row=0, column=0, sticky="w", padx=10, pady=(12,4))
        cb = ttk.Combobox(win, values=["openai","bedrock"], textvariable=provider, width=12)
        cb.grid(row=1, column=0, sticky="w", padx=10)

        ttk.Label(win, text="OpenAI Model").grid(row=2, column=0, sticky="w", padx=10, pady=(12,4))
        e_om = ttk.Entry(win)
        e_om.grid(row=3, column=0, sticky="ew", padx=10)
        e_om.insert(0, openai_model.get())

        ttk.Label(win, text="Bedrock Model ID").grid(row=4, column=0, sticky="w", padx=10, pady=(12,4))
        e_bm = ttk.Entry(win)
        e_bm.grid(row=5, column=0, sticky="ew", padx=10)
        e_bm.insert(0, bedrock_model.get())

        ttk.Label(win, text="Temperature").grid(row=6, column=0, sticky="w", padx=10, pady=(12,4))
        e_tp = ttk.Entry(win)
        e_tp.grid(row=7, column=0, sticky="ew", padx=10)
        e_tp.insert(0, str(temperature.get()))

        win.columnconfigure(0, weight=1)

        def save_and_close():
            self.cfg.llm_provider = provider.get().strip() or self.cfg.llm_provider
            self.cfg.openai_model = e_om.get().strip() or self.cfg.openai_model
            self.cfg.bedrock_model_id = e_bm.get().strip() or self.cfg.bedrock_model_id
            try:
                self.cfg.temperature = float(e_tp.get())
            except Exception:
                pass
            messagebox.showinfo("저장", "LLM 설정을 저장했습니다.")
            win.destroy()

        ttk.Button(win, text="저장", command=save_and_close).grid(row=8, column=0, sticky="e", padx=10, pady=12)

    # ----- main UI -----
    def _build_ui(self):
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=10, pady=10)

        # Left: Config
        left = ttk.LabelFrame(frm, text="Config")
        left.pack(side="left", fill="y", padx=(0,10))

        ttk.Checkbutton(left, text="Headless", variable=self.var_headless).grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Label(left, text="Target Links").grid(row=1, column=0, sticky="w", padx=6)
        ttk.Entry(left, textvariable=self.var_target, width=10).grid(row=2, column=0, sticky="w", padx=6, pady=(0,6))

        ttk.Label(left, text="Per Page Cap").grid(row=3, column=0, sticky="w", padx=6)
        ttk.Entry(left, textvariable=self.var_perpage, width=10).grid(row=4, column=0, sticky="w", padx=6, pady=(0,6))

        ttk.Label(left, text="Max Pages").grid(row=5, column=0, sticky="w", padx=6)
        ttk.Entry(left, textvariable=self.var_maxpages, width=10).grid(row=6, column=0, sticky="w", padx=6, pady=(0,6))

        ttk.Checkbutton(left, text="Do Comment", variable=self.var_do_comment).grid(row=7, column=0, sticky="w", padx=6, pady=4)
        ttk.Checkbutton(left, text="Do Like", variable=self.var_do_like).grid(row=8, column=0, sticky="w", padx=6, pady=4)

        ttk.Label(left, text="Log Level").grid(row=9, column=0, sticky="w", padx=6)
        ttk.Combobox(left, values=["DEBUG", "INFO", "WARNING", "ERROR"], textvariable=self.var_verbose, width=10).grid(row=10, column=0, sticky="w", padx=6, pady=(0,6))

        # Center: selectors (Notebook with two tabs)
        center = ttk.Notebook(frm)
        center.pack(side="left", fill="both", expand=True)

        # Communities tab
        tab_comm = ttk.Frame(center)
        center.add(tab_comm, text="Communities")
        ttk.Label(tab_comm, text="커뮤니티 선택 (다중)").pack(anchor="w", padx=8, pady=(8,4))
        self.comm_listbox = tk.Listbox(tab_comm, selectmode="extended", height=14, exportselection=False)
        for name in communities_dict.keys():
            self.comm_listbox.insert("end", name)
        self.comm_listbox.pack(fill="both", expand=True, padx=8, pady=(0,8))

        # Reviews tab
        tab_rev = ttk.Frame(center)
        center.add(tab_rev, text="Reviews")
        ttk.Label(tab_rev, text="후기 카테고리 선택 (다중)").pack(anchor="w", padx=8, pady=(8,4))
        self.review_listbox = tk.Listbox(tab_rev, selectmode="extended", height=14, exportselection=False)
        for name in review_dict.keys():
            self.review_listbox.insert("end", name)
        self.review_listbox.pack(fill="both", expand=True, padx=8, pady=(0,8))

        # Right: Logs
        right = ttk.LabelFrame(frm, text="Logs")
        right.pack(side="left", fill="both", expand=True)
        self.txt_log = tk.Text(right, state="disabled", wrap="word")
        self.txt_log.pack(fill="both", expand=True, padx=6, pady=6)

        # Bottom buttons
        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=10, pady=(0,10))
        ttk.Button(btns, text="Start", command=self.on_start).pack(side="left", padx=(0,6))
        ttk.Button(btns, text="Stop", command=self.on_stop).pack(side="left")

    def _level_from_name(self, name: str) -> int:
        return getattr(logging, name.upper(), logging.INFO)

    def _refresh_logger(self):
        level = self._level_from_name(self.var_verbose.get())
        self.logger = setup_logger(level, self.txt_log)

    def on_start(self):
        # selections
        selected_comm = [self.comm_listbox.get(i) for i in self.comm_listbox.curselection()]
        selected_rev = [self.review_listbox.get(i) for i in self.review_listbox.curselection()]
        if not selected_comm and not selected_rev:
            messagebox.showwarning("선택 필요", "커뮤니티 또는 후기 카테고리를 최소 1개 이상 선택하세요.")
            return

        # build cfg from controls
        self.cfg.headless = self.var_headless.get()
        self.cfg.target_links = max(1, int(self.var_target.get() or 1))
        self.cfg.per_page_cap = max(1, int(self.var_perpage.get() or 10))
        self.cfg.max_pages = max(1, int(self.var_maxpages.get() or 10))
        self.cfg.do_comment = self.var_do_comment.get()
        self.cfg.do_like = self.var_do_like.get()
        self.cfg.verbose = self.var_verbose.get()
        self.cfg.communities = selected_comm
        self.cfg.reviews = selected_rev

        self._refresh_logger()

        try:
            init_db()
            bot = NaverCafeBot(self.cfg, self.logger)
            self.bot = bot
            self.logger.info(f"Starting with config: {asdict(self.cfg)}")

            bot.open_browser()
            bot.login()

            # 1) communities
            for comm_name in (self.cfg.communities or []):
                menu_id = communities_dict.get(comm_name)
                if not menu_id:
                    self.logger.warning(f"Unknown community: {comm_name}")
                    continue
                bot.go_to_menu(menu_id)
                links = bot.collect_post_links(
                    target_count=self.cfg.target_links,
                    per_page_cap=self.cfg.per_page_cap,
                    max_pages=self.cfg.max_pages,
                    skip_fully_processed=True,
                )
                self.logger.info(f"[Community:{comm_name}] Collected {len(links)} links.")
                status_map = fetch_action_status(links)
                for link in links:
                    bot.driver.get(link)
                    time.sleep(1.0)
                    st = status_map.get(link, {"comment": False, "like": False})
                    if self.cfg.do_comment and not st.get("comment"):
                        bot.write_comment(lambda name, t, c: bot._community_prompt(name, t, c), comm_name)
                    if self.cfg.do_like and not st.get("like"):
                        bot.press_like()

            # 2) reviews
            for rev_name in (self.cfg.reviews or []):
                menu_id = review_dict.get(rev_name)
                if not menu_id:
                    self.logger.warning(f"Unknown review category: {rev_name}")
                    continue
                bot.go_to_menu(menu_id)
                links = bot.collect_post_links(
                    target_count=self.cfg.target_links,
                    per_page_cap=self.cfg.per_page_cap,
                    max_pages=self.cfg.max_pages,
                    skip_fully_processed=True,
                )
                self.logger.info(f"[Review:{rev_name}] Collected {len(links)} links.")
                status_map = fetch_action_status(links)
                for link in links:
                    bot.driver.get(link)
                    time.sleep(1.0)
                    st = status_map.get(link, {"comment": False, "like": False})
                    if self.cfg.do_comment and not st.get("comment"):
                        bot.write_comment(lambda name, t, c: bot._review_prompt(name, t, c), rev_name)
                    if self.cfg.do_like and not st.get("like"):
                        bot.press_like()

            self.logger.info("All done.")

        except Exception as e:
            self.logger.error(f"Run failed: {e}", exc_info=True)
            messagebox.showerror("Error", str(e))

    def on_stop(self):
        if self.bot:
            try:
                self.bot.close_browser()
            except Exception:
                pass
            self.bot = None
        self.logger.info("Stopped.")

# ---------------------- Entrypoint ----------------------
def main():
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()
