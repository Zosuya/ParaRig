"""control_style的視覺化圖示選擇器:仿造Bone Widget等rigging addon常見的
shape picker UI——平常顯示目前選中樣式的縮圖,點下去彈出一個縮圖網格讓
使用者直接點選,取代純文字的下拉選單。這裡只負責生成/管理這些縮圖的
`bpy.utils.previews`(自訂icon),純圖示資料,不含任何PropertyGroup/
Operator/Panel類別。

縮圖用純Python逐像素畫出簡單幾何圖形(矩形外框+圓形把手,直向/橫向/
XY_2D三種),不依賴任何外部圖片檔案——這個addon沒有build流程,不想額外
帶一批bundled PNG資源,用程式產生剛好呼應grid_canvas.py那套「軌道+把手」
的視覺語言,使用者一眼就能把選單裡的縮圖跟排布編輯畫布上的控制器圖示
對起來。

**不透過bpy.data.images產生PNG**(這點很重要,踩過兩次真實bug才確定):
`bpy.data.images.new()`/`.pixels =` 在好幾個Blender認定的「限制context」
下都不能寫——`register()`執行期間會丟`AttributeError:
'_RestrictData' object has no attribute 'images'`;移到EnumProperty的
動態items callback裡執行(想說delay到UI真的要顯示才做)一樣會丟
`AttributeError: Writing to ID classes in this context is not allowed`
(兩個都是使用者實測回報的真實crash,不是理論風險)。與其一直找「這個
時間點到底安不安全」,乾脆整個繞開`bpy.data`:PNG檔案用Python標準函式庫
(`struct`+`zlib`,沒有額外依賴)手刻編碼寫出來,不管在哪個context呼叫
都不會被`_RestrictData`擋。`bpy.utils.previews`本身(`pcoll.load()`)
不受這個限制影響(Bone Widget的register()就直接呼叫它),所以圖示生成
可以照Bone Widget的模式整個放回`register()`裡一次做完,不需要lazy-load
的額外機制。
"""

import os
import struct
import zlib

import bpy
import bpy.utils.previews

ICON_SIZE = 64

BG_COLOR = (0.14, 0.14, 0.16, 1.0)
TRACK_COLOR = (0.55, 0.62, 0.95, 1.0)
HANDLE_COLOR = (0.95, 0.95, 0.95, 1.0)

_preview_collections = {}
_control_style_items = None  # 見control_style_enum_items()的說明
_generated_icon_paths = []  # register()寫出的暫存PNG路徑,unregister()清掉


def _blank_canvas():
    pixels = []
    for _ in range(ICON_SIZE * ICON_SIZE):
        pixels.extend(BG_COLOR)
    return pixels


def _set_pixel(pixels, x, y, color):
    if not (0 <= x < ICON_SIZE and 0 <= y < ICON_SIZE):
        return
    i = (y * ICON_SIZE + x) * 4
    pixels[i:i + 4] = color


def _fill_rect(pixels, x0, y0, x1, y1, color):
    for y in range(max(0, y0), min(ICON_SIZE, y1)):
        for x in range(max(0, x0), min(ICON_SIZE, x1)):
            _set_pixel(pixels, x, y, color)


def _fill_circle(pixels, cx, cy, radius, color):
    """畫實心圓,邊緣用單環supersample(每個邊界像素切成4個子樣本取覆蓋率)
    做抗鋸齒,避免圖示縮成32x32 icon_pixels_float後邊緣階梯感被放大成
    「看起來不圓」。像素中心取(x+0.5, y+0.5),不是整數座標本身,否則圓心
    會系統性偏向左上。"""
    outer = radius + 1
    for y in range(max(0, int(cy - outer)), min(ICON_SIZE, int(cy + outer) + 1)):
        for x in range(max(0, int(cx - outer)), min(ICON_SIZE, int(cx + outer) + 1)):
            px, py = x + 0.5, y + 0.5
            dist = ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5
            if dist <= radius - 0.5:
                _set_pixel(pixels, x, y, color)
            elif dist <= radius + 0.5:
                coverage = 0.0
                for sub_x in (0.25, 0.75):
                    for sub_y in (0.25, 0.75):
                        sx, sy = x + sub_x, y + sub_y
                        if (sx - cx) ** 2 + (sy - cy) ** 2 <= radius * radius:
                            coverage += 0.25
                if coverage > 0.0:
                    i = (y * ICON_SIZE + x) * 4
                    bg = pixels[i:i + 4]
                    blended = [bg[c] + (color[c] - bg[c]) * coverage for c in range(4)]
                    _set_pixel(pixels, x, y, blended)


