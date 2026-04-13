"""
드론비행시험센터 예약 현황 크롤러
URL: https://dronetest.kiast.or.kr
"""

import os
import time
import logging
from dataclasses import dataclass, field
from datetime import date

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

BASE_URL = "https://dronetest.kiast.or.kr"
LOGIN_URL = f"{BASE_URL}/login.do"
STATUS_URL = f"{BASE_URL}/mypage/drncntrusestatus/drncntrusestatus.do"

ACTIVE_STATUSES = {"접수", "보완접수", "승인", "종료"}
CANCEL_STATUSES = {"취소", "불참"}


@dataclass
class FacilityTime:
    """시설 1개의 (병합된) 예약 시간"""
    facility: str
    start_time: str   # HH:MM
    end_time: str     # HH:MM
    status: str = ""  # 시설별 예약 상태 (다른 예약에서 병합될 때 사용)


@dataclass
class CenterSlot:
    """같은 날, 같은 센터의 모든 시설을 묶은 캘린더 이벤트 단위"""
    recept_id: str
    center: str
    use_date: str                          # YYYY-MM-DD
    start_time: str                        # 전체 중 가장 이른 시작
    end_time: str                          # 전체 중 가장 늦은 종료
    facilities: list[FacilityTime] = field(default_factory=list)
    status: str = ""
    apply_date: str = ""

    @property
    def event_title(self) -> str:
        return self.center

    @property
    def unique_key(self) -> str:
        # recept_id를 제외: 같은 날, 같은 센터의 여러 예약을 하나의 이벤트로 묶기 위해
        return f"{self.use_date}_{self.center}"


# 목록 페이지에서만 쓰는 내부 구조체
@dataclass
class _ResSummary:
    recept_id: str
    center: str
    status: str
    apply_date: str


def _build_driver(headless: bool = True) -> webdriver.Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=ko-KR")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36")
    options.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    return driver


def _wait_for(driver: webdriver.Chrome, by: str, value: str, timeout: int = 10):
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((by, value))
    )


def login(driver: webdriver.Chrome) -> bool:
    drone_id = os.getenv("DRONE_ID", "")
    drone_pw = os.getenv("DRONE_PW", "")
    if not drone_id or not drone_pw:
        raise ValueError(".env에 DRONE_ID와 DRONE_PW를 설정하세요.")

    logger.info("로그인 페이지 접속 중...")
    driver.get(LOGIN_URL)
    time.sleep(2)

    try:
        id_input = _wait_for(driver, By.NAME, "user_id")
        id_input.clear()
        id_input.send_keys(drone_id)

        pw_input = driver.find_element(By.NAME, "password2")
        pw_input.clear()
        pw_input.send_keys(drone_pw)

        driver.find_element(By.ID, "login").click()
        time.sleep(3)

        if "login" in driver.current_url.lower():
            logger.error("로그인 실패")
            return False

        logger.info("로그인 성공")
        return True

    except TimeoutException:
        logger.error("로그인 폼 요소를 찾을 수 없습니다.")
        return False


def _fetch_reservation_list(driver: webdriver.Chrome) -> list[_ResSummary]:
    logger.info("예약 현황 페이지 접속 중...")
    driver.get(STATUS_URL)
    time.sleep(2)

    today = date.today()
    start_date = f"{today.year}-01-01"
    end_date = f"{today.year}-12-31"
    logger.info(f"검색 기간: {start_date} ~ {end_date}")

    try:
        start_el = driver.find_element(By.ID, "search_reserve_from_dt")
        driver.execute_script("arguments[0].value = arguments[1];", start_el, start_date)
        end_el = driver.find_element(By.ID, "search_reserve_to_dt")
        driver.execute_script("arguments[0].value = arguments[1];", end_el, end_date)
        driver.find_element(By.XPATH, "//button[@type='button' and text()='검색']").click()
        time.sleep(3)
    except NoSuchElementException as e:
        logger.warning(f"날짜 입력 요소 없음: {e}")

    summaries = []
    for row in driver.find_elements(By.CSS_SELECTOR, "#tbody tr"):
        style = row.get_attribute("style") or ""
        if "display:none" in style.replace(" ", ""):
            continue
        cells = row.find_elements(By.TAG_NAME, "td")
        if len(cells) < 6:
            continue
        texts = [c.text.strip() for c in cells[:6]]
        if not any(texts):
            continue
        summaries.append(_ResSummary(
            recept_id=texts[0],
            center=texts[1],
            status=texts[4],
            apply_date=texts[5].replace(".", "-").strip(),
        ))

    logger.info(f"목록 {len(summaries)}건 확인")
    return summaries


def _parse_time_range(time_range: str) -> tuple[str, str]:
    """'09:00 ~ 12:00' → ('09:00', '12:00')"""
    try:
        parts = [p.strip() for p in time_range.split("~")]
        if len(parts) == 2 and ":" in parts[0] and ":" in parts[1]:
            return parts[0], parts[1]
    except Exception:
        pass
    return "", ""


