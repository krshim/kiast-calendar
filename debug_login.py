"""
로그인 후 예약 현황 페이지 구조 확인용 진단 스크립트
"""
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from dotenv import load_dotenv
import time, os

load_dotenv()

DRONE_ID = os.getenv("DRONE_ID", "")
DRONE_PW = os.getenv("DRONE_PW", "")

BASE_URL = "https://dronetest.kiast.or.kr"
LOGIN_URL = f"{BASE_URL}/login.do"
STATUS_URL = f"{BASE_URL}/mypage/drncntrusestatus/drncntrusestatus.do"

options = Options()
options.add_argument("--window-size=1920,1080")
options.add_argument("--lang=ko-KR")
options.add_experimental_option("excludeSwitches", ["enable-logging"])

def print_elements(driver, label):
    print(f"\n========== {label} ==========")
    inputs = driver.find_elements("tag name", "input")
    print(f"input 요소 ({len(inputs)}개):")
    for el in inputs:
        print(f"  type={el.get_attribute('type')!r:12} "
              f"name={el.get_attribute('name')!r:20} "
              f"id={el.get_attribute('id')!r:20} "
              f"placeholder={el.get_attribute('placeholder')!r}")

    buttons = driver.find_elements("tag name", "button")
    print(f"button 요소 ({len(buttons)}개):")
    for el in buttons:
        print(f"  type={el.get_attribute('type')!r:10} "
              f"id={el.get_attribute('id')!r:30} "
              f"text={el.text!r}")

    selects = driver.find_elements("tag name", "select")
    print(f"select 요소 ({len(selects)}개):")
    for el in selects:
        print(f"  name={el.get_attribute('name')!r:20} id={el.get_attribute('id')!r}")

driver = webdriver.Chrome(options=options)
try:
    # 1. 로그인
    print("로그인 중...")
    driver.get(LOGIN_URL)
    time.sleep(2)
    driver.find_element("name", "user_id").send_keys(DRONE_ID)
    driver.find_element("name", "password2").send_keys(DRONE_PW)
    driver.find_element("id", "login").click()
    time.sleep(3)
    print(f"현재 URL: {driver.current_url}")

    # 2. 예약 현황 페이지 이동
    print(f"\n예약 현황 페이지 이동: {STATUS_URL}")
    driver.get(STATUS_URL)
    time.sleep(3)
    print(f"현재 URL: {driver.current_url}")

    # 3. 페이지 소스 저장
    with open("status_page.html", "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    driver.save_screenshot("status_screenshot.png")
    print("status_page.html / status_screenshot.png 저장 완료")

    # 4. 요소 목록 출력
    print_elements(driver, "예약 현황 페이지")

    # 5. 접수 상태인 첫 번째 행의 recept_id 추출 후 상세 페이지 이동
    rows = driver.find_elements("css selector", "#tbody tr")
    recept_id = None
    for row in rows:
        style = row.get_attribute("style") or ""
        if "display:none" in style.replace(" ", ""):
            continue
        cells = row.find_elements("tag name", "td")
        if len(cells) >= 5:
            status = cells[4].text.strip()
            if status == "접수":
                recept_id = cells[0].text.strip()
                break

    if recept_id:
        print(f"\n상세 페이지 이동: recept_id={recept_id}")
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
        """, recept_id)
        time.sleep(3)
        print(f"현재 URL: {driver.current_url}")

        with open("detail_page.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        driver.save_screenshot("detail_screenshot.png")
        print("detail_page.html / detail_screenshot.png 저장 완료")

        print_elements(driver, "상세 페이지")

        # 테이블 내용 출력
        tables = driver.find_elements("tag name", "table")
        print(f"\n테이블 ({len(tables)}개):")
        for i, tbl in enumerate(tables):
            rows_t = tbl.find_elements("tag name", "tr")
            print(f"  [테이블 {i}] {len(rows_t)}행")
            for row_t in rows_t[:20]:
                cells_t = row_t.find_elements("tag name", "td") or row_t.find_elements("tag name", "th")
                texts = [c.text.strip() for c in cells_t]
                if any(texts):
                    print(f"    {texts}")
    else:
        print("접수 상태 예약을 찾지 못했습니다.")

    input("\n확인 후 Enter를 눌러 종료...")
finally:
    driver.quit()
