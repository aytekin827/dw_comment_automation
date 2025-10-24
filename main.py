import json
import logging
import os
import random
import time
# GUI
import tkinter as tk
from dataclasses import asdict
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

# Selenium
import pyperclip
# OpenAI
from openai import OpenAI
from selenium import webdriver
from selenium.webdriver import ActionChains, Keys
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# Local
from config import (DEFAULT_OPENAI_MODEL, LENGTH_CHOICES, LENGTH_TO_MAX_CHARS,
                    OPENAI_MODEL_CHOICES, TONE_CHOICES, Config)
from helpers import (build_prompt, build_prompt_for_community, clip_to_kchars,
                     extract_comment, validate_comment)

communities_dict: Dict[str, str] = {
    "자유게시판":"114","궁금한점 질문답변":"34","힘들어요 위로해주세요":"191","매일 쓰는 결혼일기":"458",
    "결혼준비 전문정보":"459","남들은 어떻게 하나요?":"437","자주묻는질문(FAQ)":"142","다이어트 질문답변":"190",
    "결혼준비 토론방":"113","나의 시댁은/처가댁은":"192","선택장애 모여라":"115","내신랑신부자랑하기":"160",
    "나만의 요리비법":"193","신랑신부 갈등과 해소":"194","내가 결혼하는 이유":"195","허니문지역선정이유":"161",
    "결혼준비 자료실":"91","다이렉트블로거":"121","데이트 맛집 소개":"196","신혼 게시판":"154",
    "임신/출산/육아":"155","미용/시술/건강관리":"453",
}


review_dict : Dict[str, str] = {
    "업체후기(다이렉트)": "134","타사와 비교한 다이렉트": "351","업체후기(박람회)": "144","업체후기(웨딩홀)": "147",
    "업체후기(웨딩통합)": "135","업체후기(스튜디오)": "41","업체후기(드레스)": "157","업체후기(메이크업)": "158",
    "업체후기(혼수)": "136","후기(가전)": "280","후기(신혼혼수)": "328","후기(프로포즈)": "148",
    "후기(상견례)": "149","후기(신혼집)": "150","후기(인테리어)": "151","후기(다이어트)": "189",
    "후기(온라인박람회)": "139","후기(신혼생활)": "456","후기(임신출산육아)": "457","예식완료 후 총평가": "350",
    "본식허니문리얼중계": "159","내 웨딩사진 자랑하기": "170","우리 결혼합니다": "123","우리 결혼했어요": "124",
    "내 계약내용 공개": "125","담당자 칭찬과 추천 ": "126",
}


PREFS_PATH = Path(os.path.expanduser("~/.dw_automation_prefs.json"))


