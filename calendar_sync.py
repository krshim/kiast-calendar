"""
Google Calendar 동기화 모듈
- 별도의 공유 캘린더 "드론비행시험센터"를 생성/관리
- 고유 키는 extendedProperties(private)에 저장 → 설명란에 노출 안 됨
"""

import os
import logging
from datetime import date
from urllib.parse import quote

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv

from crawler import CenterSlot, ACTIVE_STATUSES, CANCEL_STATUSES

load_dotenv()
logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]
UNIQUE_KEY_PROP = "droneKey"


def _get_credentials() -> Credentials:
    creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    token_file = os.getenv("GOOGLE_TOKEN_FILE", "token.json")

    creds_path = os.path.join(os.path.dirname(__file__), creds_file)
    token_path = os.path.join(os.path.dirname(__file__), token_file)

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("액세스 토큰 갱신 중...")
            creds.refresh(Request())
        else:
            if not os.path.exists(creds_path):
                raise FileNotFoundError(
                    f"credentials.json 파일을 찾을 수 없습니다: {creds_path}\n"
                    "Google Cloud Console에서 OAuth2 자격 증명을 다운로드하세요."
                )
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path, "w") as f:
            f.write(creds.to_json())
        logger.info(f"토큰 저장됨: {token_path}")

    return creds


def _make_calendar_public(service, calendar_id: str) -> None:
    acl_list = service.acl().list(calendarId=calendar_id).execute()
    for rule in acl_list.get("items", []):
        if rule.get("scope", {}).get("type") == "default" and rule.get("role") == "reader":
            logger.debug("캘린더가 이미 공개 상태입니다.")
            return
    try:
        service.acl().insert(calendarId=calendar_id, body={
            "scope": {"type": "default"},
            "role": "reader",
        }).execute()
        logger.info("캘린더 공개 설정 완료")
    except HttpError as e:
        logger.warning(f"캘린더 공개 설정 실패: {e}")


def _print_share_links(calendar_id: str) -> None:
    encoded_id = quote(calendar_id)
    subscribe_url = f"https://calendar.google.com/calendar/u/0/r?cid={encoded_id}"
    webcal_url = f"https://calendar.google.com/calendar/ical/{encoded_id}/public/basic.ics"

    print()
    print("=" * 60)
    print("  [드론비행시험센터] 캘린더 공유 정보")
    print("=" * 60)
    print(f"  캘린더 ID : {calendar_id}")
    print(f"\n  ▶ Google Calendar 구독 링크\n    {subscribe_url}")
    print(f"\n  ▶ iCal 구독 링크 (Outlook 등)\n    {webcal_url}")
    print("=" * 60)
    print()
    logger.info(f"구독 링크: {subscribe_url}")


def _get_or_create_shared_calendar(service, calendar_name: str) -> str:
    for entry in service.calendarList().list().execute().get("items", []):
        if (
            entry.get("summary") == calendar_name
            and entry.get("id") != "primary"
            and "group.calendar.google.com" in entry.get("id", "")
        ):
            cal_id = entry["id"]
            logger.info(f"기존 공유 캘린더 사용: {calendar_name}")
            _make_calendar_public(service, cal_id)
            _print_share_links(cal_id)
            return cal_id

    logger.info(f"공유 캘린더 '{calendar_name}' 생성 중...")
    new_cal = service.calendars().insert(body={
        "summary": calendar_name,
        "description": "드론비행시험센터 예약 현황 (자동 동기화)",
        "timeZone": "Asia/Seoul",
    }).execute()

    cal_id = new_cal["id"]
    logger.info(f"공유 캘린더 생성 완료: id={cal_id}")
    _make_calendar_public(service, cal_id)
    _print_share_links(cal_id)
    return cal_id


def _fetch_existing_events(service, calendar_id: str) -> dict[str, dict]:
    """캘린더 이벤트를 {unique_key: event} 딕셔너리로 반환"""
    events_map: dict[str, dict] = {}
    page_token = None
    year = date.today().year

    while True:
        result = service.events().list(
            calendarId=calendar_id,
            timeMin=f"{year}-01-01T00:00:00Z",
            timeMax=f"{year}-12-31T23:59:59Z",
            singleEvents=True,
            pageToken=page_token,
        ).execute()

        for event in result.get("items", []):
            key = (
                event.get("extendedProperties", {})
                .get("private", {})
                .get(UNIQUE_KEY_PROP)
            )
            if key:
                events_map[key] = event

        page_token = result.get("nextPageToken")
        if not page_token:
            break

    logger.info(f"기존 캘린더 이벤트 {len(events_map)}건 로드됨")
    return events_map


