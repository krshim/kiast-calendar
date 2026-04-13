"""
드론비행시험센터 예약 현황 → Google Calendar 자동 동기화
실행: python main.py
"""

import logging
import sys
from pathlib import Path

# 로그 설정
LOG_FILE = Path(__file__).parent / "sync.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def main():
    logger.info("=" * 60)
    logger.info("드론비행시험센터 예약 동기화 시작")
    logger.info("=" * 60)

    try:
        from crawler import crawl
        from calendar_sync import sync

        # 1. 크롤링
        logger.info("[1/2] 예약 현황 크롤링 중...")
        reservations = crawl()

        if not reservations:
            logger.warning("조회된 예약이 없습니다. 동기화를 건너뜁니다.")
            return

        logger.info(f"  - 접수: {sum(1 for r in reservations if r.status == '접수')}건")
        logger.info(f"  - 취소: {sum(1 for r in reservations if r.status == '취소')}건")

        # 2. 캘린더 동기화
        logger.info("[2/2] Google Calendar 동기화 중...")
        sync(reservations)

        logger.info("=" * 60)
        logger.info("동기화 완료")
        logger.info("=" * 60)

    except Exception as e:
        logger.exception(f"오류 발생: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
