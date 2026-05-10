"""Экран загрузки.

Три фазы:
1. GENERATING - генерация мира с прогресс-баром (фоновый поток)
2. CAT_FALL - падающий котик (чёрный фон)
3. WORLD_REVEAL - анимация раскрытия мира (круг расширяется от центра)

После WORLD_REVEAL - переход к PLAYING, ввод разблокируется.
"""

from __future__ import annotations

import glob
import math
import random
import threading
import time
from enum import Enum, auto
from typing import TYPE_CHECKING

import arcade
from PIL import Image, ImageDraw

from src.world.generator import GenerationConfig, WorldGenerator
from src.world.models import World

if TYPE_CHECKING:
    from src.engine.game_window import FlatCraftWindow


class LoadingPhase(Enum):
    """Фазы экрана загрузки."""

    GENERATING = auto()
    CAT_FALL = auto()
    WORLD_REVEAL = auto()
    PLAYING = auto()


# Цвета
_BG_GENERATING: tuple[int, int, int] = (10, 25, 80)
_BG_BLACK: tuple[int, int, int] = (0, 0, 0)
_PROGRESS_BAR_BG: tuple[int, int, int] = (30, 50, 100)
_PROGRESS_BAR_FG: tuple[int, int, int] = (80, 180, 255)
_TEXT_COLOR: tuple[int, int, int] = (200, 220, 255)

# Шрифт
_FONT: str = "JetBrains Mono"

# Длительности фаз (секунды)
_CAT_FALL_DURATION: float = 1.0
_REVEAL_DURATION: float = 1.5

# Маска: обновление каждые N кадров
_MASK_UPDATE_INTERVAL: int = 2

# Анимация котика на прогресс-баре
_BAR_CAT_FPS: float = 8.0
_BAR_CAT_FOLDER: str = "assets/nyan_cat/right"

# Фон экрана загрузки (рандомный выбор)
_LOADING_BG_GLOB: str = "assets/pics/loading_screen_*.png"


def _ease_in_quad(t: float) -> float:
    """Квадратичный ease-in - имитация гравитации."""
    return t * t


def _ease_out_cubic(t: float) -> float:
    """Кубический ease-out - быстрый старт, замедление."""
    return 1.0 - (1.0 - t) ** 3


