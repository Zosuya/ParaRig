#!/usr/bin/env python3
"""產生control_style圖示選擇器(panels.py的template_icon_view)用的縮圖PNG。

**這個腳本不會被打包進addon,也不會在執行期被呼叫**——它是開發工具,
只在「要改圖示的形狀或配色」的時候手動跑一次,把產出的PNG commit進
版本控制。addon執行期只負責讀檔(見icons.py的register())。

用法(在repo根目錄):

    python tools/generate_control_style_icons.py

會覆寫para_rig/thumbnails/底下全部的檔案。不需要Blender,純標準函式庫
(struct+zlib),任何Python 3都能跑。

ICON_SIZE定成256是有實測依據的:bpy.utils.previews內部最大就只存
256x256,餵512進去Blender會在載入當下直接縮回256(Blender 5.2實測),
所以256是「剛好用滿Blender能力」的上限,再往上畫質不會變好。舊版
(v1.1.0以前)是在register()裡即時畫64x64,放大到選擇器格子裡會糊。

所有繪圖座標都是以64為基準寫的(沿用最早64x64版本的構圖數值),再透過
_u()按ICON_SIZE等比放大——構圖跟舊版完全一樣,只是解析度變高。
"""

import os
import struct
import zlib

# 產出尺寸。改這個值全部的圖會整體等比縮放,構圖比例不變。
ICON_SIZE = 256

BG_COLOR = (0.14, 0.14, 0.16, 1.0)
TRACK_COLOR = (0.55, 0.62, 0.95, 1.0)
HANDLE_COLOR = (0.95, 0.95, 0.95, 1.0)

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'para_rig', 'thumbnails',
)


def _u(value):
    """把「以64x64為基準」的座標/長度換算成目前ICON_SIZE下的實際像素。"""
    return value * ICON_SIZE / 64.0


def _blank_canvas():
    pixels = []
    for _unused_i in range(ICON_SIZE * ICON_SIZE):
        pixels.extend(BG_COLOR)
    return pixels


def _set_pixel(pixels, x, y, color):
    if not (0 <= x < ICON_SIZE and 0 <= y < ICON_SIZE):
        return
    i = (y * ICON_SIZE + x) * 4
    pixels[i:i + 4] = color


def _fill_rect(pixels, x0, y0, x1, y1, color):
    """填滿一個矩形。座標接受float(_u()換算出來的值不一定是整數),
    在這裡才round成實際像素邊界。"""
    for y in range(max(0, int(round(y0))), min(ICON_SIZE, int(round(y1)))):
        for x in range(max(0, int(round(x0))), min(ICON_SIZE, int(round(x1)))):
            _set_pixel(pixels, x, y, color)


def _fill_circle(pixels, cx, cy, radius, color):
    """畫實心圓,邊緣用單環supersample(每個邊界像素切成4個子樣本取覆蓋率)
    做抗鋸齒。像素中心取(x+0.5, y+0.5),不是整數座標本身,否則圓心會
    系統性偏向左上。"""
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
    _draw_outline_rect(pixels, cx - _u(7), _u(8), cx + _u(7), ICON_SIZE - _u(8),
                       TRACK_COLOR, thickness=_u(3))
    _fill_circle(pixels, cx, cy, _u(10), HANDLE_COLOR)
    return pixels


def _icon_linear_1d_horizontal():
    """橫向1軸滑桿:同一根長條外框轉90度,把手一樣置中——跟實際生成結果
    (Track繞Z軸轉90度,不改mesh本身)的視覺呼應一致。"""
    pixels = _blank_canvas()
    cx, cy = ICON_SIZE / 2, ICON_SIZE / 2
    _draw_outline_rect(pixels, _u(8), cy - _u(7), ICON_SIZE - _u(8), cy + _u(7),
                       TRACK_COLOR, thickness=_u(3))
    _fill_circle(pixels, cx, cy, _u(10), HANDLE_COLOR)
    return pixels


def _icon_xy_2d():
    """XY_2D拖拽板:正方形外框+十字分隔線+置中把手,呼應grid_canvas.
    _draw_item_icon()裡「未知樣式/XY_2D」共用的fallback圖示(內縮方框+
    十字線+中央把手)。"""
    pixels = _blank_canvas()
    cx, cy = ICON_SIZE / 2, ICON_SIZE / 2
    _draw_outline_rect(pixels, _u(10), _u(10), ICON_SIZE - _u(10), ICON_SIZE - _u(10),
                       TRACK_COLOR, thickness=_u(3))
    _fill_rect(pixels, cx - _u(1), _u(10), cx + _u(2), ICON_SIZE - _u(10), TRACK_COLOR)
    _fill_rect(pixels, _u(10), cy - _u(1), ICON_SIZE - _u(10), cy + _u(2), TRACK_COLOR)
    _fill_circle(pixels, cx, cy, _u(9), HANDLE_COLOR)
    return pixels


def _icon_text_label():
    """純文字:沒有Track/Handle可畫(這個樣式本來就沒有控制器本體),用
    三條粗細不一、置中對齊的橫條模擬一段文字排版的剪影。"""
    pixels = _blank_canvas()
    cx = ICON_SIZE / 2
    line_specs = [(18, 0.7), (30, 1.0), (42, 0.5)]  # (64基準的y座標, 相對寬度)
    max_half_width = 20
    for y, width_ratio in line_specs:
        half_w = _u(max_half_width * width_ratio)
        _fill_rect(pixels, cx - half_w, _u(y), cx + half_w, _u(y) + _u(6), HANDLE_COLOR)
    return pixels


# key跟properties.CONTROL_STYLE_ITEMS的identifier一一對應,檔名是
# control_style_<identifier>.png——icons.py的register()照同一個規則讀檔。
# 新增control_style時,這裡加一筆畫圖函式、重跑一次這支腳本。
_ICON_BUILDERS = {
    'LINEAR_1D': _icon_linear_1d,
    'LINEAR_1D_HORIZONTAL': _icon_linear_1d_horizontal,
    'XY_2D': _icon_xy_2d,
    'TEXT_LABEL': _icon_text_label,
}


def _write_png(path, width, height, rgba_bytes):
    """手工組一個最小可用的PNG檔案(只有IHDR/IDAT/IEND三個chunk)寫到
    path。純Python標準函式庫,不需要Pillow之類的第三方套件。
    rgba_bytes是長度width*height*4的bytes,每個channel是0~255的整數。"""
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


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    total = 0
    for style, builder in _ICON_BUILDERS.items():
        float_pixels = builder()
        byte_pixels = bytes(
            min(255, max(0, round(c * 255))) for c in float_pixels)
        filename = f"control_style_{style}.png"
        path = os.path.join(OUTPUT_DIR, filename)
        _write_png(path, ICON_SIZE, ICON_SIZE, byte_pixels)
        size = os.path.getsize(path)
        total += size
        print(f"  {ICON_SIZE}x{ICON_SIZE}  {size / 1024:5.1f}KB  {filename}")
    print(f"\n完成,共{len(_ICON_BUILDERS)}張 / {total / 1024:.1f}KB → {OUTPUT_DIR}")


if __name__ == '__main__':
    main()
