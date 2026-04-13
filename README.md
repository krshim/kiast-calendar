# 드론비행시험센터 예약 → Google Calendar 자동 동기화

---

## 유지보수 가이드

### 비밀번호 변경 시: KIAST_ID / KIAST_PW Secrets 업데이트

1. GitHub 저장소 → **Settings** → **Secrets and variables** → **Actions**
2. `KIAST_ID` 또는 `KIAST_PW` 항목을 클릭 → **Update**
3. 새 값 입력 후 저장
4. 다음 자동 실행 또는 수동 실행 시 즉시 반영됨

### Google 인증 만료 시: token.json 재발급

token.json이 만료되면 Actions 실행이 실패합니다. 로컬에서 재발급 후 Secret을 업데이트해야 합니다.

1. 로컬에서 `credentials.json`이 있는 상태로 실행:
   ```bash
   python -c "
   from google_auth_oauthlib.flow import InstalledAppFlow
   flow = InstalledAppFlow.from_client_secrets_file('credentials.json', ['https://www.googleapis.com/auth/calendar'])
   creds = flow.run_local_server(port=0)
   open('token.json', 'w').write(creds.to_json())
   "
   ```
2. 브라우저에서 Google 계정 인증 완료
3. 생성된 `token.json` 내용을 복사
4. GitHub → Settings → Secrets → `GOOGLE_TOKEN_JSON` → **Update** → 붙여넣기

### GitHub Actions 수동 실행

1. GitHub 저장소 → **Actions** 탭
2. 왼쪽 목록에서 **Drone Calendar Sync** 선택
3. **Run workflow** 버튼 클릭 → **Run workflow** 확인

---

## 프로젝트 개요

KIAST 드론비행시험센터 예약 현황 페이지를 매일 자동으로 크롤링하여 Google Calendar에 동기화하는 도구입니다.

- 로그인 후 예약 목록 및 상세 정보를 Selenium으로 수집
- 같은 날짜 + 센터 단위로 시설을 병합하여 단일 캘린더 이벤트로 관리
- 접수/승인 상태는 추가·업데이트, 취소/불참 상태는 캘린더에서 삭제
- GitHub Actions로 매일 오전 7시(KST) 자동 실행

---

## 코드 구성 및 파일 역할

| 파일 | 역할 |
|------|------|
| `main.py` | 진입점. 크롤링 → 동기화 순서 실행, 로깅 설정 |
| `crawler.py` | Selenium으로 KIAST 사이트 로그인 및 예약 정보 수집 |
| `calendar_sync.py` | Google Calendar API로 이벤트 추가/업데이트/삭제 동기화 |
| `requirements.txt` | Python 의존성 목록 |
| `.github/workflows/sync.yml` | GitHub Actions 자동 실행 워크플로 |
| `credentials.json` | Google OAuth2 클라이언트 자격증명 (로컬 전용, gitignore) |
| `token.json` | Google 액세스 토큰 (로컬 전용, gitignore) |
| `sync.log` | 실행 로그 (로컬 전용, gitignore) |

---

## 기술 스택

| 구성요소 | 기술 |
|----------|------|
| 크롤링 | Python 3.11 + Selenium 4 (Chrome headless) |
| 캘린더 연동 | Google Calendar API v3 (google-api-python-client) |
| 인증 | Google OAuth2 (google-auth-oauthlib) |
| 자동화 | GitHub Actions (cron schedule + workflow_dispatch) |
| 환경 변수 | python-dotenv (로컬), GitHub Secrets (CI) |

---

## 보안 처리

- **GitHub Secrets**: 로그인 정보(`KIAST_ID`, `KIAST_PW`)와 Google 인증 파일(`GOOGLE_CREDENTIALS_JSON`, `GOOGLE_TOKEN_JSON`)은 모두 GitHub Secrets로 관리
- **하드코딩 없음**: 코드 내에 계정 정보, API 키 등 민감 정보 없음
- **워크플로 매핑**: Secrets → 환경변수(`DRONE_ID`, `DRONE_PW`) 및 파일(`credentials.json`, `token.json`)로 런타임에만 주입
- **로컬 .gitignore**: `credentials.json`, `token.json`, `sync.log`, `.env` 등 민감 파일은 저장소에 포함하지 않음

---

## 실행 방법

### 로컬 실행

```bash
# 1. 의존성 설치
pip install -r requirements.txt

# 2. .env 파일 생성
# DRONE_ID=your_kiast_id
# DRONE_PW=your_kiast_password

# 3. credentials.json 준비 (Google Cloud Console에서 OAuth2 자격증명 다운로드)

# 4. 최초 실행 시 브라우저 인증 → token.json 자동 생성
python main.py
```

### GitHub Actions 자동 실행

- 매일 오전 7시(KST) 자동 실행
- 수동 실행: Actions 탭 → Drone Calendar Sync → Run workflow
