import json
import logging
import os
import random
import re
import time
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import pyperclip
from openai import OpenAI
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver import ActionChains, Keys
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# ---------- 설정(환경변수) ----------
NAVER_ID   = os.getenv("NAVER_ID", "")
NAVER_PW   = os.getenv("NAVER_PW", "")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))
TARGET_COMMUNITY = os.getenv("TARGET_COMMUNITY", "결혼준비 토론방")
TARGET_COUNT = int(os.getenv("TARGET_COUNT", "10"))
PER_PAGE_CAP = int(os.getenv("PER_PAGE_CAP", "50"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "20"))
DO_COMMENT = os.getenv("DO_COMMENT", "true").lower() == "true"
DO_LIKE = os.getenv("DO_LIKE", "false").lower() == "true"

BASE_LOGIN = "https://nid.naver.com/nidlogin.login"
CAFE_BASE  = "https://cafe.naver.com/f-e/cafes/25228091/menus/{menu_id}"
POST_SELECTOR = "tbody tr:not(.board-notice) a.article"

# 커뮤니티 → 메뉴ID (필요한 항목만)
COMMUNITIES = {
    "결혼준비 토론방": "113",
}

TITLE_CANDIDATES = [
    (By.CSS_SELECTOR, "h3.title_text"),
    (By.CSS_SELECTOR, "div.ArticleTitle"),
    (By.CSS_SELECTOR, "#articleTitle"),
    (By.CSS_SELECTOR, "h2#title_area"),
]

CONTENT_CANDIDATES = [
    (By.CSS_SELECTOR, "div.se-module.se-module-text"),
    (By.CSS_SELECTOR, "div.se-component.se-text"),
    (By.CSS_SELECTOR, "div.se_component_wrap"),
    (By.CSS_SELECTOR, "div.ContentRenderer"),
    (By.CSS_SELECTOR, "#postContent"),
]

# ---------- 로깅 ----------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("Runner")

# ---------- 프롬프트 ----------
COMMUNITY_PROMPT_MAP = {
    "결혼준비 토론방": (
        "당신은 서로의 생각을 존중하는 토론 참여자입니다.\n"
        "상대의 견해를 가볍게 요약해 준 뒤 본인의 시각을 부드럽게 제안하는 한 문장을 쓰세요.\n"
        "공격적 표현/일방 단정 금지, 근거는 가볍고 실용적으로.\n"
    ),
}
DEFAULT_PROMPT_HEAD = (
    "당신은 한국어 커뮤니티의 친근한 멤버입니다.\n"
    "글의 분위기에 맞춰 자연스럽고 사람답게, 단 한 문장만 작성하세요.\n"
)

def _wait_ready(self, timeout=20):
    WebDriverWait(self.driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )

def _switch_to_cafe_main(self, timeout=20) -> bool:
    d = self.driver
    try:
        d.switch_to.default_content()
    except Exception:
        pass
    try:
        WebDriverWait(d, timeout).until(
            EC.frame_to_be_available_and_switch_to_it((By.ID, "cafe_main"))
        )
        return True
    except TimeoutException:
        return False

def _dump_debug(self, prefix="debug"):
    # 실패 시 상황 파악용 아티팩트 남기기 (Actions에서 업로드)
    import os
    import time
    ts = time.strftime("%Y%m%d_%H%M%S")
    png = f"{prefix}_{ts}.png"
    html = f"{prefix}_{ts}.html"
    try:
        self.driver.save_screenshot(png)
    except Exception:
        pass
    try:
        with open(html, "w", encoding="utf-8") as f:
            f.write(self.driver.page_source)
    except Exception:
        pass
    return png, html

def _find_first(self, locators, timeout=20):
    wait = WebDriverWait(self.driver, timeout)
    last_err = None
    for by, sel in locators:
        try:
            el = wait.until(EC.presence_of_element_located((by, sel)))
            return el
        except Exception as e:
            last_err = e
            continue
    raise last_err or TimeoutException("Element not found for any locator")

def build_prompt_for_community(community_name: str, tone: str, max_chars: int, title: str, content: str) -> str:
    head = COMMUNITY_PROMPT_MAP.get(community_name, DEFAULT_PROMPT_HEAD)
    sys = (
        head +
        f"말투는 '담백한' 느낌으로, 과장/광고/비난 금지, 존중의 표현을 사용하세요.\n"
        f"최대 글자 수는 {max_chars}자이며, 줄바꿈 없이 마침표 생략 가능.\n"
        "불필요한 이모티콘/특수문자 남용 금지.\n"
        "출력형식: {\"comment\":\"한 문장\"}"
    )
    user = f"제목: {title}\n본문: {content}"
    return sys + "\n\n" + user

