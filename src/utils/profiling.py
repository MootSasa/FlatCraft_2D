"""Профилирование: замер узких мест.

Отчёты сохраняются в HTML.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

try:
    from pyinstrument import Profiler as _PyinstrumentProfiler
    _HAS_PYINSTRUMENT = True
except ImportError:
    _PyinstrumentProfiler = None
    _HAS_PYINSTRUMENT = False

logger = logging.getLogger(__name__)

# Каталог для отчётов
_REPORTS_DIR: str = "output/profiling"


class GameProfiler:
    """Профилировщик игры на базе pyinstrument.

    Поддерживает:
    - Включение/выключение по горячей клавише
    - Профилирование отдельных секций (start/stop)
    - Автоматическое сохранение HTML-отчётов
    - Замер времени между start/stop

    Attributes:
        enabled: Активен ли профилировщик.
    """

    def __init__(self) -> None:
        self.enabled: bool = False
        self._profiler: Optional[
            _PyinstrumentProfiler
        ] = None
        self._section_start: float = 0.0
        self._frame_count: int = 0
        self._capture_frames: int = 300
        self._capturing: bool = False

    def toggle(self) -> None:
        """Переключает состояние профилировщика."""
        if not _HAS_PYINSTRUMENT:
            logger.warning(
                "pyinstrument не установлен: "
                "pip install pyinstrument"
            )
            return

        self.enabled = not self.enabled
        if self.enabled:
            logger.info("Профилировщик включён")
        else:
            logger.info("Профилировщик выключен")

    def start_capture(self, frames: int = 300) -> None:
        """Начинает захват профилирования на N кадров.

        Args:
            frames: Количество кадров для захвата.
        """
        if not self.enabled or not _HAS_PYINSTRUMENT:
            return

        self._capture_frames = frames
        self._frame_count = 0
        self._capturing = True

        try:
            self._profiler = _PyinstrumentProfiler()
            self._profiler.start()
            logger.info(
                "Захват профилирования начат (%d кадров)",
                frames,
            )
        except Exception as exc:
            logger.error("Ошибка запуска профилировщика: %s", exc)
            self._capturing = False

    def tick(self) -> None:
        """Отмечает один кадр. Автоматически останавливает
        захват после достижения лимита кадров."""
        if not self._capturing:
            return

        self._frame_count += 1
        if self._frame_count >= self._capture_frames:
            self._stop_capture()

    def _stop_capture(self) -> None:
        """Останавливает захват и сохраняет отчёт."""
        self._capturing = False

        if self._profiler is None:
            return

        try:
            self._profiler.stop()
        except Exception as exc:
            logger.error("Ошибка остановки профилировщика: %s", exc)
            return

        self._save_report()
        self._profiler = None

    def _save_report(self) -> None:
        """Сохраняет HTML-отчёт в output/profiling/."""
        if self._profiler is None:
            return

        # Создаём каталог
        reports_path = Path(_REPORTS_DIR)
        reports_path.mkdir(parents=True, exist_ok=True)

        # Имя файла с таймстемпом
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        html_path = reports_path / f"profile_{timestamp}.html"
        text_path = reports_path / f"profile_{timestamp}.txt"

        try:
            # HTML-отчёт
            html = self._profiler.output_html()
            html_path.write_text(html, encoding="utf-8")

            # Текстовый отчёт
            text = self._profiler.output_text(unicode=True)
            text_path.write_text(text, encoding="utf-8")

            logger.info(
                "Отчёт профилирования сохранён:\n"
                "  HTML: %s\n"
                "  Текст: %s",
                html_path,
                text_path,
            )
        except Exception as exc:
            logger.error("Ошибка сохранения отчёта: %s", exc)

    @property
    def is_capturing(self) -> bool:
        """Идёт ли захват профилирования."""
        return self._capturing

    @property
    def capture_progress(self) -> float:
        """Прогресс захвата (0.0..1.0)."""
        if not self._capturing or self._capture_frames <= 0:
            return 0.0
        return self._frame_count / self._capture_frames

    # ================================================================
    # Контекстный менеджер для секций
    # ================================================================

    def section(self, name: str) -> _Section:
        """Возвращает контекстный менеджер для замера секции.

        Использование::

            with profiler.section("generation"):
                world = generate_world(...)
        """
        return _Section(self, name)


class _Section:
    """Контекстный менеджер для замера отдельной секции."""

    def __init__(
        self, outer: GameProfiler, name: str
    ) -> None:
        self._outer = outer
        self._name = name
        self._profiler: Optional[
            _PyinstrumentProfiler
        ] = None
        self._start_time: float = 0.0

    def __enter__(self) -> "_Section":
        if not _HAS_PYINSTRUMENT:
            return self

        self._start_time = time.perf_counter()
        try:
            self._profiler = _PyinstrumentProfiler()
            self._profiler.start()
        except Exception:
            self._profiler = None
        return self

    def __exit__(
        self, exc_type: object, exc_val: object, exc_tb: object
    ) -> None:
        if self._profiler is None:
            return

        try:
            self._profiler.stop()
        except Exception:
            return

        elapsed = time.perf_counter() - self._start_time

        # Сохраняем секционный отчёт
        reports_path = Path(_REPORTS_DIR)
        reports_path.mkdir(parents=True, exist_ok=True)

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        html_path = (
            reports_path
            / f"section_{self._name}_{timestamp}.html"
        )
        text_path = (
            reports_path
            / f"section_{self._name}_{timestamp}.txt"
        )

        try:
            html_path.write_text(
                self._profiler.output_html(), encoding="utf-8"
            )
            text_path.write_text(
                self._profiler.output_text(unicode=True),
                encoding="utf-8",
            )
            logger.info(
                "Секция '%s': %.3f сек - отчёт: %s",
                self._name,
                elapsed,
                html_path,
            )
        except Exception as exc:
            logger.error(
                "Ошибка сохранения секции '%s': %s",
                self._name,
                exc,
            )