def _build_description(slot: CenterSlot) -> str:
    """
    예약시간: 09:00~18:00

    예약시설1: 대회의실
    예약시간: 09:00~12:00

    예약시설2: 활주로
    예약시간: 13:00~18:00

    신청상태: 접수
    신청일: 2026-04-01
    """
    lines = []

    # 시설별 상태가 모두 같은지 확인 (다를 때만 시설별로 상태 표시)
    fac_statuses = [ft.status for ft in slot.facilities if ft.status]
    show_per_fac_status = len(set(fac_statuses)) > 1

    for i, ft in enumerate(slot.facilities, start=1):
        lines.append(f"예약시설{i}: {ft.facility}")
        lines.append(f"예약시간: {ft.start_time}~{ft.end_time}")
        if show_per_fac_status and ft.status:
            lines.append(f"신청상태: {ft.status}")
        lines.append("")

    if not show_per_fac_status:
        lines.append(f"신청상태: {slot.status}")
    lines.append(f"신청일: {slot.apply_date}")
    return "\n".join(lines)


def _build_event_body(slot: CenterSlot) -> dict:
    from datetime import date, timedelta
    end_date = str(date.fromisoformat(slot.use_date) + timedelta(days=1))

    return {
        "summary": slot.event_title,
        "description": _build_description(slot),
        "start": {"date": slot.use_date},
        "end": {"date": end_date},
        "extendedProperties": {
            "private": {UNIQUE_KEY_PROP: slot.unique_key}
        },
    }


def sync(slots: list[CenterSlot]) -> None:
    calendar_name = os.getenv("CALENDAR_NAME", "드론비행시험센터")

    creds = _get_credentials()
    service = build("calendar", "v3", credentials=creds)

    calendar_id = _get_or_create_shared_calendar(service, calendar_name)
    existing = _fetch_existing_events(service, calendar_id)

    added = updated = deleted = skipped = 0
    processed_keys: set[str] = set()

    for slot in slots:
        key = slot.unique_key
        processed_keys.add(key)

        if slot.status in ACTIVE_STATUSES:
            if key in existing:
                existing_event = existing[key]
                new_body = _build_event_body(slot)
                # 설명이나 형식이 바뀌었으면 업데이트 (시설 추가/변경 반영)
                old_desc = existing_event.get("description", "")
                new_desc = new_body["description"]
                is_datetime_event = "dateTime" in existing_event.get("start", {})
                if is_datetime_event or old_desc != new_desc:
                    try:
                        service.events().update(
                            calendarId=calendar_id,
                            eventId=existing_event["id"],
                            body=new_body,
                        ).execute()
                        logger.info(f"업데이트: {slot.event_title} ({slot.use_date})")
                        updated += 1
                    except HttpError as e:
                        logger.error(f"업데이트 실패: {slot.event_title} - {e}")
                else:
                    logger.debug(f"유지: {slot.event_title} ({slot.use_date})")
                    skipped += 1
            else:
                try:
                    service.events().insert(
                        calendarId=calendar_id,
                        body=_build_event_body(slot),
                    ).execute()
                    logger.info(f"추가: {slot.event_title} ({slot.use_date}, {slot.start_time}~{slot.end_time})")
                    added += 1
                except HttpError as e:
                    logger.error(f"추가 실패: {slot.event_title} - {e}")

        elif slot.status in CANCEL_STATUSES:
            if key in existing:
                try:
                    service.events().delete(
                        calendarId=calendar_id,
                        eventId=existing[key]["id"],
                    ).execute()
                    logger.info(f"삭제 (취소): {slot.event_title} ({slot.use_date})")
                    deleted += 1
                except HttpError as e:
                    logger.error(f"삭제 실패: {slot.event_title} - {e}")
            else:
                logger.debug(f"취소이나 캘린더에 없음, 스킵: {slot.event_title}")

        else:
            logger.debug(f"처리 제외 상태({slot.status}): {slot.event_title}")

    # 더 이상 예약 목록에 없는 고아 이벤트 삭제 (예: unique_key 형식 변경으로 남은 구 이벤트)
    orphan_keys = set(existing.keys()) - processed_keys
    for key in orphan_keys:
        orphan_event = existing[key]
        try:
            service.events().delete(
                calendarId=calendar_id,
                eventId=orphan_event["id"],
            ).execute()
            logger.info(f"고아 이벤트 삭제: {orphan_event.get('summary', key)}")
            deleted += 1
        except HttpError as e:
            logger.error(f"고아 이벤트 삭제 실패: {key} - {e}")

    logger.info(f"동기화 완료 - 추가: {added}건, 업데이트: {updated}건, 삭제: {deleted}건, 유지: {skipped}건")
