"""Rocket Geodome - Fusion add-in, v1.0 (free release).

Dialog with all parameters, presets, live results and a wireframe preview, in
English or Russian (Language / Язык at the top, English by default, remembered).
Build modes: Full dome (one component per part type, an occurrence at every
place, floor sketch, BOM CSV), Skeleton (wireframe sketch) and Test hub (one
hub with stubs for a trial cut). Base shapes: hemisphere, on straight walls,
arches on legs with foot platforms. Model scale 1:N builds a printable model of
the same dome with print thicknesses, clearance and hole, plus tubes and an
STL export per part type. Sheet layout: the flat parts lie on sheets beside
the dome (or on the print bed of a model) and go out as one DXF per sheet.
A disclaimer has to be accepted once. Parameters are stored in the dome's
attributes.
"""
import importlib
import json
import math
import os
import re
import time
import traceback
import webbrowser

import adsk.core
import adsk.fusion

from . import geodome_core as core
from . import sheet_layout as layout

VERSION_TEXT = 'v' + '.'.join(core.VERSION.split('.')[:2])
CMD_ID = 'RocketGeodome_Dome'
CMD_NAME = 'Rocket Geodome ' + VERSION_TEXT
CMD_TIP = ('Geodesic dome frame from CNC plywood: 2V / 4V / 6V hemisphere, on straight walls '
           'or on five arched legs. Sheet layout and DXF. / Геокупол из фанеры под ЧПУ.')
KOFI_URL = 'https://ko-fi.com/sashavmire'
INSTAGRAM_URL = 'https://www.instagram.com/sashavmire/'
TELEGRAM_URL = 'https://t.me/fusion2van'
DISCLAIMER_VERSION = '1.0'                 # accepted once per version of the text
LANGS = (('en', 'English'), ('ru', 'Русский'))
PANEL_ID = 'SolidCreatePanel'
ATTR_GROUP = 'RocketGeodome'
ADDIN_DIR = os.path.dirname(os.path.abspath(__file__))
RESOURCES = os.path.join(ADDIN_DIR, 'resources')   # toolbar icon 16 / 32 / 64 px
PRESETS_PATH = os.path.join(ADDIN_DIR, 'presets.json')
PRESETS_DEFAULT_PATH = os.path.join(ADDIN_DIR, 'presets.default.json')
NO_PRESET = ('(текущие)', '(current)')    # the "no preset" line of the presets list: Russian, English