def _draw_outline_rect(pixels, x0, y0, x1, y1, color, thickness):
    _fill_rect(pixels, x0, y0, x1, y0 + thickness, color)
    _fill_rect(pixels, x0, y1 - thickness, x1, y1, color)
    _fill_rect(pixels, x0, y0, x0 + thickness, y1, color)
    _fill_rect(pixels, x1 - thickness, y0, x1, y1, color)


def _icon_linear_1d():
    """直向1軸滑桿:一根直立的長條外框+置中的圓形把手,呼應grid_canvas.
    _draw_item_icon()裡LINEAR_1D的畫法(細長軌道+圓形Handle)。"""
    pixels = _blank_canvas()
    cx, cy = ICON_SIZE / 2, ICON_SIZE / 2
    _draw_outline_rect(pixels, int(cx - 7), 8, int(cx + 7), ICON_SIZE - 8, TRACK_COLOR, thickness=3)
    _fill_circle(pixels, cx, cy, 10, HANDLE_COLOR)
    return pixels


def _icon_linear_1d_horizontal():
    """橫向1軸滑桿:同一根長條外框轉90度,把手一樣置中——跟實際生成結果
    (Track繞Z軸轉90度,不改mesh本身)的視覺呼應一致。"""
    pixels = _blank_canvas()
    cx, cy = ICON_SIZE / 2, ICON_SIZE / 2
    _draw_outline_rect(pixels, 8, int(cy - 7), ICON_SIZE - 8, int(cy + 7), TRACK_COLOR, thickness=3)
    _fill_circle(pixels, cx, cy, 10, HANDLE_COLOR)
    return pixels


def _icon_xy_2d():
    """XY_2D拖拽板:正方形外框+十字分隔線+置中把手,呼應grid_canvas.
    _draw_item_icon()裡「未知樣式/XY_2D」共用的fallback圖示(內縮方框+
    十字線+中央把手)。"""
    pixels = _blank_canvas()
    cx, cy = ICON_SIZE / 2, ICON_SIZE / 2
    _draw_outline_rect(pixels, 10, 10, ICON_SIZE - 10, ICON_SIZE - 10, TRACK_COLOR, thickness=3)
    _fill_rect(pixels, int(cx - 1), 10, int(cx + 2), ICON_SIZE - 10, TRACK_COLOR)
    _fill_rect(pixels, 10, int(cy - 1), ICON_SIZE - 10, int(cy + 2), TRACK_COLOR)
    _fill_circle(pixels, cx, cy, 9, HANDLE_COLOR)
    return pixels


def _icon_text_label():
    """純文字:沒有Track/Handle可畫(這個樣式本來就沒有控制器本體),用
    三條粗細不一、置中對齊的橫條模擬一段文字排版的剪影,顏色沿用
    HANDLE_COLOR(跟grid_canvas.py的綠色不同——這裡只是縮圖,不需要跟
    排版畫布的顏色語意綁在一起)。這樣跟其他三個「畫實際幾何形狀」的
    圖示風格一致,一眼能看出「這個不是可拖拽的控制器」。"""
    pixels = _blank_canvas()
    cx = ICON_SIZE / 2
    line_specs = [(18, 0.7), (30, 1.0), (42, 0.5)]  # (y座標, 相對寬度)
    max_half_width = 20
    for y, width_ratio in line_specs:
        half_w = max_half_width * width_ratio
        _fill_rect(pixels, int(cx - half_w), y, int(cx + half_w), y + 6, HANDLE_COLOR)
    return pixels


# key跟properties.CONTROL_STYLE_ITEMS的identifier一一對應——新增
# control_style時,記得也要來這裡登記一個對應的畫圖函式,不然
# control_style_icon_id()會找不到、退回ICON_NONE(不會crash,但選單那格
# 會沒有縮圖)。
_ICON_BUILDERS = {
    'LINEAR_1D': _icon_linear_1d,
    'LINEAR_1D_HORIZONTAL': _icon_linear_1d_horizontal,
    'XY_2D': _icon_xy_2d,
    'TEXT_LABEL': _icon_text_label,
}


