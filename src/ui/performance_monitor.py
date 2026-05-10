"""Монитор производительности: FPS, кол-во тайлов, использование памяти."""

from __future__ import annotations

import sys
import tracemalloc

import arcade

# resource - только Unix; на Windows используем psutil
# или показываем только tracemalloc
_HAS_RESOURCE = False
try:
    import resource as _resource_mod  # noqa: F401
    _HAS_RESOURCE = True
except ImportError:
    _resource_mod = None  # type: ignore[assignment]

_HAS_PSUTIL = False
try:
    import psutil as _psutil_mod  # type: ignore[import-untyped]
    _HAS_PSUTIL = True
except ImportError:
    _psutil_mod = None  # type: ignore[assignment]


class PerformanceMonitor:
    """Монитор производительности в левом верхнем углу окна.

    Показывает FPS, количество отрисованных тайлов
    и использование памяти. Привязан к краям окна.

    Attributes:
        visible: Видимость монитора (переключение по F3).
    """

    def __init__(self) -> None:
        """Инициализация монитора."""
        self.visible: bool = True
        self._fps: float = 0.0
        self._tile_count: int = 0
        self._chunk_count: int = 0

        # Текстовые элементы
        self._fps_text = arcade.Text(
            "", x=0, y=0, color=(0, 0, 0), font_size=13,
            font_name="JetBrains Mono",
        )
        self._tiles_text = arcade.Text(
            "", x=0, y=0, color=(30, 30, 30), font_size=13,
            font_name="JetBrains Mono",
        )
        self._mem_text = arcade.Text(
            "", x=0, y=0, color=(30, 30, 30), font_size=13,
            font_name="JetBrains Mono",
        )

        # Запускаем tracemalloc для отслеживания памяти
        tracemalloc.start()

    # ================================================================
    # Обновление данных
    # ================================================================

    def update(
        self, fps: float, tile_count: int, chunk_count: int
    ) -> None:
        """Обновляет метрики.

        Args:
            fps: Текущий FPS.
            tile_count: Количество отрисованных тайлов.
            chunk_count: Количество отрисованных чанков.
        """
        self._fps = fps
        self._tile_count = tile_count
        self._chunk_count = chunk_count

    # ================================================================
    # Отрисовка
    # ================================================================

    def draw(self, screen_w: int, screen_h: int) -> None:
        """Отрисовывает монитор в левом верхнем углу.

        Args:
            screen_w: Ширина окна.
            screen_h: Высота окна.
        """
        if not self.visible:
            return

        margin = 10
        line_h = 18
        x = margin
        y = screen_h - margin - 13

        # FPS
        self._fps_text.text = f"FPS: {self._fps:.0f}"
        self._fps_text.x = x
        self._fps_text.y = y
        self._fps_text.draw()

        # Тайлы / чанки
        y -= line_h
        self._tiles_text.text = (
            f"Tiles: {self._tile_count} | Chunks: {self._chunk_count}"
        )
        self._tiles_text.x = x
        self._tiles_text.y = y
        self._tiles_text.draw()

        # Память (RAM + tracemalloc)
        y -= line_h
        mem_mb = self._get_ram_mb()

        # tracemalloc: текущее использование
        current, _peak = tracemalloc.get_traced_memory()
        tracemalloc_mb = current / (1024 * 1024)

        if mem_mb is not None:
            self._mem_text.text = (
                f"RAM: {mem_mb:.0f} MB | "
                f"Heap: {tracemalloc_mb:.1f} MB"
            )
        else:
            self._mem_text.text = (
                f"Heap: {tracemalloc_mb:.1f} MB"
            )
        self._mem_text.x = x
        self._mem_text.y = y
        self._mem_text.draw()

    def toggle(self) -> None:
        """Переключает видимость монитора (F3)."""
        self.visible = not self.visible

    @staticmethod
    def _get_ram_mb() -> float | None:
        """Возвращает объём RAM процесса в МБ или None.

        Использует psutil (кросс-платформенный),
        resource (Unix - запасной) или возвращает None.
        """
        if _HAS_PSUTIL and _psutil_mod is not None:
            try:
                proc = _psutil_mod.Process()
                mem_info = proc.memory_info()
                return mem_info.rss / (1024 * 1024)
            except Exception:
                pass
        if _HAS_RESOURCE and _resource_mod is not None:
            try:
                rss = _resource_mod.getrusage(
                    _resource_mod.RUSAGE_SELF
                ).ru_maxrss
                # Linux: килобайты; macOS: байты
                if sys.platform == "darwin":
                    return rss / (1024 * 1024)
                return rss / 1024.0
            except Exception:
                pass
        return None