# Dialog texts: field -> (label, tooltip in Russian, tooltip in English)
TEXT = {
    'preset': ('Пресет (Preset)',
               'Сохранённые наборы параметров. Выбери пресет, и все поля заполнятся его значениями.',
               'Saved parameter sets. Pick one and every field is filled in with its values.'),
    'preset_name': ('Имя пресета (Save as)',
                    'Имя, под которым сохранить текущие параметры.',
                    'Name to save the current parameters under.'),
    'preset_save': ('Сохранить (Save preset)',
                    'Сохраняет все текущие параметры под именем из поля выше. Пресеты лежат в файле '
                    'presets.json рядом с плагином, обновления плагина их не затирают.',
                    'Saves all current parameters under the name above. Presets live in presets.json '
                    'next to the add-in; updates never overwrite them.'),
    'build_mode': ('Что строить (Build)',
                   'Полный купол — все детали на своих местах. Скелет — только каркас линиями в эскизе. '
                   'Пробный узел — один узел с обрезками рёбер для тестового реза.',
                   'Full dome: every part in place. Skeleton: the frame as lines in a sketch only. '
                   'Test hub: one hub with strut stubs for a trial cut.'),
    'bom_csv': ('Спецификация CSV (BOM CSV)',
                'После сборки купола предложит сохранить спецификацию в CSV: детали, количество, '
                'размеры, площадь фанеры, вес и крепёж.',
                'After building the dome, offers to save the bill of materials as CSV: parts, '
                'quantities, sizes, plywood area, weight and hardware.'),
    'export_stl': ('Экспорт STL (Export STL)',
                   'Только для модели. После сборки спросит папку и сохранит каждый тип детали отдельным STL: '
                   'деталь лежит плашмя маркировкой вверх, в имени количество — «Plate H6a x20.stl».',
                   'Model only. After building, asks for a folder and saves each part type as its own STL: '
                   'lying flat, labels up, the count in the name, e.g. "Plate H6a x20.stl".'),
    'model_scale': ('Масштаб 1 : N (Model scale)',
                    'Модель для 3D-печати. Вводишь настоящий купол и ставишь N — плагин строит его в N раз '
                    'меньше вместе со своими внутренними размерами. Толщины, зазор, отверстие, буквы и стол '
                    'берутся из полей ниже, dogbones не нужны. 1 — настоящий купол.',
                    'Model for 3D printing. Enter the real dome and set N: the add-in builds it N times smaller, '
                    'its internal sizes included. Thicknesses, clearance, hole, labels and the bed come from the '
                    'fields below; no dogbones. 1 means the real dome.'),
    'print_plywood': ('Толщина досок (Board thickness)',
                      'Толщина напечатанных досок и проставок модели. Не масштабируется.',
                      'Thickness of the printed boards and spacers. Not scaled.'),
    'print_plate': ('Толщина пластин (Plate thickness)',
                    'Толщина напечатанных пластин узла. Не масштабируется.',
                    'Thickness of the printed hub plates. Not scaled.'),
    'print_clearance': ('Зазор модели (Print clearance)',
                        'Зазор на сторону в шипах и пазах модели. 0,2 мм обычно подходит для FDM.',
                        'Clearance per side in the model joints. 0.2 mm usually suits FDM.'),
    'print_hole': ('Отверстие модели (Print hole)',
                   'Отверстие под болт в пластинах и втулке модели. 3,3 мм — под M3. 0 — без болтов и втулок.',
                   'Bolt hole in the model plates and tubes. 3.3 mm suits M3. 0 means no bolts and no tubes.'),
    'print_labels': ('Маркировка модели (Print labels)',
                     'Гравировать модель жирным шрифтом: буква ребра на каждой доске, цифра типа на каждой '
                     'пластине (1 = H5a, 2 = H6a… — расшифровка в результатах и в спецификации). На пластине '
                     'модели «H6a» не помещается, а цифра различает похожие узлы.',
                     'Engrave the model in bold: the strut letter on each board, the type digit on each plate '
                     '(1 = H5a, 2 = H6a... - the key is in the results and the BOM). "H6a" does not fit a model '
                     'plate; the digit tells look-alike hubs apart.'),
    'print_label_height': ('Высота букв модели (Print label height)',
                           'Высота букв на досках модели. Цифра на пластине такая же, если помещается, иначе '
                           'плагин сам её сдвинет или уменьшит. 8 мм хорошо читаются при печати соплом 0,4 мм.',
                           'Letter height on the model boards. The plate digit is the same if it fits, otherwise '
                           'the add-in moves or shrinks it. 8 mm reads well printed with a 0.4 mm nozzle.'),
    'print_label_depth': ('Глубина букв модели (Print label depth)',
                          'Насколько глубоко буквы и цифры врезаются в модель. 1 мм хорошо видно на печати. '
                          'Должна быть меньше толщины досок и пластин модели.',
                          'How deep the letters and digits are cut into the model. 1 mm shows well in print. '
                          'Must be less than the model board and plate thickness.'),
    'bed_len': ('Стол X (Bed X)',
                'Размер стола принтера (или лазера) по X: проверка, что каждая деталь помещается, и раскладка '
                'модели по столам. P2S — 256 мм.',
                'Print (or laser) bed size in X: the fit check and the layout of the model on beds use it. '
                'P2S: 256 mm.'),
    'bed_wid': ('Стол Y (Bed Y)',
                'Размер стола принтера по Y. P2S — 256 мм.',
                'Print bed size in Y. P2S: 256 mm.'),
    'diameter': ('Диаметр (Diameter)',
                 'Диаметр купола по наружным узлам — точкам, где рёбра сходятся снаружи. Наружные '
                 'пластины выступают ещё на свою толщину.',
                 'Dome diameter at the outer nodes, the points where the struts meet on the outside. '
                 'The outer plates stick out by their own thickness on top of that.'),
    'frequency': ('Частота (Frequency)',
                  'На сколько частей делится каждое ребро икосаэдра. Чем больше частота, тем больше '
                  'деталей, но они короче, а купол круглее.',
                  'How many pieces each icosahedron edge is split into. Higher means more but shorter '
                  'parts and a rounder dome.'),
    'base_shape': ('Основание (Base shape)',
                   'Полусфера — купол стоит прямо на полу. На стенах — под экватором прямые стены из стоек и '
                   'колец-обвязок, купол поднят на их высоту. Арки на ногах — пять ног-«V» под куполом и пять '
                   'стрельчатых арок-проходов между ними, как павильон Quadrome.',
                   'Hemisphere: the dome sits right on the floor. On walls: straight walls of posts and rings '
                   'under the equator lift the dome by their height. Arches on legs: five V legs under the dome '
                   'with five pointed arch openings between them, like a Quadrome pavilion.'),
    'wall_height': ('Высота стен (Wall height)',
                    'Только для «На стенах». От пола до середины нижнего кольца купола (экватора). Под каждым '
                    'узлом экватора — прямая стойка, внизу кольцо по полу.',
                    'On walls only. From the floor to the middle of the dome\'s bottom ring (the equator). A '
                    'straight post under every equator node, a ring on the floor.'),
    'wall_rows': ('Ярусы стен (Wall rows)',
                  'Только для «На стенах». На сколько частей кольца делят стойку по высоте: 1 — стойка от пола '
                  'до купола целиком, 2 — кольцо посередине и т. д. Диагоналей в стенах нет: жёсткость даёт '
                  'обшивка (OSB или фанера), она есть в спецификации.',
                  'On walls only. How many pieces the rings split each post into: 1 is floor to dome in one '
                  'piece, 2 adds a ring halfway, and so on. The walls have no diagonals: the sheathing (OSB or '
                  'plywood, listed in the BOM) braces them.'),
    'leg_length': ('Длина ноги (Leg length)',
                   'Только для «Арки на ногах». Длина длинной стороны ноги — от пятки до узла купола. '
                   '0 — авто: 1,3 ребра шапки, как на фото, узлы остаются маленькими. Длиннее — арки выше, '
                   'но длинные ноги делают узлы больше (плагин предупредит). Пятки стоят в платформах.',
                   'Arches on legs only. Length of a leg\'s long side, from the foot to the dome hub. '
                   '0 means auto: 1.3 x the cap edge, as on the photo, the hubs stay small. Longer legs make '
                   'taller arches but bigger hubs (you get a warning). The feet stand in platforms.'),
    'frame_depth': ('Глубина каркаса (Frame depth)',
                    'Расстояние между наружной и внутренней пластинами узла по радиусу — высота рёбер. '
                    'Для дома бери толщину утеплителя.',
                    'Radial distance between the outer and inner hub plates, i.e. the strut depth. '
                    'For a house use the insulation thickness.'),
    'boards_per_strut': ('Досок в ребре (Boards per strut)',
                         '1 — ребро из одной доски. 2 — сдвоенное ребро: две доски с зазором, '
                         'между ними проставки.',
                         '1: a single-board strut. 2: a twin strut, two boards with a gap and '
                         'spacers between them.'),
    'plywood': ('Толщина фанеры (Plywood)',
                'Фанера досок и проставок. Вводи фактическую толщину, замеренную штангенциркулем: '
                'от неё считаются пазы.',
                'Plywood for boards and spacers. Enter the real thickness measured with calipers: '
                'the slots are sized from it.'),
    'board_gap': ('Зазор между досками (Board gap)',
                  'Расстояние между двумя досками сдвоенного ребра. Его держат проставки, в доме сюда '
                  'идёт утеплитель.',
                  'Distance between the two boards of a twin strut. The spacers hold it; in a house '
                  'it is filled with insulation.'),
    'spacer_max': ('Шаг проставок (Spacer spacing)',
                   'Наибольшее расстояние между проставками вдоль ребра. Они ставятся равномерно и '
                   'не реже этого шага, минимум одна на ребро.',
                   'Largest distance between spacers along a strut. They are spread evenly, never '
                   'further apart than this, at least one per strut.'),
    'spacer_inset': ('Отступ проставки (Spacer inset)',
                     'Насколько проставка отступает от наружной и внутренней кромок доски.',
                     'How far the spacer stays in from the outer and inner edges of the board.'),
    'plate': ('Толщина пластины (Plate thickness)',
              'Фанера пластин узла. Шипы досок выходят ровно заподлицо с наружной гранью пластины.',
              'Plywood of the hub plates. The board tenons come out exactly flush with the plate face.'),
    'tenon_len': ('Длина шипа (Tenon length)',
                  'Длина шипа вдоль ребра — насколько далеко доска заходит под пластину.',
                  'Tenon length along the strut: how far the board reaches under the plate.'),
    'min_web': ('Перемычка (Min web)',
                'Наименьший остаток фанеры между соседними пазами. От неё зависит, как далеко от '
                'центра начинаются доски, то есть радиус узла.',
                'Least plywood left between neighbouring slots. It sets how far from the centre '
                'the boards start, i.e. the hub radius.'),
    'plate_margin': ('Поле пластины (Plate margin)',
                     'Сколько фанеры остаётся от пазов до края пластины.',
                     'How much plywood is left between the slots and the plate edge.'),
    'plate_shape': ('Форма пластины (Plate shape)',
                    'Многоугольник — контур по пазам со скруглёнными углами, меньше фанеры. '
                    'Круг — круглая пластина.',
                    'Hull: an outline around the slots with rounded corners, less plywood. '
                    'Circle: a round plate.'),
    'corner_radius': ('Скругление (Corner radius)',
                      'Радиус скругления углов пластины-многоугольника.',
                      'Corner radius of the Hull-shaped plates.'),
    'center_hole': ('Отверстие (Center hole)',
                    'Отверстие в центре пластины под болт. 12 мм — под M12, болт забивается плотно. '
                    '0 — без отверстия.',
                    'Hole in the plate centre for the bolt. 12 mm suits an M12 hammered in tight. '
                    '0 means no hole.'),
    'clearance': ('Зазор (Clearance)',
                  'Зазор на сторону во всех соединениях шип-паз: паз больше шипа на эту величину '
                  'с каждой стороны.',
                  'Clearance per side in every tenon-slot joint: each slot is this much larger than '
                  'its tenon on every side.'),
    'dogbone': ('Диаметр dogbone (Dogbone diameter)',
                'Подрезки в углах пазов и у корней шипов, чтобы круглая фреза дала посадку как в '
                'острый угол. Фреза 8 мм + 0,2 = 8,2.',
                'Relief cuts in slot corners and at tenon roots so a round cutter still gives a '
                'sharp-corner fit. 8 mm cutter + 0.2 = 8.2.'),
    'sheet_len': ('Длина листа (Sheet length)',
                  'Длина листа фанеры, мм: по ней раскладка и проверка, что каждая доска помещается вдоль '
                  'волокон. 2500 × 1250 — стандарт в Европе; ставь свой лист или стол лазера.',
                  'Plywood sheet length, mm: the layout and the check that every board fits along the grain '
                  'use it. 2500 x 1250 is the European standard; set your own sheet or laser bed.'),
    'sheet_wid': ('Ширина листа (Sheet width)',
                  'Ширина листа фанеры, мм.',
                  'Plywood sheet width, mm.'),
    'labels': ('Маркировка (Labels)',
               'Гравировать на деталях тип доски, код узла и буквы у пазов — вырез 0,5 мм под '
               'V-фрезу.',
               'Engrave the board type, the hub code and the letters next to the slots: a 0.5 mm '
               'cut for a V-bit.'),
    'label_height': ('Высота букв (Label height)',
                     'Высота букв маркировки.',
                     'Height of the label letters.'),
    'lang': ('Язык / Language',
             'Язык окна, подсказок и сообщений. Выбор запоминается.',
             'Language of the dialog, the tooltips and the messages. Remembered.'),
    'layout': ('Разложить на листы (Sheet layout)',
               'После сборки раскладывает плоские детали купола (доски, пластины, проставки) телами на листы '
               'рядом с куполом: ряды вдоль длинной стороны, поворот только 0° или 90°, доски вдоль волокон. '
               'Размер листа, отступ и расстояние — в группе ЧПУ; у модели — стол принтера в группе Модель. '
               'Чужие тела проекта не берёт.',
               'After building, lays the flat dome parts (boards, plates, spacers) out on sheets beside the '
               'dome as bodies: rows along the long side, turned 0 or 90 degrees only, boards along the grain. '
               'Sheet size, margin and spacing are in the CNC group; a model uses the print bed in the Model '
               'group. No other bodies of the project are taken.'),
    'export_dxf': ('Экспорт DXF (Export DXF)',
                   'Сохраняет раскладку: один DXF на лист, мм. Слои CUT — контуры, HOLES — отверстия и пазы, '
                   'TEXT — тип детали, SHEET — граница листа.',
                   'Saves the layout as one DXF per sheet, mm. Layers: CUT outlines, HOLES holes and slots, '
                   'TEXT the part type, SHEET the sheet edge.'),
    'sheet_margin': ('Отступ от края (Edge margin)',
                     'Свободная полоса по краю листа: детали не ближе к краю. Та же величина в проверке, '
                     'помещаются ли детали.',
                     'Free strip along the sheet edge; no part comes closer. The fit check uses it too.'),
    'part_gap': ('Между деталями (Part spacing)',
                 'Расстояние между деталями на листе. Не меньше диаметра фрезы: 8 мм + запас 2 мм = 10.',
                 'Distance between the parts on a sheet. At least the cutter diameter: 8 mm + 2 mm = 10.'),
    'bed_margin': ('Отступ от края стола (Bed margin)',
                   'Свободная полоса по краю стола принтера или лазера для модели.',
                   'Free strip along the edge of the print (or laser) bed for a model.'),
    'bed_gap': ('Между деталями на столе (Bed spacing)',
                'Расстояние между деталями модели на столе.',
                'Distance between the model parts on the bed.'),
    'bed_by_type': ('Столы по типам (One type per bed)',
                    'На каждом столе детали только одного типа: снял стол — сразу в пакет, и ничего не надо '
                    'искать. Что на каком столе — в результатах и в именах STL-файлов. Столов больше, а время '
                    'печати почти то же: пластика столько же.',
                    'Each bed holds one part type only: take a bed off, bag it and nothing needs sorting. '
                    'What is on each bed is in the results and in the STL file names. More beds, about the '
                    'same print time: the same amount of plastic.'),
    'disclaimer': ('Важно (Important)', '', ''),
    'disclaimer_ok': ('Понятно / I understand',
                      'Подтверди, что прочитал текст выше. Без этого кнопка построения не активна; '
                      'спросим один раз.',
                      'Confirm you have read the text above. The Build button stays off until then; '
                      'asked once.'),
    'support': ('Поддержать (Support)',
                'Плагин бесплатный. Понравился и пригодился — поддержи автора на Ko-fi.',
                'The add-in is free. If you like it and use it, support the author on Ko-fi.'),
    'share': ('Прислать фото (Share your dome)',
              'Построил купол или напечатал модель? Присылай фото в Instagram @sashavmire и отмечай #RocketGeodome '
              '— открывает Instagram.',
              'Built a dome or printed the model? Send your photos to Instagram @sashavmire and tag #RocketGeodome. '
              'Opens Instagram.'),
    'telegram': ('Телеграм (Telegram)',
                 'Канал автора: кемперы, Fusion 360 и плагины — t.me/fusion2van.',
                 'The author\'s channel: campers, Fusion 360 and add-ins - t.me/fusion2van.'),
    'about': ('О плагине (About)',
              'Версия, автор, отказ от ответственности и лицензия.',
              'Version, author, disclaimer and license.'),
    'results': ('Результаты (Results)',
                'Пересчитываются при каждом изменении: размеры, количества, типы деталей, вес и '
                'предупреждения.',
                'Recalculated on every change: sizes, counts, part types, weight and warnings.'),
}
GROUP_NAMES = {'Presets': 'Пресеты (Presets)', 'Build': 'Сборка (Build)', 'Shape': 'Форма (Shape)',
               'Model': 'Модель для печати (Model)',
               'Struts': 'Рёбра (Struts)', 'Hubs': 'Узлы (Hubs)', 'CNC': 'ЧПУ и листы (CNC and sheets)',
               'Results': 'Результаты (Results)', 'Disclaimer': 'Важно (Important)'}