def _write_png(path, width, height, rgba_bytes):
    """手工組一個最小可用的PNG檔案寫到path,完全不透過bpy.data——純
    Python標準函式庫(struct組binary、zlib壓縮),不管在哪個Blender
    context呼叫都不會被`_RestrictData`擋下來(見模組docstring)。
    rgba_bytes是長度width*height*4的bytes,每個channel是0~255的整數
    (不是0.0~1.0的float,呼叫端要自己轉換)。"""
    def chunk(tag, data):
        return (
            struct.pack(">I", len(data)) + tag + data +
            struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
        )

    signature = b'\x89PNG\r\n\x1a\n'
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA

    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)  # 每個掃描線前綴的filter type(0=None)
        raw.extend(rgba_bytes[y * stride:(y + 1) * stride])
    idat = zlib.compress(bytes(raw), 9)

    with open(path, 'wb') as f:
        f.write(signature)
        f.write(chunk(b'IHDR', ihdr))
        f.write(chunk(b'IDAT', idat))
        f.write(chunk(b'IEND', b''))


def _write_icon_png(style, float_pixels):
    """把float_pixels(RGBA float、每個channel0.0~1.0,長度
    ICON_SIZE*ICON_SIZE*4)轉成byte後手刻存成PNG,回傳檔案路徑。存到
    bpy.app.tempdir(不是這個addon自己的原始碼目錄)——不想讓執行期產生
    的暫存圖片檔案混進版本控制的目錄裡,每次register()都會重新產生,
    不依賴上一次留下的檔案是否還在。"""
    byte_pixels = bytes(min(255, max(0, round(c * 255))) for c in float_pixels)
    path = os.path.join(bpy.app.tempdir, f"slider_rig_icon_{style}.png")
    _write_png(path, ICON_SIZE, ICON_SIZE, byte_pixels)
    return path


def control_style_icon_id(control_style):
    """回傳這個control_style對應的自訂縮圖icon_value(int),給
    control_style_enum_items()組EnumProperty items時用。圖示還沒生成過
    (理論上只會在register()還沒跑完、或unregister()之後這種不該發生
    UI互動的空窗期發生)就回傳0(Blender的ICON_NONE),不直接炸掉。"""
    pcoll = _preview_collections.get("main")
    if pcoll is None or control_style not in pcoll:
        return 0
    return pcoll[control_style].icon_id


def control_style_enum_items():
    """回傳control_style這個EnumProperty要用的items清單(每個tuple帶
    icon_value)。這是動態(callback)形式的enum items,Blender官方文件
    明確警告:callback每次被呼叫時,如果都重新配置一份新的list/tuple,
    Python端的字串物件可能在Blender的C端還在使用這份items時就被GC回收,
    導致UI顯示亂碼甚至直接crash——必須讓Python端持有同一份不會被回收的
    固定參照,所以這裡快取成模組層級變數,只在第一次呼叫(或register()
    重建icon之後)才重新組一次。

    另外,動態items的EnumProperty不支援`default`參數(Blender會直接
    忽略/報錯),所以property定義那邊拿掉了`default='LINEAR_1D'`,改成
    依賴「沒有items()['default']的enum屬性in預設情況下取第一筆」——只要
    這裡回傳的list第一筆維持是LINEAR_1D(識別碼、順序都跟
    properties.CONTROL_STYLE_ITEMS原本的第一筆一致),新item的
    control_style實際預設值就還是'LINEAR_1D',效果沒變,只是不是透過
    明講的`default=`關鍵字達成。"""
    global _control_style_items
    if _control_style_items is None:
        from .properties import CONTROL_STYLE_ITEMS
        _control_style_items = [
            (identifier, name, desc, control_style_icon_id(identifier), i)
            for i, (identifier, name, desc) in enumerate(CONTROL_STYLE_ITEMS)
        ]
    return _control_style_items


def register():
    global _control_style_items
    _control_style_items = None  # 舊快取的icon_value對應到即將被
    # remove()的preview collection,reload/重新註冊時必須重建,不能沿用
    pcoll = bpy.utils.previews.new()
    for style, builder in _ICON_BUILDERS.items():
        path = _write_icon_png(style, builder())
        _generated_icon_paths.append(path)
        pcoll.load(style, path, 'IMAGE')
    _preview_collections["main"] = pcoll


def unregister():
    global _control_style_items
    for pcoll in _preview_collections.values():
        bpy.utils.previews.remove(pcoll)
    _preview_collections.clear()
    _control_style_items = None
    for path in _generated_icon_paths:
        if os.path.exists(path):
            os.remove(path)
    _generated_icon_paths.clear()
