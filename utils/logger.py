"""
로깅 유틸리티
"""
import logging
import sys
from datetime import datetime
from pathlib import Path

# 로거 인스턴스 저장
_loggers = {}


def setup_logger(name: str, log_dir: Path = None, level: int = logging.INFO) -> logging.Logger:
    """
    로거 설정

    Args:
        name: 로거 이름
        log_dir: 로그 파일 저장 디렉토리
        level: 로깅 레벨

    Returns:
        설정된 로거
    """
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers = []  # 기존 핸들러 제거

    # 포맷 설정
    formatter = logging.Formatter(
        fmt='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 콘솔 핸들러
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 파일 핸들러 (log_dir이 지정된 경우)
    if log_dir:
        log_dir = Path(log_dir)
        log_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file = log_dir / f"{name}_{timestamp}.log"

        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    _loggers[name] = logger
    return logger


def get_logger(name: str) -> logging.Logger:
    """
    기존 로거 가져오기

    Args:
        name: 로거 이름

    Returns:
        로거 인스턴스
    """
    if name in _loggers:
        return _loggers[name]
    return setup_logger(name)


class ProgressLogger:
    """진행률 로깅 클래스"""

    def __init__(self, total: int, prefix: str = "", logger: logging.Logger = None):
        self.total = total
        self.current = 0
        self.prefix = prefix
        self.logger = logger or get_logger("progress")
        self.start_time = datetime.now()

    def update(self, message: str = ""):
        """진행률 업데이트"""
        self.current += 1
        percent = (self.current / self.total) * 100
        elapsed = (datetime.now() - self.start_time).total_seconds()

        if self.current > 0:
            eta = (elapsed / self.current) * (self.total - self.current)
            eta_str = f"{int(eta // 60)}분 {int(eta % 60)}초"
        else:
            eta_str = "계산 중..."

        log_msg = f"{self.prefix}[{self.current}/{self.total}] ({percent:.1f}%) - 남은 시간: {eta_str}"
        if message:
            log_msg += f" | {message}"

        self.logger.info(log_msg)

    def finish(self):
        """완료 로깅"""
        elapsed = (datetime.now() - self.start_time).total_seconds()
        self.logger.info(
            f"{self.prefix}완료! 총 {self.current}개 처리, "
            f"소요 시간: {int(elapsed // 60)}분 {int(elapsed % 60)}초"
        )
