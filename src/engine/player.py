"""Игровой персонаж - Nyan Cat с анимацией и направлением."""

from __future__ import annotations

import glob
import math
from typing import TYPE_CHECKING, Optional

import arcade
from PIL import Image
from src.world.models import Biome, World

if TYPE_CHECKING:
    from src.engine.input_manager import InputManager

# Папки с анимациями
_CAT_FOLDERS: dict[str, str] = {
    "top": "assets/nyan_cat/top",
    "down": "assets/nyan_cat/down",
    "right": "assets/nyan_cat/right",
}

# Папки с анимациями плывущего котика
_WATER_CAT_FOLDERS: dict[str, str] = {
    "top": "assets/nyan_cat_water/top",
    "down": "assets/nyan_cat_water/down",
    "right": "assets/nyan_cat_water/right",
}

# Скорость в тайлах/секунду
_WALK_SPEED: float = 5.0
_RUN_SPEED: float = 10.0

# Частота смены кадров анимации
_ANIM_FPS: float = 8.0

# Параметры инерции для скольжения на льду и воде
# Lerp-скорость: насколько быстро скорость приближается
# к целевой. Большее значение = отзывчивее управление.
_GROUND_LERP: float = 50.0  # обычная поверхность - быстро
_WATER_LERP: float = 8.0  # вода - умеренное скольжение
_ICE_LERP: float = 3.0  # лёд - медленно, скольжение

# Порог скорости - ниже считаем что стоит
_VEL_THRESHOLD: float = 0.5

# Звуки шагов по типу поверхности
_STEP_SOUNDS: dict[str, str] = {
    "grass": "assets/music/grass_steps.mp3",
    "sand": "assets/music/steps.mp3",
    "water": "assets/music/swimming_cat.mp3",
    "ice": "assets/music/ice.mp3",
}

# Маппинг биом -> тип звука шагов
_BIOME_STEP_TYPE: dict[Biome, str] = {
    Biome.FOREST: "grass",
    Biome.GRASSLAND: "grass",
    Biome.TAIGA: "grass",
    Biome.TUNDRA: "grass",
    Biome.BEACH: "sand",
    Biome.DESERT: "sand",
    Biome.SAVANNA: "sand",
    Biome.SNOW: "sand",
    Biome.DEEP_OCEAN: "water",
    Biome.OCEAN: "water",
    Biome.FROZEN_OCEAN: "ice",
}

# Громкость шагов
_STEP_VOLUME: float = 0.3

# Длительность плавного затухания звука на воде/льду (сек)
_STEP_FADE_DURATION: float = 0.3

# Типы поверхностей с инерцией - для них плавное затухание
_SLIPPERY_TYPES: frozenset[str] = frozenset({"water", "ice"})

# Звуки биомов
_AMBIENT_SOUNDS: dict[Biome, str] = {
    Biome.BEACH: "assets/music/beach.mp3",
    Biome.DESERT: "assets/music/desert.mp3",
    Biome.SAVANNA: "assets/music/desert.mp3",
    Biome.GRASSLAND: "assets/music/grassland.mp3",
    Biome.FOREST: "assets/music/forest.mp3",
    Biome.TAIGA: "assets/music/taiga.mp3",
    Biome.TUNDRA: "assets/music/tundra.mp3",
    Biome.SNOW: "assets/music/winter.mp3",
}

# Громкость звуков биомов
_AMBIENT_VOLUME: float = 0.3

# Длительность перехода между биомами (сек)
_AMBIENT_CROSSFADE: float = 1.0