def extract_comment(text: str) -> str:
    text = (text or "").strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "comment" in obj:
            return (obj["comment"] or "").strip()
    except Exception:
        pass
    m = re.search(r'{"comment"\s*:\s*"([^"]+)"}', text)
    return (m.group(1).strip() if m else text)

def smart_clip_korean(text: str, k: int) -> str:
    text = (text or "").strip()
    if len(text) <= k: return text
    boundary = ["요!", "어요", "아요", "합니다.", "해요.", "다.", "요.", "!", "?", "…", "~"]
    window = text[:k]
    best = None
    for b in boundary:
        idx = window.rfind(b)
        if idx != -1:
            end = idx + len(b)
            if best is None or end > best:
                best = end
    if best: return window[:best].rstrip()
    sp = window.rfind(" ")
    if sp != -1 and sp >= int(k*0.6): return window[:sp].rstrip()
    return window.rstrip()

def validate_comment(c: str, min_len=6, max_len=40) -> bool:
    hangul = len(re.findall(r"[가-힣]", c or ""))
    return hangul >= min_len and len(c or "") <= max_len

# ---------- 봇 ----------
class CafeBot:
    def __init__(self):
        self.driver = None
        self._seen = set()
        self.current_page = 1
        self._openai = OpenAI(api_key=OPENAI_KEY)

    def open_browser(self):
        opts = webdriver.ChromeOptions()
        # opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--disable-dev-shm-usage")
        service = ChromeService(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=opts)
        logger.info("Chrome (headless) started")

    def close(self):
        try:
            if self.driver:
                self.driver.quit()
        finally:
            self.driver = None
            logger.info("Chrome closed")

    def login(self):
        d = self.driver
        d.get(BASE_LOGIN); time.sleep(1.5)
        d.find_element(By.ID, "id").send_keys(NAVER_ID)
        pw = d.find_element(By.ID, "pw")
        pw.click(); pw.send_keys(NAVER_PW)
        d.find_element(By.ID, "log.login").click()
        time.sleep(2.0)

        # assert self.driver
        # self.driver.get(BASE_LOGIN); time.sleep(1.6)
        # id_input = self.driver.find_element(By.ID, "id"); id_input.click()
        # pyperclip.copy(NAVER_ID); ActionChains(self.driver).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform(); time.sleep(1)
        # pw_input = self.driver.find_element(By.ID, "pw"); pw_input.click()
        # pyperclip.copy(NAVER_PW); ActionChains(self.driver).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform(); time.sleep(1)
        # self.driver.find_element(By.ID, "log.login").click(); time.sleep(2.0)
        # logger.info("Logged in")

    def go_menu(self, menu_id: str):
        url = CAFE_BASE.format(menu_id=menu_id)
        self.driver.get(url); time.sleep(1.2)
        self.current_page = 1
        logger.info(f"Go menu {menu_id}")

    def _scrape_links(self, cap: int) -> list[str]:
        links = []
        d = self.driver
        try:
            d.switch_to.frame("cafe_main")
        except Exception:
            pass
        try:
            anchors = d.find_elements(By.CSS_SELECTOR, POST_SELECTOR)
            for a in anchors[:cap]:
                href = a.get_attribute("href")
                if href: links.append(href)
        finally:
            try: d.switch_to.default_content()
            except Exception: pass
        return links

    def _next_page(self) -> bool:
        d = self.driver
        cur = d.current_url
        parsed = urlparse(cur)
        q = parse_qs(parsed.query)
        if self.current_page <= 0:
            try: self.current_page = int(q.get("page", ["1"])[0])
            except: self.current_page = 1
        nxt = self.current_page + 1
        q["page"] = [str(nxt)]
        new_url = urlunparse(parsed._replace(query=urlencode(q, doseq=True)))
        d.get(new_url); time.sleep(1.2)
        self.current_page = nxt
        logger.debug(f"Move page -> {nxt}")
        return True

    def collect_links(self, target: int, cap: int, max_pages: int) -> list[str]:
        res = []
        page = 0
        while len(res) < target and page < max_pages:
            page += 1
            page_links = [u.split("?")[0] for u in self._scrape_links(cap) if u]
            new_ones = [u for u in page_links if u not in self._seen]
            self._seen.update(new_ones)
            for u in new_ones:
                res.append(u)
                if len(res) >= target: break
            if len(res) >= target: break
            if not self._next_page(): break
        return res

    def _gen_comment(self, community_name: str, title: str, content: str) -> str:
        prompt = build_prompt_for_community(community_name, tone="담백한", max_chars=40, title=title, content=content)
        resp = self._openai.responses.create(
            model=OPENAI_MODEL,
            input=prompt,
            temperature=TEMPERATURE,
            max_output_tokens=120,  # 여유
        )
        text = getattr(resp, "output_text", "").strip()
        c = extract_comment(text).strip()
        c = smart_clip_korean(c, 40)
        if not validate_comment(c):
            c = smart_clip_korean(c.split("\n")[0].strip(), 40)
        if not validate_comment(c):
            raise RuntimeError("생성 댓글이 규칙을 충족하지 않음")
        return c

    def comment_and_like_once(self, community_name: str) -> None:
        d = self.driver
        try:
            self._wait_ready(timeout=25)

            if not self._switch_to_cafe_main(timeout=20):
                # 권한/리다이렉트/프레임 로드 실패
                self.logger.warning("cafe_main 프레임 진입 실패. 스크린샷 덤프")
                self._dump_debug("frame_fail")
                return

            # 제목/본문 파싱 (폴백 셀렉터)
            title_el = self._find_first(TITLE_CANDIDATES, timeout=20)
            title = title_el.text.strip()

            # 일부 글은 본문 셀렉터가 여러 조각이므로 join
            content_text = ""
            for by, sel in CONTENT_CANDIDATES:
                nodes = d.find_elements(by, sel)
                if nodes:
                    content_text = " ".join(n.text for n in nodes if n.text.strip())
                    if content_text.strip():
                        break

            if not content_text.strip():
                # 한 번 더 스크롤해서 레이지로드 대비
                d.execute_script("window.scrollTo(0, document.body.scrollHeight * 0.3);")
                time.sleep(0.8)
                nodes = d.find_elements(By.CSS_SELECTOR, "div.se-module.se-module-text")
                if nodes:
                    content_text = " ".join(n.text for n in nodes if n.text.strip())

            if not content_text.strip():
                self.logger.warning("본문 추출 실패. 스크린샷 덤프")
                self._dump_debug("content_fail")
                # 본문 없이도 댓글은 생성 가능 → 계속 진행할지 말지 선택
                content_text = ""

            # 댓글 작성
            if DO_COMMENT:
                comment = self._gen_comment(community_name, title, content_text)
                box = WebDriverWait(d, 15).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "textarea.comment_inbox_text"))
                )
                try: box.clear()
                except Exception: pass
                box.send_keys(comment)

                submit = self._find_first([
                    (By.CSS_SELECTOR, "a.button.btn_register"),
                    (By.CSS_SELECTOR, "button.btn_register"),
                    (By.CSS_SELECTOR, "button[type='submit']"),
                ], timeout=10)
                submit.click()
                time.sleep(1.2)
                self.logger.info(f"Comment: {comment}")

            # 좋아요 (옵션)
            if DO_LIKE:
                like_btns = d.find_elements(
                    By.CSS_SELECTOR,
                    "div.ReplyBox a.like_no.u_likeit_list_btn._button.off span.u_ico._icon"
                )
                cnt = 0
                for b in like_btns:
                    try:
                        b.click(); cnt += 1
                        time.sleep(random.uniform(0.6, 1.2))
                    except Exception:
                        pass
                self.logger.info(f"Like clicked: {cnt}")

        except TimeoutException as e:
            self.logger.error(f"[Timeout] {e}. 스크린샷 저장.")
            self._dump_debug("timeout")
            # 문제 글은 건너뛰기
        except Exception as e:
            self.logger.error(f"[comment_and_like_once] {e}", exc_info=True)
            self._dump_debug("unexpected")
        finally:
            try:
                d.switch_to.default_content()
            except Exception:
                pass


def main():
    if not NAVER_ID or not NAVER_PW or not OPENAI_KEY:
        raise SystemExit("NAVER_ID/NAVER_PW/OPENAI_API_KEY 환경변수를 설정하세요.")

    menu_id = COMMUNITIES.get(TARGET_COMMUNITY)
    if not menu_id:
        raise SystemExit(f"알 수 없는 커뮤니티명: {TARGET_COMMUNITY}")

    bot = CafeBot()
    try:
        bot.open_browser()
        bot.login()
        bot.go_menu(menu_id)
        links = bot.collect_links(1, PER_PAGE_CAP, MAX_PAGES)
        logger.info(f"Collected links: {len(links)}")

        for i, link in enumerate(links, 1):
            bot.driver.get(link); time.sleep(1.0)
            bot.comment_and_like_once(TARGET_COMMUNITY)
            logger.info(f"[{i}/{len(links)}] done")
            time.sleep(random.uniform(1.0, 5.0))
    finally:
        bot.close()

if __name__ == "__main__":
    main()
