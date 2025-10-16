import os
import time
from itertools import count

import pyperclip
from dotenv import load_dotenv
from helper import *
from openai import OpenAI
from selenium import webdriver
from selenium.webdriver import ActionChains, Keys
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

load_dotenv()

class NaverLoginService():

    def __init__(self):
        self.driver = None
        self.openai = OpenAI()

    def open_web_mode(self):
        self.driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()))
        self.driver.set_page_load_timeout(10)

    def close_browser(self):
        if self.driver:
            self.driver.quit()
            self.driver = None

    def login(self):
        self.driver.get("https://nid.naver.com/nidlogin.login")
        time.sleep(2)  # 페이지 로딩 대기

        test_id = os.getenv("NAVER_ID")
        test_passwd = os.getenv("NAVER_PASSWD")

        # 아이디 입력
        id_input = self.driver.find_element(By.ID, "id")
        id_input.click()
        pyperclip.copy(test_id)
        actions = ActionChains(self.driver)
        actions.key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
        time.sleep(1)  # 입력 후 잠시 대기

        # 패스워드 입력
        pw_input = self.driver.find_element(By.ID, "pw")
        pw_input.click()
        pyperclip.copy(test_passwd)
        actions = ActionChains(self.driver)
        actions.key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
        time.sleep(1)  # 입력 후 잠시 대기

        # 로그인 버튼 클릭
        self.driver.find_element(By.ID, "log.login").click()
        print("로그인 성공")
        time.sleep(1)  # 입력 후 잠시 대기

    def go_to_naver_cafe(self):
        '''다이렉트카페 결토방으로 이동'''
        self.driver.get("https://cafe.naver.com/f-e/cafes/25228091/menus/113")
        time.sleep(1)

    def get_post_list(self):
        '''게시글 목록 가져오기'''
        try:
            # 게시글 링크 추출
            posts = self.driver.find_elements(By.CSS_SELECTOR, "a.article")
            post_links = [post.get_attribute("href").split('?')[0] for post in posts][-10:]
            return post_links

        except Exception as e:
            print(f"게시글 목록 가져오기 중 오류 발생: {e}")
            return []
        finally:
            # 메인 프레임으로 돌아오기
            self.driver.switch_to.default_content()

    def write_comment(self):
        '''댓글 작성'''
        try:
            # 댓글 작성 iframe으로 전환
            self.driver.switch_to.frame("cafe_main")

            # 댓글창이 있는지 확인
            comment_section = self.driver.find_elements(By.CSS_SELECTOR, "div.comment_inbox")

            # 댓글창이 없다면 종료
            if not comment_section:
                print("댓글창이 없습니다.")
                return 0

            # 댓글창이 있다면 게시글 내용 확인
            post_title = self.driver.find_element(By.CSS_SELECTOR, "h3.title_text").text
            post_content = self.driver.find_element(By.CSS_SELECTOR, "div.se-module.se-module-text").text
            print(f"게시글 제목: {post_title}")

            prompt = (
                "결혼준비 및 결혼생활 관련 토론에 대한 댓글 1개 달아줘.\n"
                f"제목:{post_title}\n본문:{post_content}\n"
                "규칙: 가-힣 15자 이상(공백·이모지·특수문자 제외), 내용직반응, 광고/링크/비방X, 이모지 최소.\n"
                '출력: {"comment":"문장"}'
            )
            validate = True
            while validate:
                response = self.openai.responses.create(
                    model="gpt-4o-mini",
                    input=prompt,
                    temperature=0.75,
                )

                raw_output = response.output_text
                comment = extract_comment(raw_output)

                if validate_comment(comment):
                    print("✅ 유효한 댓글:", comment)
                    validate = False
                else:
                    print("❌ 너무 짧거나 조건 미달. 재요청 필요:", comment)

            # 댓글 입력창 클릭
            comment_box = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "textarea.comment_inbox_text"))
            )
            comment_box.click()
            time.sleep(1)

            # 댓글 내용 입력
            pyperclip.copy(comment)
            actions = ActionChains(self.driver)
            actions.key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
            time.sleep(1)

            # 댓글 등록 버튼 클릭
            submit_button = self.driver.find_element(By.CSS_SELECTOR, "a.button.btn_register")
            submit_button.click()
            time.sleep(2)
            return 1

        except Exception as e:
            print(f"댓글 작성 중 오류 발생: {e}")
            return 0
        finally:
            # 메인 프레임으로 돌아오기
            self.driver.switch_to.default_content()
            return 0

if __name__ == "__main__":
    naver_service = NaverLoginService()
    naver_service.open_web_mode()
    naver_service.login()
    naver_service.go_to_naver_cafe()
    post_links = naver_service.get_post_list()

    count_comment = 0
    for link in post_links:
        naver_service.driver.get(link)
        time.sleep(2)
        count_comment = count_comment + naver_service.write_comment()

        if count_comment >= 10:
            break

    time.sleep(2)
    naver_service.close_browser()