def _fetch_detail_slots(driver: webdriver.Chrome, res: _ResSummary) -> list[CenterSlot]:
    """
    상세 페이지 첫 번째 테이블에서 시설별 시간을 읽어
    (날짜 + 시설) 단위로 시간을 병합한 뒤
    (날짜 + 센터) 단위로 묶어 CenterSlot 목록을 반환
    """
    try:
        # 상세 페이지로 POST 이동
        driver.execute_script("""
            var form = document.createElement('form');
            form.method = 'post';
            form.action = '/drncenter/reserve/reserveDetail.do';
            var field = document.createElement('input');
            field.type = 'hidden';
            field.name = 'recept_id';
            field.value = arguments[0];
            form.appendChild(field);
            document.body.appendChild(form);
            form.submit();
        """, res.recept_id)
        time.sleep(2)

        tables = driver.find_elements(By.CSS_SELECTOR, "table")
        if not tables:
            logger.warning(f"{res.recept_id}: 테이블 없음")
            return []

        rows = tables[0].find_elements(By.TAG_NAME, "tr")

        # ── Step 1: (날짜, 시설) 단위로 시간 병합 ──────────────────────
        # key: (use_date, facility) → {center, start_time, end_time}
        fac_map: dict[tuple, dict] = {}
        for row in rows[1:]:   # 헤더 스킵
            cells = row.find_elements(By.TAG_NAME, "td")
            if len(cells) < 5:
                continue
            t = [c.text.strip() for c in cells[:5]]
            use_date, center, facility, _, time_range = t[0], t[1], t[2], t[3], t[4]
            if not facility or not use_date:
                continue
            start_t, end_t = _parse_time_range(time_range)
            if not start_t or not end_t:
                continue

            center = center or res.center
            key = (use_date, facility)
            if key not in fac_map:
                fac_map[key] = {"center": center, "start": start_t, "end": end_t}
            else:
                if start_t < fac_map[key]["start"]:
                    fac_map[key]["start"] = start_t
                if end_t > fac_map[key]["end"]:
                    fac_map[key]["end"] = end_t

        # ── Step 2: (날짜, 센터) 단위로 시설 묶기 ────────────────────────
        # key: (use_date, center) → {start_time, end_time, facilities:[FacilityTime]}
        center_map: dict[tuple, dict] = {}
        for (use_date, facility), info in fac_map.items():
            center = info["center"]
            ft = FacilityTime(
                facility=facility,
                start_time=info["start"],
                end_time=info["end"],
                status=res.status,
            )
            key2 = (use_date, center)
            if key2 not in center_map:
                center_map[key2] = {
                    "start_time": info["start"],
                    "end_time": info["end"],
                    "facilities": [ft],
                }
            else:
                if info["start"] < center_map[key2]["start_time"]:
                    center_map[key2]["start_time"] = info["start"]
                if info["end"] > center_map[key2]["end_time"]:
                    center_map[key2]["end_time"] = info["end"]
                center_map[key2]["facilities"].append(ft)

        # ── Step 3: CenterSlot 생성 ─────────────────────────────────────
        result = []
        for (use_date, center), info in center_map.items():
            facilities = sorted(info["facilities"], key=lambda f: f.start_time)
            result.append(CenterSlot(
                recept_id=res.recept_id,
                center=center,
                use_date=use_date,
                start_time=info["start_time"],
                end_time=info["end_time"],
                facilities=facilities,
                status=res.status,
                apply_date=res.apply_date,
            ))

        logger.info(f"  {res.recept_id} ({res.status}): {len(result)}개 이벤트")
        return result

    except Exception as e:
        logger.error(f"{res.recept_id} 상세 조회 실패: {e}")
        return []


def _merge_slots(raw_slots: list[CenterSlot]) -> list[CenterSlot]:
    """
    같은 (날짜, 센터)를 가진 슬롯들을 하나로 병합한다.
    별개의 예약(다른 recept_id)으로 시설을 따로 예약했을 때도
    하나의 캘린더 이벤트에 모든 시설이 표시된다.
    """
    _STATUS_PRIORITY = ["승인", "접수", "보완접수", "종료", "취소", "불참"]

    def _pick_status(a: str, b: str) -> str:
        """더 활성 상태인 쪽을 선택"""
        pa = _STATUS_PRIORITY.index(a) if a in _STATUS_PRIORITY else 99
        pb = _STATUS_PRIORITY.index(b) if b in _STATUS_PRIORITY else 99
        return a if pa <= pb else b

    merged: dict[str, CenterSlot] = {}
    for slot in raw_slots:
        key = slot.unique_key  # f"{use_date}_{center}"
        if key not in merged:
            merged[key] = slot
        else:
            base = merged[key]
            # 시설 병합 (이름 기준 중복 제거)
            existing_fac_names = {f.facility for f in base.facilities}
            for ft in slot.facilities:
                if ft.facility not in existing_fac_names:
                    base.facilities.append(ft)
                    existing_fac_names.add(ft.facility)
            # 전체 시간 범위 확장
            if slot.start_time < base.start_time:
                base.start_time = slot.start_time
            if slot.end_time > base.end_time:
                base.end_time = slot.end_time
            # 더 활성인 상태로 업데이트
            base.status = _pick_status(base.status, slot.status)
            # 시작 시간 기준 정렬
            base.facilities.sort(key=lambda f: f.start_time)

    return list(merged.values())


def crawl() -> list[CenterSlot]:
    driver = _build_driver(headless=True)
    try:
        if not login(driver):
            raise RuntimeError("로그인 실패")

        summaries = _fetch_reservation_list(driver)
        raw_slots: list[CenterSlot] = []
        for res in summaries:
            raw_slots.extend(_fetch_detail_slots(driver, res))

        # 같은 날짜 + 센터의 슬롯을 하나의 캘린더 이벤트로 병합
        all_slots = _merge_slots(raw_slots)
        logger.info(f"총 {len(all_slots)}개 이벤트 조회 완료 (병합 전 {len(raw_slots)}건)")
        return all_slots
    finally:
        driver.quit()
