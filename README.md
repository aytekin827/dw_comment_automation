# 💬 네이버 카페 자동 댓글 & 좋아요 프로그램(DWPointBooster)

이 프로젝트는 **네이버 카페**에서
댓글과 좋아요 활동을 자동화하여 **포인트를 효율적으로 모을 수 있도록 돕는 프로그램**입니다.
GUI 기반으로 쉽게 설정하고 실행할 수 있으며, OpenAI LLM을 이용해 자연스러운 한국어 댓글을 생성합니다.

**개인 openAI API 필요**

---

## 🧭 주요 기능

- ✅ **자동 로그인**: 네이버 ID / 비밀번호 입력 후 자동 로그인
- 💬 **커뮤니티별 게시글 자동 수집** (공지글 제외)
- 🧠 **OpenAI LLM 기반 자연스러운 댓글 생성(개인 openAI API 키 필요)**
- ❤️ **자동 좋아요 수행** (선택 가능)
- 🔧 **Tkinter GUI 기반 설정창 (한글 UI)**
- 🪄 **“내 정보 기억하기”** 기능으로 재실행 시 설정 자동 복원
- 🔍 **로그 실시간 표시 / 토글 숨김 / 로그 레벨 필터링**
- 🌈 **댓글 톤 / 길이 조절 기능**

---

## 🗂️ 프로젝트 구조

dw_comment_automation/

├── main.py               # GUI 실행 메인 파일

├── helpers.py            # 유틸 / 프롬프트 / 문자열 처리 함수

├── config.py             # 환경 변수 및 기본 설정

├── requirements.txt      # 의존성 목록

## 설치 및 실행

### 환경 요구사항

| 항목         | 버전 / 권장                 |
| ------------ | --------------------------- |
| Python       | 3.10 이상                   |
| Chrome       | 최신 버전                   |
| ChromeDriver | webdriver-manager 자동 설치 |
| OS           | Windows 가능               |

### 패키지 설치

```bash
pip install -r requirements.txt
```

### 실행 방법

GUI 실행

```
python main.py
```

#### 주요 설정 항목

| 설정 항목                             | 설명                                                 |
| ------------------------------------- | ---------------------------------------------------- |
| **네이버 ID / 비밀번호**        | 로그인에 사용할 계정                                 |
| **OpenAI Key**                  | GPT API Key                                          |
| **LLM 모델 선택**               | `gpt-4o-mini`(기본) /`gpt-4o`/`gpt-4.1-mini`등 |
| **Temperature**                 | 낮을수록 일관성 ↑ / 높을수록 다양성 ↑              |
| **댓글 톤 설정**                | 따뜻한 / 친근한 / 담백한 / 유머러스한 / 공감형 등    |
| **댓글 길이 설정**              | 짧게(≈18자) / 중간(≈28자) / 길게(≈40자)           |
| **커뮤니티 선택**               | 게시판 선택 (예: 결혼준비 토론방 등)                 |
| **댓글 작성 / 좋아요 체크박스** | 수행할 작업 선택                                     |
| **로그 보기 토글**              | 로그창 숨기기/보이기                                 |
| **내 정보 기억하기**            | 설정값을 로컬에 저장 (`local_config.json`)         |

#### 댓글 생성 로직

* OpenAI API를 이용하여 커뮤니티별 템플릿 프롬프트(`PROMPT_MAP`)에 맞게 문맥 기반 댓글 생성
* 커뮤니티 특성에 따라 **자연스럽고 사람다운 한 문장**만 생성
* `smart_clip_korean()` 함수로 문장 중간이 아닌 자연스러운 끝맺음에서 길이 컷팅
* 40자 제한 내에서 부드러운 한글 문체 유지

```
제목: 결혼 예산 줄이는 팁
본문: 예산이 점점 늘어서 고민이에요.
→ 생성 댓글: "실속 있게 준비하신다니 멋져요, 작은 부분부터 줄여보세요!"
```

#### 로그기능

* 하단 로그창에 실시간 진행 상황 표시
* 로그 레벨: `DEBUG / INFO / WARNING / ERROR`
* “로그 보이기” 토글로 창 숨기기 가능
* 프로그램 내부 메모리에서 관리(별도 DB 사용 안 함)

#### 내 정보 기억하기

* 체크 시 `local_config.json` 파일에 사용자 설정이 저장됩니다.
* 다음 실행 시 자동으로 불러와 동일한 설정으로 시작합니다.

> ⚠️ 보안상 OpenAI Key, 네이버 비밀번호는 공용 PC에서는 저장하지 마세요.

#### 실행 파일(.exe)로 패키징

```
pyinstaller --name DWPointBooster --onefile --noconsole --icon="icon2.ico" --add-data "icon2.ico;." main.py
```

빌드 결과:

dist/
└── DWPointBooster.exe

# 요약

**목표:** 다이렉트웨딩 카페 회원들이 효율적으로 포인트를 쌓을 수 있는 자동화 툴

**핵심 기술:**

* Python (Selenium / Tkinter / OpenAI API)
* Smart Prompt Engineering
* GUI Interaction(tkinter) & Persistent Config)
* ChromeDriver Automation

# 주의사항

본 프로그램은 개인 역량 개발목적으로 제작하였습니다.

사이트 관리자 및 정책관련하여 위반 시 책임은 개인에게 있습니다.

# 기여하기

Pull Request / Issue는 언제나 환영입니다!

# 후원

작은 프로젝트이지만 도움이 되셨다면 커피 한잔으로 응원해주세요!

⬇⬇ 커피한잔 후원하기 ⬇⬇

<img width="349" height="399" alt="DonateACoffee" src="https://github.com/user-attachments/assets/a2e14fd8-9a36-4448-9efc-f143ebb917ed" />