class Player:
    """Игровой персонаж Nyan Cat.

    Перемещается стрелками/WASD, камера следует за ним.
    Отрисовывается в мировых координатах в слое объектов
    с учётом Z-порядка.

    Attributes:
        x: Позиция X в пикселях мира.
        y: Позиция Y в пикселях мира.
    """

    def __init__(
        self,
        world_w: int,
        world_h: int,
        tile_size: int = 32,
        world: Optional[World] = None,
    ) -> None:
        """Инициализация персонажа.

        Args:
            world_w: Ширина мира в тайлах.
            world_h: Высота мира в тайлах.
            tile_size: Размер тайла в пикселях.
            world: Объект мира. Если None - скольжение отключено.
        """
        self._world_w = world_w
        self._world_h = world_h
        self._tile_size = tile_size
        self._world = world

        # Позиция в пикселях мира (центр персонажа)
        self.x: float = world_w * tile_size / 2.0
        self.y: float = world_h * tile_size / 2.0

        # Скорость в пикселях/сек (инерция для скольжения)
        self._vx: float = 0.0
        self._vy: float = 0.0

        # Направление и анимация
        self._direction: str = "down"
        self._frame: int = 0
        self._frame_timer: float = 0.0
        self._moving: bool = False
        self._last_dx: float = 0.0
        self._last_dy: float = 0.0

        # Текстуры анимации: direction -> список кадров
        self._textures: dict[str, list[arcade.Texture]] = {}
        self._water_textures: dict[str, list[arcade.Texture]] = {}
        self._load_textures()

        # Состояние поверхности
        self._on_water: bool = False
        self._prev_on_water: bool = False

        # Звуки шагов
        self._step_sounds: dict[str, arcade.Sound] = {}
        self._step_player = None  # pyglet.media.Player
        self._step_type: Optional[str] = None
        self._step_fade: float = 0.0  # оставшееся время затухания
        self._load_step_sounds()

        # Звуки биомов (фоновая атмосфера)
        self._ambient_sounds: dict[Biome, arcade.Sound] = {}
        self._ambient_current_biome: Optional[Biome] = None
        self._ambient_current_player = None  # pyglet.media.Player
        self._ambient_fade_biome: Optional[Biome] = None
        self._ambient_fade_player = None  # pyglet.media.Player (затухающий)
        self._ambient_fade_timer: float = 0.0
        self._load_ambient_sounds()

        # Спрайт для отрисовки (в мировых координатах)
        self._sprite: Optional[arcade.Sprite] = None

    # ================================================================
    # Загрузка текстур
    # ================================================================

    def _load_textures(self) -> None:
        """Загружает текстуры анимации из папок.

        Пиксель-в-пиксель, без сжатия.
        Left = отражённый right.
        Отдельный набор текстур для плавания на воде.
        """
        for direction, folder in _CAT_FOLDERS.items():
            paths = sorted(glob.glob(f"{folder}/*.png"))
            frames: list[arcade.Texture] = []
            for path in paths:
                img = Image.open(path).convert("RGBA")
                tex = arcade.Texture(image=img, size=img.size)
                frames.append(tex)
            self._textures[direction] = frames

        # "left" = отражённый "right"
        if "right" in self._textures:
            left_frames: list[arcade.Texture] = []
            for tex in self._textures["right"]:
                flipped_img = tex.image.transpose(
                    Image.Transpose.FLIP_LEFT_RIGHT
                )
                flipped_tex = arcade.Texture(
                    image=flipped_img, size=flipped_img.size
                )
                left_frames.append(flipped_tex)
            self._textures["left"] = left_frames

        # Текстуры плывущего котика
        for direction, folder in _WATER_CAT_FOLDERS.items():
            paths = sorted(glob.glob(f"{folder}/*.png"))
            frames: list[arcade.Texture] = []
            for path in paths:
                img = Image.open(path).convert("RGBA")
                tex = arcade.Texture(image=img, size=img.size)
                frames.append(tex)
            self._water_textures[direction] = frames

        # "left" = отражённый "right" для водяных текстур
        if "right" in self._water_textures:
            left_frames: list[arcade.Texture] = []
            for tex in self._water_textures["right"]:
                flipped_img = tex.image.transpose(
                    Image.Transpose.FLIP_LEFT_RIGHT
                )
                flipped_tex = arcade.Texture(
                    image=flipped_img, size=flipped_img.size
                )
                left_frames.append(flipped_tex)
            self._water_textures["left"] = left_frames

    def _load_step_sounds(self) -> None:
        """Загружает звуки шагов для каждого типа поверхности."""
        for step_type, path in _STEP_SOUNDS.items():
            try:
                self._step_sounds[step_type] = arcade.Sound(path)
            except (FileNotFoundError, OSError):
                pass

    def _update_step_sound(
        self, dt: float = 0.0, keys_pressed: bool = False
    ) -> None:
        """Управляет звуком шагов: запуск/остановка по биому и движению.

        Звук играет зацикленно, пока нажаты кнопки движения.
        При отпускании кнопок на скользкой поверхности (вода/лёд) -
        плавное затухание за _STEP_FADE_DURATION секунд.
        При отпускании кнопок на обычной поверхности - мгновенная
        остановка. При полной остановке (скорость < порога) -
        тоже мгновенная остановка.
        """
        # Обновляем затухание, если активно
        if self._step_fade > 0:
            self._step_fade -= dt
            if self._step_fade <= 0:
                # Затухание завершено - остановить звук
                self._step_fade = 0.0
                if self._step_player is not None and self._step_type is not None:
                    sound = self._step_sounds.get(self._step_type)
                    if sound is not None:
                        try:
                            sound.stop(self._step_player)
                        except Exception:
                            pass
                    self._step_player = None
                self._step_type = None
                return
            # Уменьшаем громкость пропорционально оставшемуся времени
            ratio = self._step_fade / _STEP_FADE_DURATION
            if self._step_player is not None:
                try:
                    self._step_player.volume = _STEP_VOLUME * ratio
                except Exception:
                    pass
            # Если кнопки снова нажаты - отменяем затухание
            if keys_pressed:
                self._step_fade = 0.0
                if self._step_player is not None:
                    try:
                        self._step_player.volume = _STEP_VOLUME
                    except Exception:
                        pass
            return

        # Определяем тип поверхности по биому
        biome = self._get_current_biome()
        new_type = _BIOME_STEP_TYPE.get(biome) if biome else None

        # Кнопки не нажаты - начать затухание или остановить
        if not keys_pressed:
            if self._step_player is not None and self._step_type is not None:
                # На скользкой поверхности - плавное затухание
                if self._step_type in _SLIPPERY_TYPES and self._moving:
                    self._step_fade = _STEP_FADE_DURATION
                    return
                # На обычной или полностью остановился - мгновенно
                sound = self._step_sounds.get(self._step_type)
                if sound is not None:
                    try:
                        sound.stop(self._step_player)
                    except Exception:
                        pass
                self._step_player = None
            self._step_type = None
            return

        # Нет звука для данного биома - остановить текущий
        if new_type is None or new_type not in self._step_sounds:
            if self._step_player is not None and self._step_type is not None:
                sound = self._step_sounds.get(self._step_type)
                if sound is not None:
                    try:
                        sound.stop(self._step_player)
                    except Exception:
                        pass
                self._step_player = None
            self._step_type = None
            return

        # Тот же тип - продолжаем играть
        if new_type == self._step_type and self._step_player is not None:
            return

        # Смена типа поверхности - остановить старый, запустить новый
        if self._step_player is not None and self._step_type is not None:
            old_sound = self._step_sounds.get(self._step_type)
            if old_sound is not None:
                try:
                    old_sound.stop(self._step_player)
                except Exception:
                    pass

        # Запускаем новый звук
        sound = self._step_sounds[new_type]
        try:
            self._step_player = sound.play(
                volume=_STEP_VOLUME, loop=True
            )
            self._step_type = new_type
        except Exception:
            self._step_player = None
            self._step_type = None

    def stop_step_sound(self) -> None:
        """Принудительно останавливает звук шагов (при выходе в меню)."""
        if self._step_player is not None and self._step_type is not None:
            sound = self._step_sounds.get(self._step_type)
            if sound is not None:
                try:
                    sound.stop(self._step_player)
                except Exception:
                    pass
        self._step_player = None
        self._step_type = None

    def _load_ambient_sounds(self) -> None:
        """Загружает звуки для каждого биома."""
        for biome, path in _AMBIENT_SOUNDS.items():
            try:
                self._ambient_sounds[biome] = arcade.Sound(path)
            except (FileNotFoundError, OSError):
                pass

    @staticmethod
    def _stop_player(
        sound: arcade.Sound | None, player: object
    ) -> None:
        """Останавливает pyglet-плеер для данного звука."""
        if sound is not None and player is not None:
            try:
                sound.stop(player)
            except Exception:
                pass

    def _update_ambient_sound(self, dt: float) -> None:
        """Управляет звуками биомов с кроссфейдом.

        При смене биома старый звук плавно затухает,
        а новый одновременно нарастает за _AMBIENT_CROSSFADE
        секунд. Для биомов без звука - тишина,
        но эффект затухания сохраняется.
        """
        # --- Обновляем кроссфейд, если активен ---
        if self._ambient_fade_timer > 0:
            self._ambient_fade_timer -= dt
            if self._ambient_fade_timer <= 0:
                # Кроссфейд завершён - полностью остановить старый
                self._ambient_fade_timer = 0.0
                if self._ambient_fade_biome is not None:
                    old_sound = self._ambient_sounds.get(
                        self._ambient_fade_biome
                    )
                    self._stop_player(
                        old_sound, self._ambient_fade_player
                    )
                self._ambient_fade_player = None
                self._ambient_fade_biome = None
                # Текущий звук - полная громкость
                if self._ambient_current_player is not None:
                    try:
                        self._ambient_current_player.volume = (
                            _AMBIENT_VOLUME
                        )
                    except Exception:
                        pass
            else:
                # Кроссфейд в процессе
                ratio = self._ambient_fade_timer / _AMBIENT_CROSSFADE
                # Старый звук затухает
                if self._ambient_fade_player is not None:
                    try:
                        self._ambient_fade_player.volume = (
                            _AMBIENT_VOLUME * ratio
                        )
                    except Exception:
                        pass
                # Новый звук нарастает
                if self._ambient_current_player is not None:
                    try:
                        self._ambient_current_player.volume = (
                            _AMBIENT_VOLUME * (1.0 - ratio)
                        )
                    except Exception:
                        pass
            return

        # --- Проверяем текущий биом ---
        biome = self._get_current_biome()

        # Тот же биом - ничего не делаем
        if biome == self._ambient_current_biome:
            return

        # Биом сменился - запускаем кроссфейд
        old_biome = self._ambient_current_biome
        old_player = self._ambient_current_player

        # Определяем, есть ли звук у нового биома
        new_sound = (
            self._ambient_sounds.get(biome) if biome else None
        )

        if new_sound is not None:
            # Запускаем новый звук с нулевой громкостью
            try:
                new_player = new_sound.play(
                    volume=0.0, loop=True
                )
            except Exception:
                new_player = None
            self._ambient_current_biome = biome
            self._ambient_current_player = new_player
        else:
            # Биом без звука - тишина
            self._ambient_current_biome = biome
            self._ambient_current_player = None

        # Настраиваем затухание старого звука
        if old_player is not None and old_biome is not None:
            self._ambient_fade_biome = old_biome
            self._ambient_fade_player = old_player
            self._ambient_fade_timer = _AMBIENT_CROSSFADE
        # Если старого звука не было - кроссфейд не нужен,
        # но таймер всё равно запускаем для нарастания нового
        elif self._ambient_current_player is not None:
            # Новый звук должен нарастать от 0
            self._ambient_fade_biome = None
            self._ambient_fade_player = None
            self._ambient_fade_timer = _AMBIENT_CROSSFADE

    def stop_ambient_sound(self) -> None:
        """Принудительно останавливает все звуки биомов."""
        if (
            self._ambient_current_player is not None
            and self._ambient_current_biome is not None
        ):
            sound = self._ambient_sounds.get(
                self._ambient_current_biome
            )
            self._stop_player(sound, self._ambient_current_player)
        if (
            self._ambient_fade_player is not None
            and self._ambient_fade_biome is not None
        ):
            sound = self._ambient_sounds.get(
                self._ambient_fade_biome
            )
            self._stop_player(sound, self._ambient_fade_player)
        self._ambient_current_biome = None
        self._ambient_current_player = None
        self._ambient_fade_biome = None
        self._ambient_fade_player = None
        self._ambient_fade_timer = 0.0

    # ================================================================
    # Обновление
    # ================================================================

    def update(self, dt: float, input_mgr: InputManager) -> None:
        """Обновляет позицию, направление и анимацию.

        На льду (FROZEN_OCEAN) движение инерционное -
        котик скользит. На воде - умеренное скольжение.
        На обычной поверхности - резкая остановка.

        Args:
            dt: Время с прошлого кадра (сек).
            input_mgr: Менеджер ввода (клавиатура + геймпад).
        """
        from src.engine.input_manager import Action

        # Вектор движения из InputManager (аналоговый для геймпада)
        dx, dy = input_mgr.get_movement()
        self._last_dx = dx
        self._last_dy = dy

        # Целевая скорость (тайлы/сек -> пиксели/сек)
        speed = (
            (_RUN_SPEED if input_mgr.is_pressed(Action.RUN) else _WALK_SPEED)
            * self._tile_size
        )
        target_vx = dx * speed
        target_vy = dy * speed

        # Lerp-скорость зависит от поверхности
        on_ice = self._is_on_ice()
        self._on_water = self._is_on_water()
        if on_ice:
            lerp = _ICE_LERP
        elif self._on_water:
            lerp = _WATER_LERP
        else:
            lerp = _GROUND_LERP

        # При смене поверхности (земля<->вода) сбрасываем кадр,
        # т.к. наборы текстур могут иметь разное число кадров
        if self._on_water != self._prev_on_water:
            self._frame = 0
            self._frame_timer = 0.0
            self._prev_on_water = self._on_water

        # Плавное приближение к целевой скорости
        # lerp * dt - чтобы не зависеть от FPS
        factor = min(lerp * dt, 1.0)
        self._vx += (target_vx - self._vx) * factor
        self._vy += (target_vy - self._vy) * factor

        # На обычной поверхности - мгновенная остановка
        # при отпускании клавиш
        # На льду - медленное торможение

        # Определяем "движется ли" по фактической скорости
        vel = math.sqrt(self._vx ** 2 + self._vy ** 2)
        self._moving = vel > _VEL_THRESHOLD

        # Сдвиг позиции
        self.x += self._vx * dt
        self.y += self._vy * dt

        # Ограничение - не выходить за край мира
        ts = self._tile_size
        half = ts / 2.0
        self.x = max(half, min(self._world_w * ts - half, self.x))
        self.y = max(half, min(self._world_h * ts - half, self.y))

        # Определяем направление для анимации
        # по нажатым клавишам
        if dx != 0.0 or dy != 0.0:
            if abs(dx) >= abs(dy):
                self._direction = "right" if dx > 0 else "left"
            else:
                self._direction = "top" if dy > 0 else "down"

        # Анимация кадров
        # На льду/воде при отпускании клавиш - замораживаем анимацию
        tex_set = self._water_textures if self._on_water else self._textures
        keys_pressed = dx != 0.0 or dy != 0.0
        if keys_pressed:
            self._frame_timer += dt
            interval = 1.0 / _ANIM_FPS
            while self._frame_timer >= interval:
                self._frame_timer -= interval
                frames = tex_set.get(self._direction, [])
                if frames:
                    self._frame = (self._frame + 1) % len(frames)
        elif not self._moving:
            # Полностью остановился - сброс на стоячую позу
            self._frame = 0
            self._frame_timer = 0.0

        # Обновляем звук шагов (передаём dt и keys_pressed)
        self._update_step_sound(dt, keys_pressed=keys_pressed)

        # Обновляем звук биома (переход)
        self._update_ambient_sound(dt)

    def _get_current_biome(self) -> Optional[Biome]:
        """Возвращает биом текущего тайла под котиком.

        Returns:
            Biome или None, если мир не задан / координаты вне мира.
        """
        if self._world is None:
            return None

        ts = self._tile_size
        tx = int(self.x / ts)
        ty = self._world.height - 1 - int(self.y / ts)

        tx = max(0, min(self._world.width - 1, tx))
        ty = max(0, min(self._world.height - 1, ty))

        tile = self._world.get_tile(tx, ty)
        if tile is None:
            return None
        return tile.biome

    def _is_on_ice(self) -> bool:
        """Проверяет, стоит ли котик на льду.

        Returns:
            True если текущий тайл - лёд.
        """
        return self._get_current_biome() == Biome.FROZEN_OCEAN

    def _is_on_water(self) -> bool:
        """Проверяет, плывёт ли котик по воде.

        Вода - биомы DEEP_OCEAN и OCEAN.

        Returns:
            True если текущий тайл - вода.
        """
        biome = self._get_current_biome()
        return biome in (Biome.DEEP_OCEAN, Biome.OCEAN)

    # ================================================================
    # Спрайт для отрисовки
    # ================================================================

    def get_sprite(self) -> arcade.Sprite:
        """Возвращает спрайт котика в мировых координатах.

        Спрайт используется для Z-сортировки с объектами.
        Основание спрайта привязано к центру тайла.
        """
        tex_set = self._water_textures if self._on_water else self._textures
        frames = tex_set.get(self._direction, [])
        tex = frames[self._frame % len(frames)] if frames else None

        # Позиция: основание в центре тайла
        px_h = tex.height if tex else self._tile_size
        draw_cy = self.y + px_h / 2.0

        if self._sprite is None:
            if tex is not None:
                self._sprite = arcade.Sprite(
                    tex, center_x=self.x, center_y=draw_cy
                )
                self._sprite.width = tex.width
                self._sprite.height = tex.height
            else:
                self._sprite = arcade.SpriteSolidColor(
                    width=self._tile_size,
                    height=self._tile_size,
                    color=(255, 165, 0, 255),
                    center_x=self.x,
                    center_y=draw_cy,
                )
        else:
            if tex is not None:
                self._sprite.texture = tex
                self._sprite.width = tex.width
                self._sprite.height = tex.height
            self._sprite.center_x = self.x
            self._sprite.center_y = draw_cy

        # Угол поворота для диагонального бега
        self._sprite.angle = self._compute_angle()

        return self._sprite

    def _compute_angle(self) -> float:
        """Вычисляет угол поворота для диагонального бега.

        Поворачивается только боковая анимация (right/left).
        При направлении "влево" текстура уже отражена,
        поэтому угол нужно инвертировать.
        """
        dx, dy = self._last_dx, self._last_dy

        # Поворот только для боковых направлений
        if self._direction not in ("right", "left"):
            return 0.0
        if dx == 0.0 or dy == 0.0:
            return 0.0

        # Поворачиваем боковую анимацию
        if dy > 0:  # вверх-вправо/влево
            angle = -45.0
        else:  # вниз-вправо/влево
            angle = 45.0

        # При отражённой текстуре (влево) угол визуально
        # инвертируется
        if self._direction == "left":
            angle = -angle

        return angle

    # ================================================================
    # Позиция для камеры
    # ================================================================

    @property
    def world_x(self) -> float:
        """X-позиция в пикселях мира."""
        return self.x

    @property
    def world_y(self) -> float:
        """Y-позиция в пикселях мира."""
        return self.y
