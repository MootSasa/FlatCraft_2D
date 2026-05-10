"""HUD: координатор интерфейса (миникарта, монитор)."""

from __future__ import annotations

from src.ui.minimap import Minimap
from src.ui.performance_monitor import PerformanceMonitor
from src.world.models import World


class HUD:
    """Координатор элементов интерфейса.

    Объединяет миникарту и монитор производительности.
    Все элементы привязаны к краям окна.

    Attributes:
        minimap: Миникарта мира.
        perf: Монитор производительности.
    """

    def __init__(self, world: World) -> None:
        """Инициализация HUD.

        Args:
            world: Сгенерированный мир.
        """
        self.minimap = Minimap(world)
        self.perf = PerformanceMonitor()

    def cleanup(self) -> None:
        """Освобождает ресурсы миникарты.

        Вызывается при возврате в меню для уменьшения RSS.
        """
        self.minimap.cleanup()

    # ================================================================
    # Отрисовка
    # ================================================================

    def draw(
        self,
        screen_w: int,
        screen_h: int,
        fps: float,
        cam_x: float,
        cam_y: float,
        zoom: float,
        tile_size: int = 32,
        tile_count: int = 0,
        chunk_count: int = 0,
    ) -> None:
        """Отрисовывает все элементы HUD.

        Args:
            screen_w: Ширина окна.
            screen_h: Высота окна.
            fps: Текущий FPS.
            cam_x: X камеры в пикселях мира.
            cam_y: Y камеры в пикселях мира.
            zoom: Текущий зум.
            tile_size: Размер тайла.
            tile_count: Кол-во отрисованных тайлов.
            chunk_count: Кол-во отрисованных чанков.
        """
        # Монитор производительности
        self.perf.update(fps, tile_count, chunk_count)
        self.perf.draw(screen_w, screen_h)

        # Миникарта
        self.minimap.draw(screen_w, screen_h, cam_x, cam_y, zoom, tile_size)

    # ================================================================
    # События
    # ================================================================

    def on_resize(self, screen_w: int, screen_h: int) -> None:
        """Обновляет позиции при изменении размера окна."""
        self.minimap.on_resize(screen_w, screen_h)

    def on_mouse_press(self, screen_x: float, screen_y: float) -> bool:
        """Обрабатывает клик мыши.

        Проверяет попадание в миникарту и перемещает камеру.

        Args:
            screen_x: X клика (пиксели экрана).
            screen_y: Y клика (пиксели экрана).

        Returns:
            True, если клик обработан.
        """
        if self.minimap.hit_test(screen_x, screen_y):
            return True
        return False

    def minimap_click_to_world(
        self, screen_x: float, screen_y: float, tile_size: int = 32
    ) -> tuple[float, float]:
        """Преобразует клик по миникарте в мировые координаты.

        Args:
            screen_x: X клика (пиксели экрана).
            screen_y: Y клика (пиксели экрана).
            tile_size: Размер тайла.

        Returns:
            Кортеж (world_x, world_y) в пикселях мира.
        """
        return self.minimap.click_to_world(screen_x, screen_y, tile_size)

    def toggle_perf(self) -> None:
        """Переключает видимость монитора производительности (F3)."""
        self.perf.toggle()