class LoadingScreen:
    """Экран загрузки.

    Управляет тремя фазами анимации перед переходом к игровому процессу.
    Генерация мира выполняется в фоновом потоке.

    Attributes:
        phase: Текущая фаза загрузки.
        world: Сгенерированный мир (доступен после GENERATING).
    """

    def __init__(
        self,
        window: FlatCraftWindow,
        config: GenerationConfig,
        tile_size: int,
    ) -> None:
        """Инициализация экрана загрузки.

        Args:
            window: Игровое окно.
            config: Настройки генерации мира.
            tile_size: Размер тайла в пикселях.
        """
        self._window = window
        self._config = config
        self._tile_size = tile_size

        self.phase: LoadingPhase = LoadingPhase.GENERATING

        # Фаза 1: GENERATING
        self._gen_progress: float = 0.0
        self._gen_step_name: str = "Подготовка..."
        self._gen_done: bool = False
        self._subsystems_ready: bool = False
        self._world: World | None = None
        self._gen_thread: threading.Thread | None = None

        # Фон экрана загрузки (рандомный выбор при каждом запуске)
        self._bg_texture: arcade.Texture | None = None
        bg_paths = sorted(glob.glob(_LOADING_BG_GLOB))
        if bg_paths:
            chosen = random.choice(bg_paths)
            try:
                self._bg_texture = arcade.load_texture(chosen)
            except (FileNotFoundError, OSError):
                pass

        # Котик на конце прогресс-бара
        self._bar_cat_textures: list[arcade.Texture] = []
        self._bar_cat_start_time: float = time.monotonic()
        self._bar_cat_sprite: arcade.Sprite | None = None
        self._load_bar_cat_textures()

        # Текстовые объекты
        self._title_text: arcade.Text = arcade.Text(
            "FlatCraft",
            0, 0,
            _TEXT_COLOR,
            font_size=46,
            anchor_x="center",
            anchor_y="center",
            font_name=_FONT,
        )
        self._step_text: arcade.Text = arcade.Text(
            self._gen_step_name,
            0, 0,
            _TEXT_COLOR,
            font_size=14,
            anchor_x="center",
            anchor_y="center",
            font_name=_FONT,
        )
        self._pct_text: arcade.Text = arcade.Text(
            "0%",
            0, 0,
            _TEXT_COLOR,
            font_size=16,
            anchor_x="center",
            anchor_y="center",
            font_name=_FONT,
        )

        # Фаза 2: CAT_FALL
        self._cat_sprite: arcade.Sprite | None = None
        self._cat_start_y: float = 0.0
        self._cat_end_y: float = 0.0
        self._cat_elapsed: float = 0.0

        # Фаза 3: WORLD_REVEAL
        self._reveal_elapsed: float = 0.0
        self._mask_texture: arcade.Texture | None = None
        self._mask_sprite: arcade.Sprite | None = None
        self._mask_frame_counter: int = 0
        self._mask_counter: int = 0

        # Запуск генерации
        self._start_generation()

    # ================================================================
    # Загрузка текстур котика для прогресс-бара
    # ================================================================

    def _load_bar_cat_textures(self) -> None:
        """Загружает текстуры котика для прогресс-бара."""
        paths = sorted(glob.glob(f"{_BAR_CAT_FOLDER}/*.png"))
        for path in paths:
            img = Image.open(path).convert("RGBA")
            tex = arcade.Texture(image=img, size=img.size)
            self._bar_cat_textures.append(tex)

    # ================================================================
    # Публичный API
    # ================================================================

    def update(self, delta_time: float) -> None:
        """Обновление логики экрана загрузки.

        Вызывается каждый кадр из on_update окна.

        Args:
            delta_time: Время с прошлого кадра (сек).
        """
        if self.phase == LoadingPhase.GENERATING:
            self._update_generating(delta_time)
        elif self.phase == LoadingPhase.CAT_FALL:
            self._update_cat_fall(delta_time)
        elif self.phase == LoadingPhase.WORLD_REVEAL:
            self._update_reveal(delta_time)

    def draw(self) -> None:
        """Отрисовка экрана загрузки.

        Вызывается каждый кадр из on_draw окна.
        Для GENERATING и CAT_FALL - полная отрисовка включая фон.
        Для WORLD_REVEAL - только маска-оверлей.
        """
        if self.phase == LoadingPhase.GENERATING:
            self._draw_generating()
        elif self.phase == LoadingPhase.CAT_FALL:
            self._draw_cat_fall()
        elif self.phase == LoadingPhase.WORLD_REVEAL:
            self._draw_reveal()

    def is_done(self) -> bool:
        """проверяет, завершён ли экран загрузки."""
        return self.phase == LoadingPhase.PLAYING

    def is_world_ready(self) -> bool:
        """Проверяет, сгенерирован ли мир.

        Возвращает True после завершения GENERATING,
        даже если экран загрузки ещё показывает анимации.
        """
        return self._world is not None

    def notify_subsystems_ready(self) -> None:
        """Подсистемы созданы и чанки предзагружены.

        Вызывается game_window после создания Renderer/Camera/Player/HUD
        и предзагрузки чанков. LoadingScreen ждёт этого сигнала
        перед переходом к CAT_FALL.
        """
        self._subsystems_ready = True

    def get_world(self) -> World:
        """Возвращает сгенерированный мир.

        Returns:
            Объект World.

        Raises:
            RuntimeError: Если мир ещё не сгенерирован.
        """
        if self._world is None:
            raise RuntimeError("Мир ещё не сгенерирован")
        return self._world

    # ================================================================
    # Фаза 1: GENERATING - генерация мира
    # ================================================================

    def _start_generation(self) -> None:
        """Запускает генерацию мира в фоновом потоке."""
        from src.utils.profiling import GameProfiler as _GP

        _section_profiler = _GP()

        def _worker() -> None:
            with _section_profiler.section("world_generation"):
                generator = WorldGenerator(self._config)
                world = generator.generate(
                    on_progress=self._on_gen_progress
                )
                self._world = world
            self._gen_done = True

        self._gen_thread = threading.Thread(
            target=_worker, daemon=True
        )
        self._gen_thread.start()

    def _on_gen_progress(self, progress: float, step_name: str) -> None:
        """Callback прогресса генерации (вызывается из фонового потока).

        Args:
            progress: Прогресс 0..1.
            step_name: Имя текущего шага.
        """
        self._gen_progress = progress
        self._gen_step_name = step_name

    def _update_generating(self, delta_time: float) -> None:
        """Проверяет завершение генерации и готовность подсистем.

        Args:
            delta_time: Время с прошлого кадра (сек).
        """

        if self._gen_done and self._subsystems_ready:
            self.phase = LoadingPhase.CAT_FALL
            self._window.background_color = _BG_BLACK
            self._init_cat_fall()

    def _draw_generating(self) -> None:
        """Отрисовка фазы GENERATING: прогресс-бар + текст."""
        screen_w = self._window.width
        screen_h = self._window.height

        # Фон
        if self._bg_texture is not None:
            tw = self._bg_texture.width
            th = self._bg_texture.height
            scale = max(screen_w / tw, screen_h / th)
            dw = tw * scale
            dh = th * scale
            cx = screen_w / 2
            cy = screen_h / 2
            rect = arcade.rect.LRBT(
                cx - dw / 2, cx + dw / 2,
                cy - dh / 2, cy + dh / 2,
            )
            arcade.draw_texture_rect(self._bg_texture, rect)
        else:
            arcade.draw_lrbt_rectangle_filled(
                0, screen_w, 0, screen_h, _BG_GENERATING
            )

        # Прогресс-бар
        bar_w = int(screen_w * 0.6)
        bar_h = 20
        bar_left = (screen_w - bar_w) / 2
        bar_bottom = screen_h * 0.3

        # Заголовок FlatCraft
        self._title_text.x = screen_w / 2
        self._title_text.y = screen_h * 0.6
        self._title_text.draw()

        # Фон прогресс-бара
        arcade.draw_lbwh_rectangle_filled(
            bar_left, bar_bottom, bar_w, bar_h, _PROGRESS_BAR_BG
        )

        # Заполненная часть
        fill_w = int(bar_w * self._gen_progress)
        if fill_w > 0:
            arcade.draw_lbwh_rectangle_filled(
                bar_left, bar_bottom, fill_w, bar_h, _PROGRESS_BAR_FG
            )

        # Рамка прогресс-бара
        arcade.draw_lbwh_rectangle_outline(
            bar_left, bar_bottom, bar_w, bar_h, _TEXT_COLOR, border_width=1
        )

        # Котик на конце заполненной части прогресс-бара
        if self._bar_cat_textures and self._gen_progress > 0.01:
            elapsed = time.monotonic() - self._bar_cat_start_time
            frame = int(elapsed * _BAR_CAT_FPS) % len(self._bar_cat_textures)
            tex = self._bar_cat_textures[frame]
            cat_x = bar_left + fill_w
            cat_y = bar_bottom + bar_h / 2.0
            # Масштабируем котика по высоте прогресс-бара
            scale = (bar_h + 16) / tex.height
            if self._bar_cat_sprite is None:
                self._bar_cat_sprite = arcade.Sprite()
            self._bar_cat_sprite.texture = tex
            self._bar_cat_sprite.center_x = cat_x
            self._bar_cat_sprite.center_y = cat_y
            self._bar_cat_sprite.scale = scale
            arcade.draw_sprite(self._bar_cat_sprite)

        # Текст шага
        self._step_text.text = self._gen_step_name
        self._step_text.x = screen_w / 2
        self._step_text.y = bar_bottom - 30
        self._step_text.draw()

        # Проценты
        self._pct_text.text = f"{int(self._gen_progress * 100)}%"
        self._pct_text.x = screen_w / 2
        self._pct_text.y = bar_bottom + bar_h + 15
        self._pct_text.draw()

    # ================================================================
    # Фаза 2: CAT_FALL - падающий котик
    # ================================================================

    def _init_cat_fall(self) -> None:
        """Инициализация фазы CAT_FALL."""
        screen_w = self._window.width
        screen_h = self._window.height

        # Загружаем спрайт котика
        cat_texture = arcade.load_texture(
            "assets/nyan_cat/down/cat_2.png"
        )
        cat_h = cat_texture.height

        self._cat_sprite = arcade.Sprite()
        self._cat_sprite.texture = cat_texture
        self._cat_sprite.center_x = screen_w / 2

        # Старт: за верхним краем экрана
        self._cat_start_y = screen_h + cat_h / 2
        # Конец: центр экрана
        self._cat_end_y = screen_h / 2

        self._cat_sprite.center_y = self._cat_start_y
        self._cat_elapsed = 0.0

    def _update_cat_fall(self, delta_time: float) -> None:
        """Обновление фазы CAT_FALL: падение котика.

        Args:
            delta_time: Время с прошлого кадра (сек).
        """
        self._cat_elapsed += delta_time
        t = min(self._cat_elapsed / _CAT_FALL_DURATION, 1.0)

        delta_y = self._cat_end_y - self._cat_start_y
        if self._cat_sprite is not None:
            self._cat_sprite.center_y = (
                self._cat_start_y + delta_y * _ease_in_quad(t)
            )

        if t >= 1.0:
            self.phase = LoadingPhase.WORLD_REVEAL
            self._window.background_color = (10, 25, 80)
            self._init_reveal()

    def _draw_cat_fall(self) -> None:
        """Отрисовка фазы CAT_FALL: падающий котик."""
        if self._cat_sprite is not None:
            arcade.draw_sprite(self._cat_sprite)

    # ================================================================
    # Фаза 3: WORLD_REVEAL - раскрытие мира
    # ================================================================

    def _init_reveal(self) -> None:
        """Инициализация фазы WORLD_REVEAL."""
        self._reveal_elapsed = 0.0
        self._mask_frame_counter = 0

        self._mask_texture = self._build_mask_texture(0)
        self._mask_sprite = arcade.Sprite()
        self._mask_sprite.texture = self._mask_texture

        self._mask_sprite.scale = 2.0
        self._mask_sprite.center_x = self._window.width / 2
        self._mask_sprite.center_y = self._window.height / 2

    def _update_reveal(self, delta_time: float) -> None:
        """Обновление фазы WORLD_REVEAL: расширяющийся круг.

        Args:
            delta_time: Время с прошлого кадра (сек).
        """
        self._reveal_elapsed += delta_time
        t = min(self._reveal_elapsed / _REVEAL_DURATION, 1.0)

        screen_w = self._window.width
        screen_h = self._window.height
        max_radius = math.sqrt(screen_w**2 + screen_h**2)
        radius = max_radius * _ease_out_cubic(t)

        # Обновляем маску каждые N кадров
        self._mask_frame_counter += 1
        if self._mask_frame_counter >= _MASK_UPDATE_INTERVAL:
            self._mask_frame_counter = 0
            self._mask_texture = self._build_mask_texture(radius)
            if self._mask_sprite is not None:
                self._mask_sprite.texture = self._mask_texture
                self._mask_sprite.center_x = screen_w / 2
                self._mask_sprite.center_y = screen_h / 2

        if t >= 1.0:
            self.phase = LoadingPhase.PLAYING
            # Очистка ресурсов маски
            self._mask_sprite = None
            self._mask_texture = None

    def _draw_reveal(self) -> None:
        """Отрисовка фазы WORLD_REVEAL: только маска-оверлей.

        Мир отрисовывается окном (game_window.on_draw) ДО вызова
        этого метода. Здесь рисуем только чёрную маску поверх.
        """
        if self._mask_sprite is not None:
            arcade.draw_sprite(self._mask_sprite)

    def _build_mask_texture(self, radius: float) -> arcade.Texture:
        """Создаёт текстуру маски с прозрачным кругом.

        Маска создаётся в 1/2 разрешении экрана и масштабируется
        для оптимизации. NEAREST-фильтр для чётких краёв круга.

        Args:
            radius: Радиус прозрачного круга.

        Returns:
            arcade.Texture с маской.
        """
        screen_w = self._window.width
        screen_h = self._window.height

        half_w = max(screen_w // 2, 1)
        half_h = max(screen_h // 2, 1)
        half_radius = radius / 2.0

        # RGBA-изображение
        img = Image.new("RGBA", (half_w, half_h), (0, 0, 0, 255))
        draw = ImageDraw.Draw(img)

        # Прозрачный круг в центре
        cx = half_w / 2.0
        cy = half_h / 2.0
        r = half_radius

        if r > 0:
            draw.ellipse(
                [cx - r, cy - r, cx + r, cy + r],
                fill=(0, 0, 0, 0),
            )

        # Конвертируем в arcade.Texture с уникальным хешем,
        # чтобы не кэшировалось при обновлении маски
        self._mask_counter += 1
        texture = arcade.Texture(
            image=img,
            hit_box_algorithm=None,
            hash=f"loading_mask_{self._mask_counter}",
        )

        return texture