CHOICE_TEXT = {'plate_shape': {'Hull': 'Многоугольник (Hull)', 'Circle': 'Круг (Circle)'},
               'base_shape': {'Hemisphere': 'Полусфера (Hemisphere)', 'Walls': 'На стенах (On walls)',
                              'Arches': 'Арки на ногах (Arches on legs)'}}
INT_RANGES = {'model_scale': (1, 100), 'wall_rows': (1, core.MAX_WALL_ROWS)}

# (group, field in core.Params, kind, choices)
INPUTS = [
    ('Shape', 'diameter', 'mm', None),
    ('Shape', 'frequency', 'choice', ['2V', '4V', '6V']),
    ('Shape', 'base_shape', 'choice', list(core.BASE_SHAPES)),
    ('Shape', 'wall_height', 'mm', None),
    ('Shape', 'wall_rows', 'int', None),
    ('Shape', 'leg_length', 'mm', None),
    ('Model', 'model_scale', 'int', None),
    ('Model', 'print_plywood', 'mm', None),
    ('Model', 'print_plate', 'mm', None),
    ('Model', 'print_clearance', 'mm', None),
    ('Model', 'print_hole', 'mm', None),
    ('Model', 'print_labels', 'bool', None),
    ('Model', 'print_label_height', 'mm', None),
    ('Model', 'print_label_depth', 'mm', None),
    ('Model', 'bed_len', 'mm', None),
    ('Model', 'bed_wid', 'mm', None),
    ('Model', 'bed_margin', 'mm', None),
    ('Model', 'bed_gap', 'mm', None),
    ('Model', 'bed_by_type', 'bool', None),
    ('Struts', 'frame_depth', 'mm', None),
    ('Struts', 'boards_per_strut', 'choice', ['1', '2']),
    ('Struts', 'plywood', 'mm', None),
    ('Struts', 'board_gap', 'mm', None),
    ('Struts', 'spacer_max', 'mm', None),
    ('Struts', 'spacer_inset', 'mm', None),
    ('Hubs', 'plate', 'mm', None),
    ('Hubs', 'tenon_len', 'mm', None),
    ('Hubs', 'min_web', 'mm', None),
    ('Hubs', 'plate_margin', 'mm', None),
    ('Hubs', 'plate_shape', 'choice', ['Hull', 'Circle']),
    ('Hubs', 'corner_radius', 'mm', None),
    ('Hubs', 'center_hole', 'mm', None),
    ('CNC', 'clearance', 'mm', None),
    ('CNC', 'dogbone', 'mm', None),
    ('CNC', 'sheet_len', 'mm', None),
    ('CNC', 'sheet_wid', 'mm', None),
    ('CNC', 'sheet_margin', 'mm', None),
    ('CNC', 'part_gap', 'mm', None),
    ('CNC', 'labels', 'bool', None),
    ('CNC', 'label_height', 'mm', None),
]
EXPANDED = ('Presets', 'Shape', 'Struts', 'Results')
BUILD_MODES = ('Full dome', 'Skeleton', 'Test hub')
BUILD_TEXT = {'Full dome': 'Полный купол (Full dome)', 'Skeleton': 'Скелет (Skeleton)',
              'Test hub': 'Пробный узел (Test hub)'}
NEST_GROUP = 'RocketNesting'   # attributes read by Rocket Nesting: qty, grain
PALETTE = [(230, 25, 75), (60, 180, 75), (0, 130, 200), (245, 130, 48), (145, 30, 180),
           (70, 190, 190), (240, 50, 230), (128, 128, 0), (0, 0, 128), (170, 110, 40)]

_app = None
_ui = None
_handlers = []
_graphics = None
_cache = {'key': None, 'dome': None}
_edit_occurrence = None
_y_up = False
_accepted_flag = [False]   # the disclaimer of this version is accepted
RELAUNCH_EVENT = 'RocketGeodome_Relaunch'
_relaunch = {'state': None, 'ready': False}   # carried dialog state; ready: the event is registered


# ------------------------------------------------------------------ helpers
def _error():
    if _ui:
        _ui.messageBox(M('failed', CMD_NAME, traceback.format_exc()))


def _up_is_y():
    try:
        pref = _app.preferences.generalPreferences.defaultModelingOrientation
        return pref == adsk.core.DefaultModelingOrientations.YUpModelingOrientation
    except Exception:
        return False


def _coords(p_mm):
    """Dome coordinates (mm, Z up) -> model coordinates (cm, honours Y-up)."""
    x, y, z = p_mm[0] / 10.0, p_mm[1] / 10.0, p_mm[2] / 10.0
    return [x, z, -y] if _y_up else [x, y, z]


def _point(p_mm):
    return adsk.core.Point3D.create(*_coords(p_mm))


# ----------------------------------------------------------------- language
_lang = 'en'

MSG = {   # key: (Russian, English)
    'failed': ('{}: ошибка\n{}', '{}: failed\n{}'),
    'preset_name': ('Сначала введи имя пресета.', 'Type a name for the preset first.'),
    'no_design': ('Сначала открой дизайн.', 'Open a design first.'),
    'progress': ('Сборка деталей: %v / %m', 'Building parts: %v / %m'),
    'built': ('{} готов: {} деталей за {:.0f} с.', '{} built: {} parts in {:.0f} s.'),
    'skeleton': ('{}: скелет построен.', '{}: skeleton built.'),
    'test_hub': ('{}: пробный узел построен.', '{}: test hub built.'),
    'bom_title': ('Сохранить спецификацию', 'Save the BOM'),
    'bom_saved': ('Спецификация: {}', 'BOM: {}'),
    'folder_title': ('Папка для STL и DXF', 'Folder for STL and DXF'),
    'stl_saved': ('STL по типам деталей: {} файлов — {}', 'STL per part type: {} files - {}'),
    'bed_stl_saved': ('STL по столам принтера: {} файлов', 'STL per print bed: {} files'),
    'dxf_saved': ('DXF: {} листов — {}', 'DXF: {} sheets - {}'),
    'sheets_built': ('Детали разложены телами на листы рядом с куполом (компонент Sheets).',
                     'The parts lie on their sheets beside the dome as bodies (component Sheets).'),
    'layout_line': ('Раскладка: {} листов {:g} × {:g} мм{}', 'Layout: {} sheets {:g} x {:g} mm{}'),
    'layout_misfit': (', не помещается: {}', ', does not fit: {}'),
    'labels_failed': ('Детали построены, но маркировка не получилась:\n{}', 'Parts built, but the labels failed:\n{}'),
    'lang_later': ('Язык сменится, когда откроешь окно заново.', 'The language changes when you open the dialog again.'),
    'open_link': ('Не получилось открыть браузер. Ссылка:\n{}', 'Could not open the browser. The link:\n{}'),
    'build': ('Построить', 'Build'),
    'cancel': ('Отмена', 'Cancel'),
    'license_q': ('Бесплатно для личного и некоммерческого использования', 'Free for personal and non-commercial use'),
    'license_a': ('(лицензия PolyForm Noncommercial 1.0.0). Мастерским, строителям и фирмам, которые зарабатывают '
                  'с помощью плагина, нужна коммерческая лицензия — напиши мне в Instagram {} или в Telegram {}.',
                  '(PolyForm Noncommercial 1.0.0 license). CNC shops, builders and companies that earn money with '
                  'the plugin need a commercial license — message me on Instagram {} or Telegram {}.'),
    'license_file': ('Полный текст лицензии — LICENSE.txt в папке плагина.',
                     'Full license text: LICENSE.txt in the add-in folder.'),
    'support_q': ('Понравился плагин и пригодился?', 'Like the plugin and found it useful?'),
    'support_a': ('Поддержи меня на Ko-fi:', 'Support me on Ko-fi:'),
    'share_q': ('Построил купол или напечатал модель на 3D-принтере?', 'Built a dome or printed the 3D model?'),
    'share_a': ('Присылай фото мне в Instagram {} и отмечай #RocketGeodome',
                'Send your photos to my Instagram {} and tag #RocketGeodome'),
    'tag_line': ('Построил или напечатал — присылай фото в Instagram @sashavmire, отмечай #RocketGeodome',
                 'Built or printed it? Send your photos to Instagram @sashavmire, tag #RocketGeodome'),
}

GIFT = {   # (headline, the rest of the disclaimer)
    'ru': ('Rocket Geodome бесплатный — это мой подарок всем, кто строит купола для себя.',
           'Он предоставляется «как есть», без каких-либо гарантий. Я не отвечаю за прочность и безопасность '
           'построек: нагрузки (снег, ветер), материалы и местные строительные нормы ты проверяешь сам, при '
           'необходимости привлекаешь инженера-конструктора и строишь на свой риск.'),
    'en': ('Rocket Geodome is free: my gift to everyone who builds domes for themselves.',
           'It is provided "as is", without any warranty. I am not liable for the strength or safety of anything '
           'built with it: you check the loads (snow, wind), the materials and your local building codes '
           'yourself, bring in a structural engineer where needed and build at your own risk.'),
}
DISCLAIMER = {lang: head + ' ' + rest for lang, (head, rest) in GIFT.items()}


def _split(text):
    """'Диаметр (Diameter)' -> ('Диаметр', 'Diameter'); text without a (...) at the end stays as is."""
    m = re.match(r'^(.*\S)\s*\(([^()]*)\)$', text)
    return (m.group(1), m.group(2)) if m else (text, text)


def L(text):
    """The dialog language's half of a 'Русский (English)' text."""
    ru, en = _split(text)
    return ru if _lang == 'ru' else en


def M(key, *args):
    ru, en = MSG[key]
    s = ru if _lang == 'ru' else en
    return s.format(*args) if args else s


def _choice_text(field, value):
    if field == 'frequency':
        return '{}V'.format(int(value))
    shown = CHOICE_TEXT.get(field, {}).get(str(value))
    return L(shown) if shown else str(value)


