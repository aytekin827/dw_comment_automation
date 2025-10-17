
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

# ---------------------- Prompt Templates ----------------------
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
    llm_provider: str = "openai"          # "openai" | "bedrock"
    openai_model: str = "gpt-4o-mini"
    bedrock_model_id: str = "anthropic.claude-3-haiku-20240307-v1:0"
    bedrock_region: str = "ap-northeast-2"  # Seoul
    temperature: float = 0.7

    base_url: str = "https://nid.naver.com/nidlogin.login"
    cafe_base: str = "https://cafe.naver.com/f-e/cafes/25228091/menus/{menu_id}"
    login_id_env: str = "NAVER_ID"
    login_pw_env: str = "NAVER_PASSWD"
    post_anchor_selector: str = "tbody tr:not(.board-notice) a.article"

    target_links: int = 10
    per_page_cap: int = 50
    max_pages: int = 100
    do_comment: bool = True
    do_like: bool = True
    verbose: str = "INFO"
    communities: List[str] = None

# ---------------------- LLM Client ----------------------
class LLMClient:
    def __init__(self, cfg: Config, logger: logging.Logger):
        self.cfg = cfg
        self.logger = logger
        self._openai: Optional[OpenAI] = None
        self._bedrock = None

    def _ensure_openai(self):
        if self._openai is None:
            self._openai = OpenAI()

    def _openai_generate(self, prompt: str) -> str:
        self._ensure_openai()
        resp = self._openai.responses.create(
            model=self.cfg.openai_model,
            input=prompt,
            temperature=self.cfg.temperature,
        )
        return getattr(resp, "output_text", "").strip()

    def _ensure_bedrock(self):
        if self._bedrock is None:
            self._bedrock = boto3.client("bedrock-runtime", region_name=self.cfg.bedrock_region)

    def _bedrock_generate(self, prompt: str) -> str:
        self._ensure_bedrock()
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 256,
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
            return json.dumps(data)

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

    def login(self):
        assert self.driver
        self.driver.get(self.cfg.base_url)
        time.sleep(2)

        user = os.getenv(self.cfg.login_id_env)
        pw = os.getenv(self.cfg.login_pw_env)
        if not user or not pw:
            raise RuntimeError("ENV NAVER_ID / NAVER_PASSWD not set.")

        id_input = self.driver.find_element(By.ID, "id")
        id_input.click()
        pyperclip.copy(user)
        ActionChains(self.driver).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
        time.sleep(1)

        pw_input = self.driver.find_element(By.ID, "pw")
        pw_input.click()
        pyperclip.copy(pw)
        ActionChains(self.driver).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
        time.sleep(1)

        self.driver.find_element(By.ID, "log.login").click()
        time.sleep(2)
        self.logger.info("Logged in successfully.")

    def go_to_menu(self, menu_id: str):
        assert self.driver
        url = self.cfg.cafe_base.format(menu_id=menu_id)
        self.driver.get(url)
        time.sleep(2)
        self.current_page = 1
        self.logger.debug(f"Navigated to menu {menu_id}: {url}")

    def collect_post_links(self, target_count: int, per_page_cap: int, max_pages: int, skip_fully_processed: bool = True) -> list[str]:
        assert self.driver
        results: list[str] = []
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

    def _scrape_links_on_current_page(self, per_page_cap: int = 50) -> list[str]:
        links: list[str] = []
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

    def _go_to_next_page(self, timeout: int = 10) -> bool:
        assert self.driver
        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass

        current_url = self.driver.current_url
        parsed = urlparse(current_url)
        q = parse_qs(parsed.query)

        if not hasattr(self, "current_page") or not isinstance(self.current_page, int) or self.current_page <= 0:
            try:
                self.current_page = int(q.get("page", ["1"])[0])
            except Exception:
                self.current_page = 1

        next_page = self.current_page + 1

        try:
            cur_page = int(q.get("page", ["1"])[0])
        except Exception:
            cur_page = 1
        if cur_page == next_page:
            self.current_page = next_page
            return True

        q["page"] = [str(next_page)]
        new_query = urlencode(q, doseq=True)
        new_url = urlunparse(parsed._replace(query=new_query))

        self.logger.debug(f"[Pagination] Move {cur_page} -> {next_page}: {new_url}")
        try:
            self.driver.get(new_url)
            time.sleep(1.5)
            self.current_page = next_page
            return True
        except Exception as e:
            self.logger.warning(f"[Pagination] failed to move page: {e}")
            return False

    def _community_prompt(self, community_name: str, title: str, content: str) -> str:
        tmpl = PROMPT_MAP.get(community_name) or PROMPT_MAP["__default__"]
        return tmpl.format(title=title, content=content)[:6000]

    def _generate_comment(self, community_name: str, title: str, content: str) -> str:
        prompt = self._community_prompt(community_name, title, content)
        text = self._llm.generate(prompt)
        comment = extract_comment(text).strip()
        if not validate_comment(comment, min_len=15):
            raise ValueError("생성 댓글이 길이 규칙을 충족하지 않습니다.")
        return comment

    def write_comment(self, community_name: str) -> int:
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

                comment = self._generate_comment(community_name, title, content)
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
                time.sleep(2)
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
        self.geometry("1024x700")

        # General
        self.var_headless = tk.BooleanVar(value=False)
        self.var_target = tk.IntVar(value=10)
        self.var_perpage = tk.IntVar(value=50)
        self.var_maxpages = tk.IntVar(value=100)
        self.var_do_comment = tk.BooleanVar(value=True)
        self.var_do_like = tk.BooleanVar(value=True)
        self.var_verbose = tk.StringVar(value="INFO")

        # LLM
        self.var_llm_provider = tk.StringVar(value="openai")
        self.var_openai_model = tk.StringVar(value="gpt-4o-mini")
        self.var_bedrock_model = tk.StringVar(value="anthropic.claude-3-haiku-20240307-v1:0")
        self.var_bedrock_region = tk.StringVar(value="ap-northeast-2")
        self.var_temperature = tk.DoubleVar(value=0.7)

        self.comm_listbox = None

        self._build_ui()

        self.logger = setup_logger(self._level_from_name(self.var_verbose.get()), self.txt_log)
        self.bot: Optional[NaverCafeBot] = None

    def _level_from_name(self, name: str) -> int:
        return getattr(logging, name.upper(), logging.INFO)

    def _build_ui(self):
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=10, pady=10)

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

        sep = ttk.Separator(left); sep.grid(row=11, column=0, sticky="ew", pady=(8,6))
        ttk.Label(left, text="LLM Provider").grid(row=12, column=0, sticky="w", padx=6)
        ttk.Combobox(left, values=["openai","bedrock"], textvariable=self.var_llm_provider, width=10).grid(row=13, column=0, sticky="w", padx=6, pady=(0,6))

        ttk.Label(left, text="OpenAI Model").grid(row=14, column=0, sticky="w", padx=6)
        ttk.Entry(left, textvariable=self.var_openai_model, width=24).grid(row=15, column=0, sticky="w", padx=6, pady=(0,6))

        ttk.Label(left, text="Bedrock Model ID").grid(row=16, column=0, sticky="w", padx=6)
        ttk.Entry(left, textvariable=self.var_bedrock_model, width=30).grid(row=17, column=0, sticky="w", padx=6, pady=(0,6))

        ttk.Label(left, text="Bedrock Region").grid(row=18, column=0, sticky="w", padx=6)
        ttk.Entry(left, textvariable=self.var_bedrock_region, width=14).grid(row=19, column=0, sticky="w", padx=6, pady=(0,6))

        ttk.Label(left, text="Temperature").grid(row=20, column=0, sticky="w", padx=6)
        ttk.Entry(left, textvariable=self.var_temperature, width=10).grid(row=21, column=0, sticky="w", padx=6, pady=(0,6))

        ttk.Label(left, text="Communities (multi-select)").grid(row=22, column=0, sticky="w", padx=6, pady=(8,2))
        self.comm_listbox = tk.Listbox(left, selectmode="extended", height=10, exportselection=False)
        for name in communities_dict.keys():
            self.comm_listbox.insert("end", name)
        self.comm_listbox.grid(row=23, column=0, sticky="nsew", padx=6, pady=(0,6))

        btns = ttk.Frame(left)
        btns.grid(row=24, column=0, sticky="ew", padx=6, pady=(6,0))
        ttk.Button(btns, text="Start", command=self.on_start).pack(side="left", expand=True, fill="x", padx=(0,4))
        ttk.Button(btns, text="Stop", command=self.on_stop).pack(side="left", expand=True, fill="x", padx=(4,0))

        right = ttk.LabelFrame(frm, text="Logs")
        right.pack(side="left", fill="both", expand=True)
        self.txt_log = tk.Text(right, state="disabled", wrap="word")
        self.txt_log.pack(fill="both", expand=True, padx=6, pady=6)

    def on_start(self):
        selected = [self.comm_listbox.get(i) for i in self.comm_listbox.curselection()]
        if not selected:
            messagebox.showwarning("Communities", "최소 1개 이상의 커뮤니티를 선택하세요.")
            return

        cfg = Config(
            headless=self.var_headless.get(),
            llm_provider=self.var_llm_provider.get(),
            openai_model=self.var_openai_model.get(),
            bedrock_model_id=self.var_bedrock_model.get(),
            bedrock_region=self.var_bedrock_region.get(),
            temperature=float(self.var_temperature.get() or 0.7),
            target_links=max(1, int(self.var_target.get() or 1)),
            per_page_cap=max(1, int(self.var_perpage.get() or 10)),
            max_pages=max(1, int(self.var_maxpages.get() or 10)),
            do_comment=self.var_do_comment.get(),
            do_like=self.var_do_like.get(),
            verbose=self.var_verbose.get(),
            communities=selected,
        )

        level = self._level_from_name(cfg.verbose)
        self.logger = setup_logger(level, self.txt_log)

        try:
            init_db()
            self.bot = NaverCafeBot(cfg, self.logger)
            self.logger.info(f"Starting with config: {asdict(cfg)}")
            self.bot.open_browser()
            self.bot.login()

            for comm_name in cfg.communities:
                menu_id = communities_dict.get(comm_name)
                if not menu_id:
                    self.logger.warning(f"Unknown community: {comm_name}")
                    continue

                self.bot.go_to_menu(menu_id)
                links = self.bot.collect_post_links(
                    target_count=cfg.target_links,
                    per_page_cap=cfg.per_page_cap,
                    max_pages=cfg.max_pages,
                    skip_fully_processed=True,
                )
                self.logger.info(f"[{comm_name}] Collected {len(links)} links.")

                status_map = fetch_action_status(links)
                for link in links:
                    self.bot.driver.get(link)
                    time.sleep(1.0)
                    st = status_map.get(link, {"comment": False, "like": False})
                    if cfg.do_comment and not st.get("comment"):
                        self.bot.write_comment(community_name=comm_name)
                    if cfg.do_like and not st.get("like"):
                        self.bot.press_like()

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

def main():
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()