class InMemoryLogHandler(logging.Handler):
    def __init__(self):
        super().__init__(); self.records = []
    def emit(self, record):
        self.records.append((record.levelno, self.format(record)))

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("다이렉트 카페 좋아요/댓글 자동봇")
        self.geometry("600x1000")

        self.cfg = Config()
        self.bot: Optional[NaverCafeBot] = None

        self.mem_handler = InMemoryLogHandler()
        self.logger = self._setup_logger(logging.INFO)

        # UI 상태
        self.var_id = tk.StringVar()
        self.var_pw = tk.StringVar()
        self.var_api = tk.StringVar()
        self.var_show_api = tk.BooleanVar(value=False)
        self.var_show_pw  = tk.BooleanVar(value=False)
        self.var_remember = tk.BooleanVar(value=False)  # ← 내 정보 기억하기

        self.var_model = tk.StringVar(value=DEFAULT_OPENAI_MODEL)
        self.var_temperature = tk.DoubleVar(value=self.cfg.temperature)

        self.var_tone = tk.StringVar(value=self.cfg.tone)
        self.var_length = tk.StringVar(value=self.cfg.length_label)

        self.var_target = tk.IntVar(value=10)
        self.var_perpage = tk.IntVar(value=50)
        self.var_maxpages = tk.IntVar(value=100)
        self.var_do_comment = tk.BooleanVar(value=True)
        self.var_do_like = tk.BooleanVar(value=True)

        self.var_log_visible = tk.BooleanVar(value=True)
        self.var_log_level = tk.StringVar(value="INFO")

        self.comm_listbox = None
        self.review_listbox = None

        self._build_ui_vertical_compact()
        self._load_prefs_if_exists()  # ← 앱 시작 시 자동 로드

    # ----- 로컬 저장/로드 -----
    def _load_prefs_if_exists(self):
        if PREFS_PATH.exists():
            try:
                data = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
                # 필드 로드 (없으면 스킵)
                self.var_id.set(data.get("naver_id",""))
                self.var_pw.set(data.get("naver_pw",""))
                self.var_api.set(data.get("openai_api_key",""))
                self.var_model.set(data.get("openai_model", DEFAULT_OPENAI_MODEL))
                self.var_temperature.set(float(data.get("temperature", 0.7)))
                self.var_tone.set(data.get("tone","따뜻한"))
                self.var_length.set(data.get("length_label","중간"))
                self.var_target.set(int(data.get("target_links",10)))
                self.var_perpage.set(int(data.get("per_page_cap",50)))
                self.var_maxpages.set(int(data.get("max_pages",100)))
                self.var_do_comment.set(bool(data.get("do_comment", True)))
                self.var_do_like.set(bool(data.get("do_like", True)))
                self.var_remember.set(True)  # 저장 파일이 있으면 기본 체크로 표시
                self.logger.info("로컬 환경설정을 불러왔습니다.")
            except Exception as e:
                self.logger.warning(f"환경설정 로드 실패: {e}")
        self._refresh_log_view()

    def _save_prefs(self):
        data = {
            "naver_id": self.var_id.get().strip(),
            "naver_pw": self.var_pw.get().strip(),              # ⚠ 평문 저장 주의
            "openai_api_key": self.var_api.get().strip(),       # ⚠ 평문 저장 주의
            "openai_model": self.var_model.get().strip() or DEFAULT_OPENAI_MODEL,
            "temperature": float(self.var_temperature.get() or 0.7),
            "tone": self.var_tone.get(),
            "length_label": self.var_length.get(),
            "target_links": int(self.var_target.get() or 10),
            "per_page_cap": int(self.var_perpage.get() or 50),
            "max_pages": int(self.var_maxpages.get() or 100),
            "do_comment": bool(self.var_do_comment.get()),
            "do_like": bool(self.var_do_like.get()),
        }
        try:
            PREFS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self.logger.info(f"환경설정을 저장했습니다: {PREFS_PATH}")
        except Exception as e:
            self.logger.error(f"환경설정 저장 실패: {e}", exc_info=True)

    def _clear_prefs(self):
        try:
            if PREFS_PATH.exists():
                PREFS_PATH.unlink()
                self.logger.info("저장된 환경설정을 삭제했습니다.")
        except Exception as e:
            self.logger.warning(f"환경설정 삭제 실패: {e}")

    # ----- 로거/로그뷰 -----
    def _setup_logger(self, level: int) -> logging.Logger:
        logger = logging.getLogger("CafeBot")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        fmt = logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s", "%H:%M:%S")
        ch = logging.StreamHandler(); ch.setFormatter(fmt); ch.setLevel(level); logger.addHandler(ch)
        self.mem_handler.setFormatter(fmt); self.mem_handler.setLevel(logging.DEBUG); logger.addHandler(self.mem_handler)
        return logger

    def _refresh_log_view(self, *_):
        # 텍스트 영역만 토글
        if not self.var_log_visible.get():
            if self.txt_log.winfo_ismapped():
                self.txt_log.pack_forget()  # 텍스트만 숨김
            return
        else:
            if not self.txt_log.winfo_ismapped():
                # 다시 보이게
                self.txt_log.pack(fill="both", expand=True, padx=6, pady=6)

        # 레벨 필터에 맞춰 렌더
        level_name = self.var_log_level.get().upper()
        level_value = getattr(logging, level_name, logging.INFO)

        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        for lvl, msg in self.mem_handler.records:
            if lvl >= level_value:
                self.txt_log.insert("end", msg + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    # ----- UI (압축 레이아웃) -----
    def _build_ui_vertical_compact(self):
        root = ttk.Frame(self); root.pack(fill="both", expand=True, padx=10, pady=10)

        # 1) 자격증명 (ID+PW 한 줄, API Key 한 줄, "내 정보 기억하기")
        frm_cred = ttk.LabelFrame(root, text="자격증명")
        frm_cred.pack(fill="x", padx=0, pady=(0,10))
        frm_cred.columnconfigure(0, weight=1); frm_cred.columnconfigure(1, weight=1)

        ttk.Label(frm_cred, text="네이버 아이디").grid(row=0, column=0, sticky="w", padx=6, pady=(8,2))
        ttk.Label(frm_cred, text="네이버 비밀번호").grid(row=0, column=1, sticky="w", padx=6, pady=(8,2))

        ent_id = ttk.Entry(frm_cred, textvariable=self.var_id)
        ent_id.grid(row=1, column=0, sticky="ew", padx=6, pady=(0,6))

        pw_wrap = ttk.Frame(frm_cred); pw_wrap.grid(row=1, column=1, sticky="ew", padx=6, pady=(0,6))
        pw_wrap.columnconfigure(0, weight=1)
        self.ent_pw = ttk.Entry(pw_wrap, textvariable=self.var_pw, show="*")
        self.ent_pw.grid(row=0, column=0, sticky="ew")
        ttk.Button(pw_wrap, width=3, text="👁", command=self._toggle_pw_visibility).grid(row=0, column=1, padx=(6,0))

        ttk.Label(frm_cred, text="OpenAI API Key").grid(row=2, column=0, sticky="w", padx=6, pady=(4,2), columnspan=2)
        api_frame = ttk.Frame(frm_cred); api_frame.grid(row=3, column=0, sticky="ew", padx=6, pady=(0,6), columnspan=2)
        api_frame.columnconfigure(0, weight=1)
        self.ent_api = ttk.Entry(api_frame, textvariable=self.var_api, show="*")
        self.ent_api.grid(row=0, column=0, sticky="ew")
        ttk.Button(api_frame, width=3, text="👁", command=self._toggle_api_visibility).grid(row=0, column=1, padx=(6,0))

        ttk.Checkbutton(frm_cred, text="내 정보 기억하기", variable=self.var_remember).grid(row=4, column=0, sticky="w", padx=6, pady=(0,8), columnspan=2)

        # 2) LLM 설정 (모델+Temperature 한 줄)
        frm_model = ttk.LabelFrame(root, text="LLM 설정")
        frm_model.pack(fill="x", padx=0, pady=(0,10))
        frm_model.columnconfigure(0, weight=1); frm_model.columnconfigure(1, weight=1)
        ttk.Label(frm_model, text="모델").grid(row=0, column=0, sticky="w", padx=6, pady=(8,2))
        ttk.Label(frm_model, text="Temperature").grid(row=0, column=1, sticky="w", padx=6, pady=(8,2))
        ttk.Combobox(frm_model, values=OPENAI_MODEL_CHOICES, textvariable=self.var_model).grid(row=1, column=0, sticky="ew", padx=6, pady=(0,6))
        ttk.Entry(frm_model, textvariable=self.var_temperature).grid(row=1, column=1, sticky="ew", padx=6, pady=(0,6))

        # 3) 댓글 스타일 (톤+길이 한 줄)
        frm_style = ttk.LabelFrame(root, text="댓글 스타일")
        frm_style.pack(fill="x", padx=0, pady=(0,10))
        frm_style.columnconfigure(0, weight=1); frm_style.columnconfigure(1, weight=1)
        ttk.Label(frm_style, text="톤").grid(row=0, column=0, sticky="w", padx=6, pady=(8,2))
        ttk.Label(frm_style, text="길이").grid(row=0, column=1, sticky="w", padx=6, pady=(8,2))
        ttk.Combobox(frm_style, values=TONE_CHOICES, textvariable=self.var_tone).grid(row=1, column=0, sticky="ew", padx=6, pady=(0,6))
        ttk.Combobox(frm_style, values=LENGTH_CHOICES, textvariable=self.var_length).grid(row=1, column=1, sticky="ew", padx=6, pady=(0,6))

        # 4) 크롤/실행 설정 (Target/PerPage/MaxPage 한 줄)
        frm_crawl = ttk.LabelFrame(root, text="크롤/실행 설정")
        frm_crawl.pack(fill="x", padx=0, pady=(0,10))
        for c in range(6): frm_crawl.columnconfigure(c, weight=1 if c in (1,3,5) else 0)
        ttk.Label(frm_crawl, text="Target").grid(row=0, column=0, sticky="e", padx=(6,4), pady=(8,2))
        ttk.Entry(frm_crawl, textvariable=self.var_target, width=10).grid(row=0, column=1, sticky="w", padx=(0,8), pady=(8,2))
        ttk.Label(frm_crawl, text="PerPage").grid(row=0, column=2, sticky="e", padx=(6,4), pady=(8,2))
        ttk.Entry(frm_crawl, textvariable=self.var_perpage, width=10).grid(row=0, column=3, sticky="w", padx=(0,8), pady=(8,2))
        ttk.Label(frm_crawl, text="MaxPage").grid(row=0, column=4, sticky="e", padx=(6,4), pady=(8,2))
        ttk.Entry(frm_crawl, textvariable=self.var_maxpages, width=10).grid(row=0, column=5, sticky="w", padx=(0,8), pady=(8,2))

        # 5) 액션 (댓글/좋아요 한 줄)
        frm_action = ttk.LabelFrame(root, text="액션")
        frm_action.pack(fill="x", padx=0, pady=(0,10))
        ttk.Checkbutton(frm_action, text="댓글 작성", variable=self.var_do_comment).pack(side="left", padx=(6,6), pady=(8,6))
        ttk.Checkbutton(frm_action, text="좋아요", variable=self.var_do_like).pack(side="left", padx=(0,6), pady=(8,6))

        # 6) 대상 선택 (탭: 커뮤니티/후기)
        frm_sel = ttk.LabelFrame(root, text="대상 선택"); frm_sel.pack(fill="both", padx=0, pady=(0,10))
        nb = ttk.Notebook(frm_sel); nb.pack(fill="both", expand=True, padx=6, pady=6)
        tab_comm = ttk.Frame(nb); tab_rev = ttk.Frame(nb)
        nb.add(tab_comm, text="커뮤니티"); nb.add(tab_rev, text="후기")

        ttk.Label(tab_comm, text="커뮤니티 선택(다중)").pack(anchor="w", padx=8, pady=(8,4))
        self.comm_listbox = tk.Listbox(tab_comm, selectmode="extended", height=8, exportselection=False)
        for name in communities_dict.keys(): self.comm_listbox.insert("end", name)
        self.comm_listbox.pack(fill="both", expand=True, padx=8, pady=(0,8))

        ttk.Label(tab_rev, text="후기 카테고리 선택(다중)").pack(anchor="w", padx=8, pady=(8,4))
        self.review_listbox = tk.Listbox(tab_rev, selectmode="extended", height=8, exportselection=False)
        for name in review_dict.keys(): self.review_listbox.insert("end", name)
        self.review_listbox.pack(fill="both", expand=True, padx=8, pady=(0,8))

        # 7) 실행 버튼
        frm_run = ttk.Frame(root); frm_run.pack(fill="x", padx=0, pady=(0,10))
        ttk.Button(frm_run, text="Start", command=self.on_start).pack(side="left", padx=(0,6))
        ttk.Button(frm_run, text="Stop", command=self.on_stop).pack(side="left")

        # 8) 로그
        self.frm_logs = ttk.LabelFrame(root, text="Logs")
        self.frm_logs.pack(fill="both", expand=True, padx=0, pady=(0,0))

        # 항상 보이는 상단 바(체크박스/레벨)
        self.top_log_bar = ttk.Frame(self.frm_logs)
        self.top_log_bar.pack(fill="x", padx=6, pady=(6,0))

        # ttk.Checkbutton(
        #     self.top_log_bar,
        #     text="로그 보이기",
        #     variable=self.var_log_visible,
        #     command=self._refresh_log_view
        # ).pack(side="left")

        ttk.Label(self.top_log_bar, text="레벨:").pack(side="left", padx=(10,4))
        self.cb_log_level = ttk.Combobox(
            self.top_log_bar,
            values=["DEBUG","INFO","WARNING","ERROR"],
            textvariable=self.var_log_level,
            width=10
        )
        self.cb_log_level.pack(side="left")
        self.cb_log_level.bind("<<ComboboxSelected>>", self._refresh_log_view)

        # 토글 대상: 텍스트 영역(처음엔 보이도록 pack)
        self.txt_log = tk.Text(self.frm_logs, state="disabled", wrap="word", height=16)
        self.txt_log.pack(fill="both", expand=True, padx=6, pady=6)

    # ----- 토글 -----
    def _toggle_api_visibility(self):
        if self.var_show_api.get():
            self.ent_api.configure(show="*"); self.var_show_api.set(False)
        else:
            self.ent_api.configure(show=""); self.var_show_api.set(True)
    def _toggle_pw_visibility(self):
        if self.var_show_pw.get():
            self.ent_pw.configure(show="*"); self.var_show_pw.set(False)
        else:
            self.ent_pw.configure(show=""); self.var_show_pw.set(True)

    # ----- 실행 -----
    def on_start(self):
        communities = [self.comm_listbox.get(i) for i in self.comm_listbox.curselection()]
        reviews = [self.review_listbox.get(i) for i in self.review_listbox.curselection()]
        if not (communities or reviews):
            messagebox.showwarning("선택 필요","커뮤니티 또는 후기 카테고리를 최소 1개 이상 선택하세요."); return

        # 설정 반영
        self.cfg.naver_id = self.var_id.get().strip()
        self.cfg.naver_pw = self.var_pw.get().strip()
        self.cfg.openai_api_key = self.var_api.get().strip()
        self.cfg.openai_model = self.var_model.get().strip() or DEFAULT_OPENAI_MODEL
        self.cfg.temperature = float(self.var_temperature.get() or 0.7)
        self.cfg.tone = self.var_tone.get(); self.cfg.length_label = self.var_length.get()
        self.cfg.target_links = max(1, int(self.var_target.get() or 1))
        self.cfg.per_page_cap = max(1, int(self.var_perpage.get() or 10))
        self.cfg.max_pages = max(1, int(self.var_maxpages.get() or 10))
        self.cfg.do_comment = self.var_do_comment.get(); self.cfg.do_like = self.var_do_like.get()
        self.cfg.communities = communities; self.cfg.reviews = reviews

        if not self.cfg.naver_id or not self.cfg.naver_pw:
            messagebox.showerror("로그인","네이버 아이디/비밀번호를 입력하세요."); return
        if not self.cfg.openai_api_key:
            messagebox.showerror("OpenAI","OpenAI API Key를 입력하세요."); return

        # 내 정보 기억하기 저장/삭제
        if self.var_remember.get():
            self._save_prefs()
        else:
            self._clear_prefs()

        self.mem_handler.records.clear()
        self.logger.info(f"Starting with config: {asdict(self.cfg)}"); self._refresh_log_view()

        try:
            bot = NaverCafeBot(self.cfg, self.logger); self.bot = bot
            bot.open_browser(); bot.login()

            for comm_name in self.cfg.communities:
                menu_id = communities_dict.get(comm_name)
                if not menu_id: self.logger.warning(f"Unknown community: {comm_name}"); continue
                bot.go_to_menu(menu_id)
                links = bot.collect_post_links(self.cfg.target_links, self.cfg.per_page_cap, self.cfg.max_pages)
                self.logger.info(f"[Community:{comm_name}] Collected {len(links)} links.")
                for link in links:
                    bot.driver.get(link); time.sleep(1.0)
                    if self.cfg.do_comment: bot.write_comment(comm_name, is_review=False)
                    if self.cfg.do_like: bot.press_like()

            for rev_name in self.cfg.reviews:
                menu_id = review_dict.get(rev_name)
                if not menu_id: self.logger.warning(f"Unknown review category: {rev_name}"); continue
                bot.go_to_menu(menu_id)
                links = bot.collect_post_links(self.cfg.target_links, self.cfg.per_page_cap, self.cfg.max_pages)
                self.logger.info(f"[Review:{rev_name}] Collected {len(links)} links.")
                for link in links:
                    bot.driver.get(link); time.sleep(1.0)
                    if self.cfg.do_comment: bot.write_comment(rev_name, is_review=True)
                    if self.cfg.do_like: bot.press_like()

            self.logger.info("All done.")
        except Exception as e:
            self.logger.error(f"Run failed: {e}", exc_info=True); messagebox.showerror("Error", str(e))
        finally:
            self._refresh_log_view()

    def on_stop(self):
        if self.bot:
            try: self.bot.close_browser()
            except Exception: pass
            self.bot = None
        self.logger.info("Stopped."); self._refresh_log_view()


class NaverCafeBot:
    def __init__(self, cfg: Config, logger: logging.Logger):
        self.cfg = cfg; self.logger = logger
        self.driver: Optional[webdriver.Chrome] = None
        self._seen: set[str] = set(); self.current_page = 1
        self._openai: Optional[OpenAI] = None

    def _ensure_openai(self):
        if self._openai is None:
            self._openai = OpenAI(api_key=self.cfg.openai_api_key)

    def _generate_comment(self, title: str, content: str, *, category_name: str, is_review: bool) -> str:
        self._ensure_openai()
        max_chars = LENGTH_TO_MAX_CHARS.get(self.cfg.length_label, 40)
        prompt = (
            build_prompt(self.cfg.tone, max_chars, title, content)
            if is_review else
            build_prompt_for_community(category_name, self.cfg.tone, max_chars, title, content)
        )
        resp = self._openai.responses.create(
            model=self.cfg.openai_model,
            input=prompt,
            temperature=self.cfg.temperature,
            max_output_tokens=self.cfg.max_output_tokens,  # ✅ 여기!
        )
        text = getattr(resp, "output_text", "").strip()
        comment = extract_comment(text).strip()
        # comment = clip_to_kchars(comment, max_chars)
        # if not validate_comment(comment, min_len=6, max_len=40):
        #     comment = clip_to_kchars(comment.split("\n")[0].strip(), max_chars)
        # if not validate_comment(comment, min_len=6, max_len=LENGTH_TO_MAX_CHARS.get(self.cfg.length_label, 44)):
        #     raise ValueError("생성 댓글이 길이/형식 규칙을 충족하지 않습니다.")
        return comment

    # === 이하 브라우저/네비/수집/액션은 동일 ===
    def open_browser(self):
        opts = webdriver.ChromeOptions()
        opts.add_argument("--disable-gpu"); opts.add_argument("--no-sandbox")
        service = ChromeService(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=opts)
        self.logger.info("Chrome session started.")

    def close_browser(self):
        if self.driver: self.driver.quit(); self.driver=None; self.logger.info("Chrome session closed.")

    def login(self):
        assert self.driver
        self.driver.get(self.cfg.base_url); time.sleep(1.6)
        if not self.cfg.naver_id or not self.cfg.naver_pw: raise RuntimeError("NAVER ID/Password가 비어 있습니다.")
        id_input = self.driver.find_element(By.ID, "id"); id_input.click()
        pyperclip.copy(self.cfg.naver_id); ActionChains(self.driver).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform(); time.sleep(0.7)
        pw_input = self.driver.find_element(By.ID, "pw"); pw_input.click()
        pyperclip.copy(self.cfg.naver_pw); ActionChains(self.driver).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform(); time.sleep(0.7)
        self.driver.find_element(By.ID, "log.login").click(); time.sleep(2.0); self.logger.info("Logged in successfully.")

    def go_to_menu(self, menu_id: str):
        assert self.driver
        url = self.cfg.cafe_base.format(menu_id=menu_id); self.driver.get(url); time.sleep(1.2)
        self.current_page = 1; self.logger.debug(f"Navigated to menu {menu_id}: {url}")

    def collect_post_links(self, target_count: int, per_page_cap: int, max_pages: int) -> List[str]:
        assert self.driver
        results: List[str] = []; page_idx = 0
        while len(results) < target_count and page_idx < max_pages:
            page_idx += 1
            page_links = self._scrape_links_on_current_page(per_page_cap)
            page_links = [u.split('?')[0] for u in page_links if u]
            unique_new = [u for u in page_links if u not in self._seen]; self._seen.update(unique_new)
            for u in unique_new:
                if u not in results:
                    results.append(u)
                    if len(results) >= target_count: break
            self.logger.debug(f"Page {self.current_page} collected {len(unique_new)} new links. Total: {len(results)}")
            if len(results) >= target_count: break
            if not self._go_to_next_page(): self.logger.debug("No more pages or failed to move next."); break
        return results

    def _scrape_links_on_current_page(self, per_page_cap: int = 50) -> List[str]:
        links: List[str] = []
        try: self.driver.switch_to.frame("cafe_main")
        except Exception: pass
        try:
            anchors = self.driver.find_elements(By.CSS_SELECTOR, self.cfg.post_anchor_selector)
            for a in anchors[:per_page_cap]:
                try: href = a.get_attribute("href")
                except Exception: href=None
                if href: links.append(href)
        finally:
            try: self.driver.switch_to.default_content()
            except Exception: pass
        return links

    def _go_to_next_page(self) -> bool:
        assert self.driver
        try: self.driver.switch_to.default_content()
        except Exception: pass
        current_url = self.driver.current_url; parsed = urlparse(current_url); q = parse_qs(parsed.query)
        if self.current_page <= 0:
            try: self.current_page = int(q.get("page", ["1"])[0])
            except Exception: self.current_page = 1
        next_page = self.current_page + 1; q["page"] = [str(next_page)]
        new_url = urlunparse(parsed._replace(query=urlencode(q, doseq=True)))
        self.logger.debug(f"[Pagination] Move {self.current_page} -> {next_page}: {new_url}")
        try:
            self.driver.get(new_url); time.sleep(1.2); self.current_page = next_page; return True
        except Exception as e:
            self.logger.warning(f"[Pagination] failed to move page: {e}"); return False

    def write_comment(self, category_name: str, is_review: bool=False) -> int:
        assert self.driver
        try:
            try: self.driver.switch_to.frame("cafe_main")
            except Exception: pass
            title_el = WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "h3.title_text")))
            title = title_el.text
            content_el = self.driver.find_element(By.CSS_SELECTOR, "div.se-module.se-module-text")
            content = content_el.text
            comment = self._generate_comment(title, content, category_name=category_name, is_review=is_review)
            comment_box = WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "textarea.comment_inbox_text")))
            comment_box.click(); pyperclip.copy(comment)
            ActionChains(self.driver).key_down(Keys.CONTROL).send_keys("v").key_up(Keys.CONTROL).perform()
            submit_btn = self.driver.find_element(By.CSS_SELECTOR, "a.button.btn_register")
            submit_btn.click(); time.sleep(1.4)
            self.logger.info(f"Comment posted: {comment}"); return 1
        except Exception as e:
            self.logger.warning(f"[write_comment] error: {e}"); return 0
        finally:
            try: self.driver.switch_to.default_content()
            except Exception: pass

    def press_like(self) -> int:
        assert self.driver
        try:
            try: self.driver.switch_to.frame("cafe_main")
            except Exception: pass
            like_buttons = self.driver.find_elements(By.CSS_SELECTOR, "div.ReplyBox a.like_no.u_likeit_list_btn._button.off span.u_ico._icon")
            count = 0
            for like_button in like_buttons:
                like_button.click(); count += 1; time.sleep(random.uniform(1, 2.0))
            self.logger.info(f"Liked {count} items on page."); return 1
        except Exception as e:
            self.logger.warning(f"[press_like] error: {e}"); return 0
        finally:
            try: self.driver.switch_to.default_content()
            except Exception: pass


def main():
    app = App(); app.mainloop()


if __name__ == "__main__":
    main()