def _choice_value(field, text):
    if field == 'frequency':
        return int(text.rstrip('V'))
    if field == 'boards_per_strut':
        return int(text)
    for value, shown in CHOICE_TEXT.get(field, {}).items():
        if text in _split(shown) or text == shown:
            return value
    return text


def _tip(inp, field):
    """Tooltip title and description in the dialog language."""
    label, ru, en = TEXT[field]
    try:
        inp.tooltip = L(label)
        desc = ru if _lang == 'ru' else en
        if desc:
            inp.tooltipDescription = desc
    except Exception:
        pass
    return inp


def _label(field):
    return L(TEXT[field][0])


def _settings():
    s = _load_presets().get('_settings')
    return s if isinstance(s, dict) else {}


def _save_setting(key, value):
    data = _load_presets()
    s = data.get('_settings') if isinstance(data.get('_settings'), dict) else {}
    s[key] = value
    data['_settings'] = s
    _save_presets(data)


def _load_lang():
    lang = _settings().get('lang', 'en')
    return lang if lang in dict(LANGS) else 'en'


def _accepted():
    return _settings().get('disclaimer') == DISCLAIMER_VERSION


def _open_url(url):
    try:
        if webbrowser.open(url):
            return
    except Exception:
        pass
    _ui.messageBox(M('open_link', url), CMD_NAME)


def _about_text():
    lang = 'ru' if _lang == 'ru' else 'en'
    lines = ['Rocket Geodome {}'.format(VERSION_TEXT),
             ('Каркасы геокуполов из фанеры под ЧПУ для Fusion.' if lang == 'ru' else
              'Geodesic dome frames from CNC plywood for Fusion.'),
             '© 2026 Alexander · Instagram @sashavmire · t.me/fusion2van', '',
             DISCLAIMER[lang], '',
             M('license_q') + ' ' + M('license_a').format('@sashavmire', 't.me/fusion2van') + ' ' + M('license_file'),
             '', M('support_q') + ' ' + M('support_a') + ' ' + KOFI_URL, '',
             M('share_q') + ' ' + M('share_a').format('@sashavmire')]
    return '\n'.join(lines)


def _top_html():
    """The block on top of the dialog: gift and disclaimer, license, Ko-fi, photos - links clickable."""
    head, rest = GIFT['ru' if _lang == 'ru' else 'en']
    kofi = '<a href="{}">{}</a>'.format(KOFI_URL, KOFI_URL.split('//', 1)[-1])
    insta = '<a href="{}">@sashavmire</a>'.format(INSTAGRAM_URL)
    tg = '<a href="{}">{}</a>'.format(TELEGRAM_URL, TELEGRAM_URL.split('//', 1)[-1])
    return ('<b>{}</b> {}<br/><br/><b>{}</b> {}<br/><br/><b>{}</b> {} {}<br/><br/><b>{}</b> {}'.format(
        head, rest, M('license_q'), M('license_a').format(insta, tg),
        M('support_q'), M('support_a'), kofi, M('share_q'), M('share_a').format(insta)))


def _default_presets():
    try:
        with open(PRESETS_DEFAULT_PATH, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
        return dict(loaded.get('presets', {})) if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _load_presets():
    """presets.default.json ships with the add-in, presets.json holds the user's
    own; the user's presets win, and updates never overwrite them. Copies of the
    shipped presets that older versions wrote into presets.json (no sheet margin
    yet) give way to the new defaults."""
    defaults = _default_presets()
    data = {'presets': dict(defaults)}
    try:
        with open(PRESETS_PATH, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
    except Exception:
        loaded = None
    if isinstance(loaded, dict):
        user = loaded.get('presets') if isinstance(loaded.get('presets'), dict) else {}
        for name, values in user.items():
            if name in defaults and isinstance(values, dict) and 'sheet_margin' not in values:
                continue
            data['presets'][name] = values
        for key, value in loaded.items():
            if key != 'presets':
                data[key] = value
    return data


def _save_presets(data):
    """Writes the user's presets (shipped ones only when changed), the last
    parameters and the settings."""
    defaults = _default_presets()
    out = dict(data)
    out['presets'] = {k: v for k, v in data.get('presets', {}).items() if defaults.get(k) != v}
    with open(PRESETS_PATH, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)


def _remember_last(p):
    data = _load_presets()
    data['_last'] = p.to_dict()
    _save_presets(data)


def _analyze(p):
    key = json.dumps(p.to_dict(), sort_keys=True)
    if _cache['key'] != key:
        _cache['key'] = key
        _cache['dome'] = core.analyze(p)
    return _cache['dome']


# ------------------------------------------------------------------- dialog
def _initial_params():
    """A selected Rocket Geodome dome -> edit its parameters, else the last used."""
    try:
        sel = _ui.activeSelections
        if sel.count == 1:
            occ = adsk.fusion.Occurrence.cast(sel.item(0).entity)
            if occ:
                attr = occ.component.attributes.itemByName(ATTR_GROUP, 'params')
                if attr:
                    return core.Params.from_dict(json.loads(attr.value)), occ
    except Exception:
        pass
    last = _load_presets().get('_last')
    return (core.Params.from_dict(last) if isinstance(last, dict) else core.Params()), None


def _no_preset():
    return NO_PRESET[0] if _lang == 'ru' else NO_PRESET[1]


def _build_inputs(inputs, p, state=None):
    """Every input under the language box, in the dialog language. `state` keeps the
    build choices and the preset when the dialog is rebuilt for another language."""
    state = state or {}
    style = adsk.core.DropDownStyles.TextListDropDownStyle
    grp = inputs.addGroupCommandInput('grp_disclaimer', L(GROUP_NAMES['Disclaimer']))
    grp.isExpanded = True
    rows = 16 if _lang == 'ru' else 14      # the whole block visible without scrolling
    tb = grp.children.addTextBoxCommandInput('disclaimer_text', ' ', _top_html(), rows, True)
    try:
        tb.isFullWidth = True
    except Exception:
        pass
    for key, text in (('support', 'Ko-fi'), ('share', 'Instagram')):
        btn = _tip(grp.children.addBoolValueInput(key, _label(key), False, '', False), key)
        try:
            btn.text = text
        except Exception:
            pass
    if not _accepted_flag[0]:      # first run: Build stays off until "I understand"
        _tip(grp.children.addBoolValueInput('disclaimer_ok', _label('disclaimer_ok'), True, '', False), 'disclaimer_ok')

    grp = inputs.addGroupCommandInput('grp_presets', L(GROUP_NAMES['Presets']))
    grp.isExpanded = True
    dd = _tip(grp.children.addDropDownCommandInput('preset', _label('preset'), style), 'preset')
    chosen = state.get('preset')
    names = sorted(_load_presets().get('presets', {}))
    dd.listItems.add(_no_preset(), chosen not in names, '')
    for name in names:
        dd.listItems.add(name, name == chosen, '')
    _tip(grp.children.addStringValueInput('preset_name', _label('preset_name'), state.get('preset_name', '')),
         'preset_name')
    _tip(grp.children.addBoolValueInput('preset_save', _label('preset_save'), False, '', False), 'preset_save')

    grp = inputs.addGroupCommandInput('grp_build', L(GROUP_NAMES['Build']))
    grp.isExpanded = True
    dd = _tip(grp.children.addDropDownCommandInput('build_mode', _label('build_mode'), style), 'build_mode')
    mode = state.get('build_mode', BUILD_MODES[0])
    for m in BUILD_MODES:
        dd.listItems.add(L(BUILD_TEXT[m]), m == mode, '')
    for key in ('bom_csv', 'export_stl', 'layout', 'export_dxf'):
        _tip(grp.children.addBoolValueInput(key, _label(key), True, '', bool(state.get(key, True))), key)

    groups = {}
    for group, field, kind, choices in INPUTS:
        if group not in groups:
            g = inputs.addGroupCommandInput('grp_' + group.lower(), L(GROUP_NAMES[group]))
            g.isExpanded = (group in EXPANDED or (group == 'Model' and p.is_model) or
                            (group == 'CNC' and not p.is_model))
            groups[group] = g.children
        children = groups[group]
        value = getattr(p, field)
        label = _label(field)
        if kind == 'mm':
            inp = children.addValueInput(field, label, 'mm', adsk.core.ValueInput.createByReal(value / 10.0))
        elif kind == 'choice':
            inp = children.addDropDownCommandInput(field, label, style)
            current = _choice_text(field, value)
            for c in choices:
                shown = _choice_text(field, c if field != 'frequency' else int(c.rstrip('V')))
                inp.listItems.add(shown, shown == current, '')
        elif kind == 'int':
            lo, hi = INT_RANGES.get(field, (1, 100))
            inp = children.addIntegerSpinnerCommandInput(field, label, lo, hi, 1, int(round(value)))
        else:
            inp = children.addBoolValueInput(field, label, True, '', bool(value))
        _tip(inp, field)

    grp = inputs.addGroupCommandInput('grp_results', L(GROUP_NAMES['Results']))
    grp.isExpanded = True
    tb = _tip(grp.children.addTextBoxCommandInput('results', _label('results'), '', 16, True), 'results')
    try:
        tb.isFullWidth = True
    except Exception:
        pass

    grp = inputs.addGroupCommandInput('grp_about', CMD_NAME)
    grp.isExpanded = True
    for key, text in (('telegram', 'Telegram'), ('about', 'Инфо' if _lang == 'ru' else 'Info')):
        btn = _tip(grp.children.addBoolValueInput(key, _label(key), False, '', False), key)
        try:
            btn.text = text
        except Exception:
            pass


def _read_state(inputs):
    """Build mode, check boxes and preset of the open dialog."""
    st = {'build_mode': BUILD_MODES[0]}
    dd = adsk.core.DropDownCommandInput.cast(inputs.itemById('build_mode'))
    item = dd.selectedItem if dd else None
    if item:
        st['build_mode'] = next((m for m in BUILD_MODES if item.name in _split(BUILD_TEXT[m])), BUILD_MODES[0])
    for key in ('bom_csv', 'export_stl', 'layout', 'export_dxf', 'disclaimer_ok'):
        inp = adsk.core.BoolValueCommandInput.cast(inputs.itemById(key))
        if inp:
            st[key] = bool(inp.value)
    dd = adsk.core.DropDownCommandInput.cast(inputs.itemById('preset'))
    item = dd.selectedItem if dd else None
    if item and item.name not in NO_PRESET:
        st['preset'] = item.name
    name = adsk.core.StringValueCommandInput.cast(inputs.itemById('preset_name'))
    if name:
        st['preset_name'] = name.value
    return st


def _switch_language(inputs, lang):
    """Fusion cannot rename inputs and does not delete group inputs, so the dialog
    closes and opens again in the other language with the same values (and the
    same dome being edited); without the relaunch event it applies next time."""
    global _lang
    _relaunch['state'] = (_read_params(inputs), _read_state(inputs), _edit_occurrence)
    _lang = lang
    _save_setting('lang', lang)
    if _relaunch['ready']:
        try:   # Fusion queues the event even when this call returns False
            _app.fireCustomEvent(RELAUNCH_EVENT, lang)
            return
        except Exception:
            pass
    _relaunch['state'] = None
    _ui.messageBox(M('lang_later'), CMD_NAME)


def _read_params(inputs):
    p = core.Params()
    for group, field, kind, choices in INPUTS:
        inp = inputs.itemById(field)
        if inp is None:
            continue
        if kind == 'mm':
            setattr(p, field, round(adsk.core.ValueCommandInput.cast(inp).value * 10.0, 6))
        elif kind == 'choice':
            item = adsk.core.DropDownCommandInput.cast(inp).selectedItem
            if item:
                setattr(p, field, _choice_value(field, item.name))
        elif kind == 'int':   # model_scale stays a float, wall_rows an int
            setattr(p, field, type(getattr(p, field))(adsk.core.IntegerSpinnerCommandInput.cast(inp).value))
        elif kind == 'bool':
            setattr(p, field, adsk.core.BoolValueCommandInput.cast(inp).value)
    return p


def _apply_params(inputs, p):
    for group, field, kind, choices in INPUTS:
        inp = inputs.itemById(field)
        if inp is None:
            continue
        value = getattr(p, field)
        if kind == 'mm':
            adsk.core.ValueCommandInput.cast(inp).value = value / 10.0
        elif kind == 'choice':
            dd = adsk.core.DropDownCommandInput.cast(inp)
            current = _choice_text(field, value)
            for i in range(dd.listItems.count):
                if dd.listItems.item(i).name == current:
                    dd.listItems.item(i).isSelected = True
        elif kind == 'int':
            adsk.core.IntegerSpinnerCommandInput.cast(inp).value = int(round(value))
        elif kind == 'bool':
            adsk.core.BoolValueCommandInput.cast(inp).value = bool(value)


_layout_cache = {'key': None, 'lay': None}


def _layout_for(dome, mode):
    """Sheet layout of this dome's flat parts (the test hub's in that mode), cached."""
    kind = 'Test hub' if mode == 'Test hub' else 'Full dome'
    key = (json.dumps(dome.src.to_dict(), sort_keys=True), kind)
    if _layout_cache['key'] != key:
        dp = dome.p
        by_type = bool(dome.model and dp.bed_by_type and kind == 'Full dome')
        _layout_cache['lay'] = layout.pack(layout.flat_parts(dome, kind), dp.sheet_len, dp.sheet_wid,
                                           dp.sheet_margin, dp.part_gap, by_type)
        _layout_cache['key'] = key
    return _layout_cache['lay']


def _layout_line(lay):
    misfit = ''
    if lay.misfit:
        misfit = M('layout_misfit', ', '.join('{} x{}'.format(k, q) for k, q in lay.misfit.items()))
    return M('layout_line', len(lay.sheets), lay.L, lay.W, misfit)


def _update_results(inputs):
    p = _read_params(inputs)
    dome = _analyze(p)
    st = _read_state(inputs)
    tb = adsk.core.TextBoxCommandInput.cast(inputs.itemById('results'))
    if tb:
        html = core.summary_html(dome, _lang)
        if not dome.errors and (st.get('layout') or st.get('export_dxf')):
            try:
                html += '<br/>' + _layout_line(_layout_for(dome, st['build_mode']))
            except Exception:
                pass
        tb.formattedText = html
    model, twin = p.is_model, p.boards_per_strut == 2
    enabled = {'board_gap': twin, 'spacer_max': twin, 'spacer_inset': twin,
               'corner_radius': p.plate_shape == 'Hull', 'export_stl': model,
               'label_height': p.labels and not model, 'print_label_height': p.print_labels and model,
               'print_label_depth': p.print_labels and model,
               'wall_height': p.base_shape == 'Walls', 'wall_rows': p.base_shape == 'Walls',
               'leg_length': p.base_shape == 'Arches'}
    for field in ('plywood', 'plate', 'clearance', 'dogbone', 'center_hole', 'sheet_len', 'sheet_wid', 'labels',
                  'sheet_margin', 'part_gap'):
        enabled[field] = not model      # a model takes these from the print values
    for field in ('print_plywood', 'print_plate', 'print_clearance', 'print_hole', 'print_labels',
                  'bed_len', 'bed_wid', 'bed_margin', 'bed_gap', 'bed_by_type'):
        enabled[field] = model
    for field, on in enabled.items():
        inp = inputs.itemById(field)
        if inp:
            inp.isEnabled = on


def _load_preset(inputs):
    item = adsk.core.DropDownCommandInput.cast(inputs.itemById('preset')).selectedItem
    if not item or item.name in NO_PRESET:
        return
    data = _load_presets().get('presets', {}).get(item.name)
    if isinstance(data, dict):
        _apply_params(inputs, core.Params.from_dict(data))
        adsk.core.StringValueCommandInput.cast(inputs.itemById('preset_name')).value = item.name


def _save_preset(inputs):
    name = adsk.core.StringValueCommandInput.cast(inputs.itemById('preset_name')).value.strip()
    if not name:
        _ui.messageBox(M('preset_name'), CMD_NAME)
        return
    data = _load_presets()
    data.setdefault('presets', {})[name] = _read_params(inputs).to_dict()
    _save_presets(data)
    dd = adsk.core.DropDownCommandInput.cast(inputs.itemById('preset'))
    item = None
    for i in range(dd.listItems.count):
        if dd.listItems.item(i).name == name:
            item = dd.listItems.item(i)
    if item is None:
        item = dd.listItems.add(name, False, '')
    item.isSelected = True


# ------------------------------------------------------------------ preview
def _clear_graphics():
    global _graphics
    try:
        if _graphics is not None and _graphics.isValid:
            _graphics.deleteMe()
    except Exception:
        pass
    _graphics = None
    try:
        _app.activeViewport.refresh()
    except Exception:
        pass


def _draw_preview(dome):
    global _graphics
    _clear_graphics()
    design = adsk.fusion.Design.cast(_app.activeProduct)
    if not design:
        return
    _graphics = design.rootComponent.customGraphicsGroups.add()
    by_type = {}
    for a, b, t in dome.segments():
        by_type.setdefault(t, []).extend(_coords(a) + _coords(b))
    for t, coords in by_type.items():
        lines = _graphics.addLines(adsk.fusion.CustomGraphicsCoordinates.create(coords), [], False)
        r, g, b = PALETTE[t % len(PALETTE)]
        lines.color = adsk.fusion.CustomGraphicsSolidColorEffect.create(adsk.core.Color.create(r, g, b, 255))
        lines.weight = 2.0
    # floor outline: base nodes (the floor ring, or the five feet) dropped to the floor level
    base = dome.floor_outline()
    ring = []
    for q in base + base[:1]:
        ring += _coords(q)
    if len(base) > 1:
        floor = _graphics.addLines(adsk.fusion.CustomGraphicsCoordinates.create(ring), [], True)
        floor.color = adsk.fusion.CustomGraphicsSolidColorEffect.create(adsk.core.Color.create(140, 140, 140, 255))
        floor.weight = 1.0
    _app.activeViewport.refresh()


# -------------------------------------------------------------------- build
def _build_skeleton(design, dome):
    root = design.rootComponent
    occ = _fixed(root.occurrences.addNewComponent(adsk.core.Matrix3D.create()))
    comp = occ.component
    comp.name = dome.name
    sketch = comp.sketches.add(comp.xYConstructionPlane)
    sketch.name = 'Skeleton'
    sketch.isComputeDeferred = True
    pts = [sketch.sketchPoints.add(_point(q)) for q in dome.pos]
    lines = sketch.sketchCurves.sketchLines
    for a, b, t in dome.struts:
        lines.addByTwoPoints(pts[a], pts[b])
    sketch.isComputeDeferred = False
    comp.attributes.add(ATTR_GROUP, 'params', json.dumps(dome.src.to_dict()))
    comp.attributes.add(ATTR_GROUP, 'version', core.VERSION)
    return occ


def _free(occ):
    """Fusion grounds the first component made inside another one to its parent
    ("Ground to Parent"); every part has to move on its own."""
    try:
        if occ.isGroundToParent:
            occ.isGroundToParent = False
    except Exception:
        pass
    return occ


def _fixed(occ):
    """The dome and its groups (Boards, Plates...) stay grounded to their parent,
    so the dome as a whole does not drift; the parts inside still move freely."""
    try:
        if not occ.isGroundToParent:
            occ.isGroundToParent = True
    except Exception:
        pass
    return occ


def _vector(v):
    x, y, z = v
    return adsk.core.Vector3D.create(*([x, z, -y] if _y_up else [x, y, z]))


def _unit(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / n, v[1] / n, v[2] / n)


def _axes(x, y, z=None):
    """Exactly orthonormal right-handed axes from two nearly perpendicular ones:
    Fusion rejects a transform or a box whose axes are off by even 1e-9."""
    x = _unit(x)
    d = x[0] * y[0] + x[1] * y[1] + x[2] * y[2]
    y = _unit((y[0] - d * x[0], y[1] - d * x[1], y[2] - d * x[2]))
    n = (x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0])
    if z is not None and n[0] * z[0] + n[1] * z[1] + n[2] * z[2] < 0.99:
        raise ValueError('frame is not right-handed')
    return x, y, n


def _matrix(frame):
    o, x, y, z = frame
    x, y, z = _axes(x, y, z)
    m = adsk.core.Matrix3D.create()
    m.setWithCoordinateSystem(_point(o), _vector(x), _vector(y), _vector(z))
    return m


def _p2(q):
    return adsk.core.Point3D.create(q[0] / 10.0, q[1] / 10.0, 0.0)


def _draw_loops(sketch, loops):
    curves = sketch.sketchCurves
    for loop in loops:
        for el in loop:
            if el[0] == 'L':
                curves.sketchLines.addByTwoPoints(_p2(el[1]), _p2(el[2]))
            elif el[0] == 'A':
                curves.sketchArcs.addByThreePoints(_p2(el[1]), _p2(el[2]), _p2(el[3]))
            elif el[0] == 'C':
                curves.sketchCircles.addByCenterRadius(_p2(el[1]), el[2] / 10.0)


_label_problems = []


def _engrave(comp, body, labels, thickness, height, depth=core.LABEL_DEPTH, bold=False):
    """Labels as text cut depth deep into the top (+z) face; bold (a model) in Arial Bold,
    so the strokes are wide enough for a 0.4 mm nozzle."""
    try:
        sketch = comp.sketches.add(comp.xYConstructionPlane)
        sketch.name = 'Labels'
        texts = sketch.sketchTexts
        items = []
        for lab in labels:
            text, x, y = lab[0], lab[1], lab[2]
            if not text:
                continue
            h = (lab[3] if len(lab) > 3 else height) / 10.0
            w = (len(text) + 1) * h
            ti = texts.createInput2(text, h)
            if bold:
                try:
                    ti.fontName = 'Arial'
                    ti.textStyle = adsk.fusion.TextStyles.TextStyleBold
                except Exception:
                    pass
            ti.setAsMultiLine(adsk.core.Point3D.create(x / 10.0 - w / 2.0, y / 10.0 - h, 0.0),
                              adsk.core.Point3D.create(x / 10.0 + w / 2.0, y / 10.0 + h, 0.0),
                              adsk.core.HorizontalAlignments.CenterHorizontalAlignment,
                              adsk.core.VerticalAlignments.MiddleVerticalAlignment, 0)
            items.append(texts.add(ti))
        extrudes = comp.features.extrudeFeatures
        for st in items:
            ei = extrudes.createInput(st, adsk.fusion.FeatureOperations.CutFeatureOperation)
            ei.startExtent = adsk.fusion.OffsetStartDefinition.create(
                adsk.core.ValueInput.createByReal(thickness / 10.0))
            ei.setOneSideExtent(adsk.fusion.DistanceExtentDefinition.create(
                adsk.core.ValueInput.createByReal(depth / 10.0)),
                adsk.fusion.ExtentDirections.NegativeExtentDirection)
            ei.participantBodies = [body]
            extrudes.add(ei)
    except Exception:
        _label_problems.append(traceback.format_exc())


def _make_part(parent, name, geo, frame, labels_on, label_height, qty=None):
    """New component with one body: the 2D loops extruded +z by the thickness,
    base plates cut at the floor, labels engraved, nesting attributes set."""
    occ = _free(parent.occurrences.addNewComponent(_matrix(frame)))
    comp = occ.component
    comp.name = name
    sketch = comp.sketches.add(comp.xYConstructionPlane)
    sketch.name = 'Profile'
    sketch.isComputeDeferred = True
    _draw_loops(sketch, geo['loops'])
    sketch.isComputeDeferred = False
    profiles = [sketch.profiles.item(i) for i in range(sketch.profiles.count)]
    if not profiles:
        raise RuntimeError('No closed profile for ' + name)
    prof = max(profiles, key=lambda pr: pr.areaProperties().area)
    extrudes = comp.features.extrudeFeatures
    ext_in = extrudes.createInput(prof, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    ext_in.setDistanceExtent(False, adsk.core.ValueInput.createByReal(geo['thickness'] / 10.0))
    body = extrudes.add(ext_in).bodies.item(0)
    body.name = name
    if geo.get('clip') is not None:
        cut_sketch = comp.sketches.add(comp.xYConstructionPlane)
        cut_sketch.name = 'Floor cut'
        clip, big = geo['clip'], 2000.0
        cut_sketch.sketchCurves.sketchLines.addTwoPointRectangle(_p2((clip, -big)), _p2((clip + big, big)))
        cut_in = extrudes.createInput(cut_sketch.profiles.item(0), adsk.fusion.FeatureOperations.CutFeatureOperation)
        cut_in.setDistanceExtent(False, adsk.core.ValueInput.createByReal(geo['thickness'] / 10.0))
        cut_in.participantBodies = [body]
        extrudes.add(cut_in)
    if labels_on and geo.get('labels'):
        _engrave(comp, body, geo['labels'], geo['thickness'], label_height,
                 geo.get('label_depth', core.LABEL_DEPTH), geo.get('label_bold', False))
    comp.attributes.add(NEST_GROUP, 'grain', geo.get('grain', 'any'))
    if qty is not None:
        comp.attributes.add(NEST_GROUP, 'qty', str(qty))
    return comp


def _csg_body(node):
    """Temporary B-Rep body of a core CSG node (boxes, pins and booleans), cm."""
    tbm = adsk.fusion.TemporaryBRepManager.get()
    kind = node[0]

    def pt(q):
        return adsk.core.Point3D.create(q[0] / 10.0, q[1] / 10.0, q[2] / 10.0)
    if kind == 'box':
        _k, c, u, v, size = node
        u, v, _n = _axes(u, v)
        obb = adsk.core.OrientedBoundingBox3D.create(pt(c), adsk.core.Vector3D.create(u[0], u[1], u[2]),
                                                     adsk.core.Vector3D.create(v[0], v[1], v[2]),
                                                     size[0] / 10.0, size[1] / 10.0, size[2] / 10.0)
        return tbm.createBox(obb)
    if kind == 'cyl':
        _k, a, b, r = node
        return tbm.createCylinderOrCone(pt(a), r / 10.0, pt(b), r / 10.0)
    ops = adsk.fusion.BooleanTypes
    if kind == 'union':
        body = _csg_body(node[1][0])
        for child in node[1][1:]:
            tbm.booleanOperation(body, _csg_body(child), ops.UnionBooleanType)
        return body
    if kind == 'inter':
        body = _csg_body(node[1])
        tbm.booleanOperation(body, _csg_body(node[2]), ops.IntersectionBooleanType)
        return body
    body = _csg_body(node[1])
    for child in node[2]:
        tbm.booleanOperation(body, _csg_body(child), ops.DifferenceBooleanType)
    return body


def _make_solid_part(parent, name, csg, frame, qty=None):
    """New component with one solid built from a core CSG tree in its own frame
    (the foot platform: base on its XY plane, so it exports lying on the bed)."""
    occ = _free(parent.occurrences.addNewComponent(_matrix(frame)))
    comp = occ.component
    comp.name = name
    body = _csg_body(csg)
    design = comp.parentDesign
    if design and design.designType == adsk.fusion.DesignTypes.ParametricDesignType:
        base = comp.features.baseFeatures.add()
        base.startEdit()
        comp.bRepBodies.add(body, base)
        base.finishEdit()
    else:
        comp.bRepBodies.add(body)
    if comp.bRepBodies.count:
        comp.bRepBodies.item(0).name = name
    comp.attributes.add(NEST_GROUP, 'grain', 'any')
    if qty is not None:
        comp.attributes.add(NEST_GROUP, 'qty', str(qty))
    return comp


def _build_dome(design, dome, progress):
    """Dome component: Boards, Plates, Spacers (and Tubes in a model) as one
    component per part type with an occurrence at every place, plus the floor
    sketch. Returns the occurrence, the part count and [(component, qty, label)]."""
    d, p = dome, dome.p
    lab, lh = p.labels, p.label_height
    identity = adsk.core.Matrix3D.create
    dome_occ = _fixed(design.rootComponent.occurrences.addNewComponent(identity()))
    comp = dome_occ.component
    comp.name = d.name
    comp.attributes.add(ATTR_GROUP, 'params', json.dumps(d.src.to_dict()))
    comp.attributes.add(ATTR_GROUP, 'version', core.VERSION)
    parts = []

    boards = _fixed(comp.occurrences.addNewComponent(identity())).component
    boards.name = 'Boards'
    geos = [core.board_geometry(d, ti) for ti in range(len(d.types))]
    made = {}
    for a, b, ti in d.struts:
        for off in p.board_offsets():
            m = _matrix(core.board_frame(d, a, b, ti, off))
            if ti in made:
                _free(boards.occurrences.addExistingComponent(made[ti], m))
            else:
                made[ti] = _make_part(boards, core.LETTERS[ti], geos[ti], core.board_frame(d, a, b, ti, off),
                                      lab, lh, d.types[ti].count * p.boards_per_strut)
                parts.append((made[ti], d.types[ti].count * p.boards_per_strut, 'Board ' + core.LETTERS[ti]))
            progress.tick()

    plates = _fixed(comp.occurrences.addNewComponent(identity())).component
    plates.name = 'Plates'
    placements, reps = core.plate_placements(d)
    qty = {}
    for name, _frame in placements:
        qty[name] = qty.get(name, 0) + 1
    made = {}
    for name, frame in placements:
        if name in made:
            _free(plates.occurrences.addExistingComponent(made[name], _matrix(frame)))
        else:
            n, inner = reps[name]
            made[name] = _make_part(plates, core.plate_display(d, name), core.plate_geometry(d, n, inner), frame,
                                    lab, lh, qty[name])
            parts.append((made[name], qty[name], 'Plate ' + name))
        progress.tick()

    if p.boards_per_strut == 2 and d.n_spacers:
        spacers = _fixed(comp.occurrences.addNewComponent(identity())).component
        spacers.name = 'Spacers'
        spacer = None
        for a, b, ti in d.struts:
            for x in geos[ti]['spacers_x']:
                frame = core.spacer_frame(d, a, b, ti, x)
                if spacer is None:
                    spacer = _make_part(spacers, 'S', core.spacer_geometry(d), frame, False, lh, d.n_spacers)
                    parts.append((spacer, d.n_spacers, 'Spacer'))
                else:
                    _free(spacers.occurrences.addExistingComponent(spacer, _matrix(frame)))
                progress.tick()

    if d.has_tubes:
        tubes = _fixed(comp.occurrences.addNewComponent(identity())).component
        tubes.name = 'Tubes'
        tube = None
        for n in range(d.n_nodes):
            if d.socket[n]:
                continue
            frame = core.tube_frame(d, n)
            if tube is None:
                tube = _make_part(tubes, 'T', core.tube_geometry(d), frame, False, lh, d.n_hubs)
                parts.append((tube, d.n_hubs, 'Tube'))
            else:
                _free(tubes.occurrences.addExistingComponent(tube, _matrix(frame)))
            progress.tick()

    if d.platform:
        platforms = _fixed(comp.occurrences.addNewComponent(identity())).component
        platforms.name = 'Platforms'
        plat = None
        frames = core.platform_frames(d)
        for frame in frames:
            if plat is None:
                plat = _make_solid_part(platforms, 'Platform', d.platform['csg'], frame, len(frames))
                parts.append((plat, len(frames), 'Platform'))
            else:
                _free(platforms.occurrences.addExistingComponent(plat, _matrix(frame)))
            progress.tick()

    _floor_sketch(comp, d)
    return dome_occ, progress.count, parts


class _NoProgress:
    count = 0

    def tick(self):
        self.count += 1


class _Progress:
    """Progress dialog for long builds; keeps Fusion responsive with doEvents."""

    def __init__(self, total):
        self.count, self.dlg = 0, None
        try:
            self.dlg = _ui.createProgressDialog()
            self.dlg.isCancelButtonShown = False
            self.dlg.show(CMD_NAME, M('progress'), 0, max(int(total), 1), 0)
        except Exception:
            self.dlg = None

    def tick(self):
        self.count += 1
        if self.dlg is not None and self.count % 10 == 0:
            try:
                self.dlg.progressValue = self.count
                adsk.doEvents()
            except Exception:
                pass

    def close(self):
        if self.dlg is not None:
            try:
                self.dlg.hide()
            except Exception:
                pass


def _floor_sketch(comp, d):
    """Floor outline: polygons through the outer and inner base nodes at floor level
    (the floor ring of the hemisphere or the walls, the five feet of the arches)."""
    base_plane = comp.xZConstructionPlane if _y_up else comp.xYConstructionPlane
    normal = base_plane.geometry.normal
    up = normal.y if _y_up else normal.z
    planes = comp.constructionPlanes
    plane_in = planes.createInput()
    plane_in.setByOffset(base_plane, adsk.core.ValueInput.createByReal(d.z_floor / 10.0 * (1.0 if up > 0 else -1.0)))
    plane = planes.add(plane_in)
    plane.name = 'Floor'
    sketch = comp.sketches.add(plane)
    sketch.name = 'Floor'
    lines = sketch.sketchCurves.sketchLines
    for inner in (False, True):
        pts = [sketch.modelToSketchSpace(_point(q)) for q in d.floor_outline(inner)]
        for i in range(len(pts)):
            lines.addByTwoPoints(pts[i], pts[(i + 1) % len(pts)])


def _save_bom(dome):
    dlg = _ui.createFileDialog()
    dlg.isMultiSelectEnabled = False
    dlg.title = M('bom_title')
    dlg.filter = 'CSV files (*.csv)'
    dlg.initialFilename = dome.name + '.csv'
    if dlg.showSave() == adsk.core.DialogResults.DialogOK:
        with open(dlg.filename, 'w', encoding='utf-8-sig', newline='') as f:
            f.write(core.bom_csv(dome))
        return dlg.filename
    return None


def _ask_folder():
    dlg = _ui.createFolderDialog()
    dlg.title = M('folder_title')
    if dlg.showDialog() != adsk.core.DialogResults.DialogOK:
        return None
    return dlg.folder


def _stl(em, geometry, path):
    opts = em.createSTLExportOptions(geometry, path)
    opts.isBinaryFormat = True
    try:
        opts.unitType = adsk.fusion.DistanceUnits.MillimeterDistanceUnits
    except Exception:
        pass
    try:
        opts.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementHigh
    except Exception:
        pass
    return bool(em.execute(opts))


def _export_stl(design, parts, folder, dome):
    """Each part type as its own binary STL in mm, lying flat as built in its
    component (labels up); the type (a plate with its digit) and the count are in the name."""
    written = 0
    em = design.exportManager
    for comp, qty, label in parts:
        if comp.bRepBodies.count == 0:
            continue
        if _stl(em, comp.bRepBodies.item(0), os.path.join(folder, '{} x{}.stl'.format(core.part_title(dome, label),
                                                                                     qty))):
            written += 1
    return written


def _bed_suffix(lay, index):
    """' - Board E x30' for a bed of one part type (a pile), nothing for a mixed one."""
    if len(layout.type_counts(lay.sheets[index])) == 1:
        return ' - ' + layout.sheet_contents(lay, index)
    return ''


def _export_bed_stl(design, sheets, folder, name, lay):
    """A model: every print bed of the layout as one STL, the parts lying in place;
    a bed of one type says in its name what is on it."""
    em, written, n = design.exportManager, 0, len(sheets)
    for i, comp in enumerate(sheets):
        path = os.path.join(folder, '{} - bed {:02d} of {:02d}{}.stl'.format(name, i + 1, n, _bed_suffix(lay, i)))
        if _stl(em, comp, path):
            written += 1
    return written


def _export_dxf(lay, folder, name, model=False):
    """One DXF per sheet (R12, mm), straight from the core geometry of this dome;
    a model's beds say in the name what is on them."""
    n = len(lay.sheets)
    for i in range(n):
        if model:
            path = os.path.join(folder, '{} - bed {:02d} of {:02d}{}.dxf'.format(name, i + 1, n, _bed_suffix(lay, i)))
        else:
            path = os.path.join(folder, '{} - sheet {:02d} of {:02d}.dxf'.format(name, i + 1, n))
        with open(path, 'w', encoding='ascii', errors='replace', newline='\r\n') as f:
            f.write(layout.sheet_dxf(lay, i))
    return n


def _local_matrix(o2, ex, ey):
    """Transform inside a sheet component: sheet coordinates (mm, z up), no Y-up swap."""
    m = adsk.core.Matrix3D.create()
    m.setWithCoordinateSystem(adsk.core.Point3D.create(o2[0] / 10.0, o2[1] / 10.0, 0.0),
                              adsk.core.Vector3D.create(ex[0], ex[1], 0.0),
                              adsk.core.Vector3D.create(ey[0], ey[1], 0.0),
                              adsk.core.Vector3D.create(0.0, 0.0, 1.0))
    return m


def _sheets_origin(dome, lay, test_hub=False):
    """Corner of the first sheet: beside the dome on its floor (beside a test hub)."""
    p = dome.p
    if test_hub:
        return (max(3.0 * dome.plate_size, 0.2 * lay.L), -lay.W / 2.0, 0.0)
    return (1.2 * p.R + p.plate + 0.1 * lay.L, p.R - lay.W, dome.z_floor)


def _build_sheets(parent, dome, lay, parts, progress, origin):
    """The same part components once more, lying flat on their sheets: a component
    per sheet (outline sketch + occurrences), its own frame z up, so a sheet
    exports as a ready print bed. Only this build's parts: nothing else is touched."""
    comps = {label: comp for comp, _qty, label in parts}
    group = _fixed(parent.occurrences.addNewComponent(adsk.core.Matrix3D.create())).component
    group.name = 'Sheets'
    n = len(lay.sheets)
    cols = max(1, int(math.ceil(math.sqrt(n))))
    space = 0.1 * lay.W
    sheets = []
    for i, sheet in enumerate(lay.sheets):
        col, row = i % cols, i // cols
        o = (origin[0] + col * (lay.L + space), origin[1] - row * (lay.W + space), origin[2])
        # Fusion shifts a part that is inserted into a component already moved away
        # from its parent's origin (by the turn of the part's first occurrence), so
        # each sheet is filled at the origin and only then placed beside the dome
        temp = group.occurrences.addNewComponent(adsk.core.Matrix3D.create())
        comp = temp.component
        comp.name = 'Sheet {:02d}'.format(i + 1)
        sketch = comp.sketches.add(comp.xYConstructionPlane)
        sketch.name = 'Sheet {:g} x {:g}'.format(lay.L, lay.W)
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(_p2((0.0, 0.0)), _p2((lay.L, lay.W)))
        for pl in sheet:
            src = comps.get(pl.part.key)
            if src is None:
                continue
            o2, ex, ey = pl.frame2d()
            _free(comp.occurrences.addExistingComponent(src, _local_matrix(o2, ex, ey)))
            progress.tick()
        _fixed(group.occurrences.addExistingComponent(comp, _matrix((o, (1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
                                                                     (0.0, 0.0, 1.0)))))
        temp.deleteMe()
        sheets.append(comp)
    return sheets


def _build_test_hub(design, dome):
    """The most common 6-strut hub with both plates, board stubs and spacers,
    standing axis-up at the origin, every part a body ready for nesting."""
    d, p = dome, dome.p
    n = core.test_hub_node(d)
    hub = core.plate_frame(d, n)
    outer_name, inner_name = d.node_plate_names[n]
    group = _fixed(design.rootComponent.occurrences.addNewComponent(adsk.core.Matrix3D.create())).component
    group.name = 'Test hub {} - {}'.format(outer_name, d.name)
    lab, lh = p.labels, p.label_height
    outer_key, inner_key = 'Plate {} outer'.format(outer_name), 'Plate {} inner'.format(inner_name)
    parts = [(_make_part(group, core.part_title(d, outer_key), core.plate_geometry(d, n),
                         core.frame_in(core.plate_frame(d, n), hub), lab, lh), 1, outer_key),
             (_make_part(group, core.part_title(d, inner_key), core.plate_geometry(d, n, True),
                         core.frame_in(core.plate_frame(d, n, True), hub), lab, lh), 1, inner_key)]
    stubs, stub_qty, spacer, spacer_qty = {}, {}, None, 0
    for m, ti, _si in d.adj[n]:
        geo = core.board_geometry(d, ti, stub=True)
        for off in p.board_offsets():
            frame = core.frame_in(core.board_frame(d, n, m, ti, off), hub)
            if ti in stubs:
                _free(group.occurrences.addExistingComponent(stubs[ti], _matrix(frame)))
            else:
                stubs[ti] = _make_part(group, 'Stub ' + core.LETTERS[ti], geo, frame, lab, lh)
            stub_qty[ti] = stub_qty.get(ti, 0) + 1
        for x in geo['spacers_x']:
            frame = core.frame_in(core.spacer_frame(d, n, m, ti, x), hub)
            if spacer is None:
                spacer = _make_part(group, 'Spacer', core.spacer_geometry(d), frame, False, lh)
            else:
                _free(group.occurrences.addExistingComponent(spacer, _matrix(frame)))
            spacer_qty += 1
    parts += [(stubs[ti], stub_qty[ti], 'Stub ' + core.LETTERS[ti]) for ti in sorted(stubs)]
    if spacer is not None:
        parts.append((spacer, spacer_qty, 'Spacer'))
    if d.has_tubes:
        tube = _make_part(group, 'Tube', core.tube_geometry(d), core.frame_in(core.tube_frame(d, n), hub), False, lh)
        parts.append((tube, 1, 'Tube'))
    return group, parts


# ----------------------------------------------------------------- handlers
class CreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        global _edit_occurrence, _y_up, _lang
        try:
            cmd = args.command
            _lang = _load_lang()
            _accepted_flag[0] = _accepted()
            cmd.okButtonText = M('build')
            try:
                cmd.cancelButtonText = M('cancel')
            except Exception:
                pass
            try:
                cmd.setDialogInitialSize(520, 800)
            except Exception:
                pass
            _y_up = _up_is_y()
            carried, _relaunch['state'] = _relaunch['state'], None
            state = None
            if carried:
                p, state, _edit_occurrence = carried
                if _edit_occurrence is not None and not _edit_occurrence.isValid:
                    _edit_occurrence = None
            else:
                p, _edit_occurrence = _initial_params()
            inputs = cmd.commandInputs
            dd = inputs.addDropDownCommandInput('lang', TEXT['lang'][0], adsk.core.DropDownStyles.TextListDropDownStyle)
            for code, name in LANGS:
                dd.listItems.add(name, code == _lang, '')
            _tip(dd, 'lang')
            _build_inputs(inputs, p, state)
            _update_results(inputs)
            for event, cls in ((cmd.inputChanged, ChangedHandler), (cmd.validateInputs, ValidateHandler),
                               (cmd.executePreview, PreviewHandler), (cmd.execute, ExecuteHandler),
                               (cmd.destroy, DestroyHandler)):
                handler = cls()
                event.add(handler)
                _handlers.append(handler)
        except Exception:
            _error()


class ChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            command = adsk.core.Command.cast(args.firingEvent.sender)
            inputs = command.commandInputs
            changed = args.input
            cid = changed.id
            if cid == 'lang':
                item = adsk.core.DropDownCommandInput.cast(changed).selectedItem
                lang = next((code for code, name in LANGS if item and item.name == name), 'en')
                if lang != _lang:
                    _switch_language(inputs, lang)
                return
            if cid == 'disclaimer_ok':
                box = adsk.core.BoolValueCommandInput.cast(changed)
                if box.value:      # accepted once: the box goes, the block with the links stays
                    _save_setting('disclaimer', DISCLAIMER_VERSION)
                    _accepted_flag[0] = True
                    box.isVisible = False
                return
            if cid in ('support', 'share', 'telegram'):
                _open_url({'support': KOFI_URL, 'share': INSTAGRAM_URL, 'telegram': TELEGRAM_URL}[cid])
                return
            if cid == 'about':
                _ui.messageBox(_about_text(), CMD_NAME)
                return
            if cid == 'preset':
                _load_preset(inputs)
            elif cid == 'preset_save':
                _save_preset(inputs)
            _update_results(inputs)
        except Exception:
            _error()


class ValidateHandler(adsk.core.ValidateInputsEventHandler):
    def notify(self, args):
        try:
            dome = _analyze(_read_params(args.inputs))
            args.areInputsValid = not dome.errors and _accepted_flag[0]
            if dome.errors:
                _clear_graphics()
        except Exception:
            _error()


class PreviewHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            dome = _analyze(_read_params(args.command.commandInputs))
            if dome.errors:
                _clear_graphics()
            else:
                _draw_preview(dome)
            args.isValidResult = False
        except Exception:
            _error()


class ExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        global _edit_occurrence
        try:
            _clear_graphics()
            inputs = args.command.commandInputs
            p = _read_params(inputs)
            dome = _analyze(p)
            if dome.errors:
                _ui.messageBox('\n'.join(core.translate(e, _lang) for e in dome.errors), CMD_NAME)
                return
            design = adsk.fusion.Design.cast(_app.activeProduct)
            if not design:
                _ui.messageBox(M('no_design'), CMD_NAME)
                return
            st = _read_state(inputs)
            mode = st['build_mode']
            del _label_problems[:]
            lay = _layout_for(dome, mode) if (st.get('layout') or st.get('export_dxf')) else None
            lay_bodies = bool(lay is not None and st.get('layout') and lay.sheets)
            report, parts, sheets, name = [], [], [], dome.name
            started = time.time()
            if mode == 'Test hub':
                group, parts = _build_test_hub(design, dome)
                name = group.name
                report.append(M('test_hub', name))
                if lay_bodies:
                    sheets = _build_sheets(group, dome, lay, parts, _NoProgress(),
                                           _sheets_origin(dome, lay, test_hub=True))
            else:
                if _edit_occurrence is not None and _edit_occurrence.isValid:
                    _edit_occurrence.deleteMe()
                _edit_occurrence = None
                if mode == 'Full dome':
                    progress = _Progress(dome.n_boards + dome.n_plates + dome.n_spacers +
                                         (dome.n_hubs if dome.has_tubes else 0) + len(dome.feet) +
                                         (sum(lay.placed.values()) if lay_bodies else 0))
                    try:
                        occ, count, parts = _build_dome(design, dome, progress)
                        if lay_bodies:
                            sheets = _build_sheets(occ.component, dome, lay, parts, progress,
                                                   _sheets_origin(dome, lay))
                    finally:
                        progress.close()
                    report.append(M('built', dome.name, count, time.time() - started))
                else:
                    _build_skeleton(design, dome)
                    report.append(M('skeleton', dome.name))
            folder = None
            if mode == 'Full dome' and st.get('bom_csv'):
                path = _save_bom(dome)
                if path:
                    report.append(M('bom_saved', path))
                    folder = os.path.dirname(path)
            want_stl = bool(dome.model and parts and st.get('export_stl'))
            want_dxf = bool(lay is not None and st.get('export_dxf') and lay.sheets)
            if (want_stl or want_dxf) and not folder:
                folder = _ask_folder()
            if folder and want_stl:
                report.append(M('stl_saved', _export_stl(design, parts, folder, dome), folder))
                if sheets:
                    report.append(M('bed_stl_saved', _export_bed_stl(design, sheets, folder, name, lay)))
            if folder and want_dxf:
                report.append(M('dxf_saved', _export_dxf(lay, folder, name, dome.model), folder))
            if lay is not None:
                report += layout.summary_lines(lay, _lang)
                if sheets:
                    report.append(M('sheets_built'))
            _remember_last(p)
            if _label_problems:
                _ui.messageBox(M('labels_failed', _label_problems[0]), CMD_NAME)
            elif mode == 'Full dome' or len(report) > 1:
                _ui.messageBox('\n'.join(report + ['', M('tag_line')]), CMD_NAME)
        except Exception:
            _error()


class RelaunchHandler(adsk.core.CustomEventHandler):
    """Runs when Fusion is idle after a language change: closes the open dialog and
    opens it again (terminateActiveCommand is not allowed inside command events)."""

    def notify(self, args):
        try:
            if _ui.activeCommand == CMD_ID:
                _ui.terminateActiveCommand()
            cmd_def = _ui.commandDefinitions.itemById(CMD_ID)
            if cmd_def:
                cmd_def.execute()
        except Exception:
            _relaunch['state'] = None
            _error()


class DestroyHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        global _edit_occurrence
        try:
            _clear_graphics()
            _edit_occurrence = None
        except Exception:
            _error()


# ------------------------------------------------------------- add-in entry
def run(context):
    global _app, _ui
    try:
        _app = adsk.core.Application.get()
        _ui = _app.userInterface
        importlib.reload(core)
        importlib.reload(layout)
        cmd_def = _ui.commandDefinitions.itemById(CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()
        icons = RESOURCES if os.path.isdir(RESOURCES) else ''
        cmd_def = _ui.commandDefinitions.addButtonDefinition(CMD_ID, CMD_NAME, CMD_TIP, icons)
        handler = CreatedHandler()
        cmd_def.commandCreated.add(handler)
        _handlers.append(handler)
        try:   # a language change reopens the dialog through this event
            _app.unregisterCustomEvent(RELAUNCH_EVENT)
        except Exception:
            pass
        event = _app.registerCustomEvent(RELAUNCH_EVENT)
        if event:
            relaunch = RelaunchHandler()
            event.add(relaunch)
            _handlers.append(relaunch)
            _relaunch['ready'] = True
        panel = _ui.allToolbarPanels.itemById(PANEL_ID)
        if panel:
            ctrl = panel.controls.itemById(CMD_ID)
            if ctrl:
                ctrl.deleteMe()
            ctrl = panel.controls.addCommand(cmd_def)
            try:   # the icon right on the toolbar, not only inside the Create menu
                ctrl.isPromoted = True
                ctrl.isPromotedByDefault = True
            except Exception:
                pass
    except Exception:
        _error()


def stop(context):
    try:
        _clear_graphics()
        if _ui:
            panel = _ui.allToolbarPanels.itemById(PANEL_ID)
            ctrl = panel.controls.itemById(CMD_ID) if panel else None
            if ctrl:
                ctrl.deleteMe()
            cmd_def = _ui.commandDefinitions.itemById(CMD_ID)
            if cmd_def:
                cmd_def.deleteMe()
        _relaunch['ready'] = False
        if _app:
            try:
                _app.unregisterCustomEvent(RELAUNCH_EVENT)
            except Exception:
                pass
        _handlers.clear()
    except Exception:
        _error()
