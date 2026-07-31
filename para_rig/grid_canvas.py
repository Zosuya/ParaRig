"""排布編輯畫布:在3D Viewport疊一層POST_PIXEL繪製的2D網格,顯示某個
group底下所有滑桿項目佔用的格子並支援拖曳/互換/擴充。純繪製與座標轉換
邏輯留在這裡(不含bpy.types的Operator/Panel類別,那些在operators.py),
只依賴grid_layout.py的純函式判斷佔用/衝突,不重複那些邏輯。

畫布狀態(目前正在編輯哪個group、拖曳中是哪個item)是模組層級變數,因為
一次只會有一個編輯畫布在運作(modal operator本身就是單例的操作模式)。
"""

import math

import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader

from .grid_layout import (
    CONTROL_STYLE_CELLS, cells_for, content_bounds, items_overlapping_at,
    occupied_cells, same_item,
)

DEFAULT_CELL_PX = 96  # px,畫布上一格的「邏輯」螢幕尺寸(跟世界空間的
# CELL_SIZE無關)。曾經有過可拖曳調整的縮放滑塊,後來取消了——直接固定用
# 當時滑塊能拉到的最大值當唯一的顯示大小,不再讓使用者調整。這是套用
# ui_scale()之前的基準值,實際畫出來的像素大小是這個值乘上ui_scale()。

# 畫布預設顯示10x10格。格子數在這個範圍以內時,面板大小完全貼合內容
# (跟以前的行為一樣);一旦欄或列數超過10,面板不再繼續長大,而是固定
# 顯示10格寬/高的「視窗」,超出視窗的部分要靠拖曳空白處平移(state["pan"])
# 才看得到——面板不會無限長高長寬到超出viewport可見範圍。
DEFAULT_GRID_CELLS = 10
MAX_GRID_SIZE = 100  # 格子總數上限(不是視窗大小)。以前沒有平移功能時,
# 這個值刻意壓低避免內容超出viewport裁切看不到;現在有平移+裁剪(scissor)
# 撐著,可以大幅提高。

PLUS_HIT_SIZE = 20

# 外框(整個介面的可視邊界,不只是格子視窗本身)跟格子視窗之間的留白,
# 分別給四邊留夠列/欄座標數字跟+按鈕的空間。標題列畫在面板外框「外面」
# (上方),不佔用這個margin,所以上緣不用額外加寬。
PANEL_LEFT_MARGIN = 34
PANEL_TOP_MARGIN = 34
PANEL_RIGHT_MARGIN = 50
PANEL_BOTTOM_MARGIN = 50

TITLE_TEXT = "編輯排版"
TITLE_SIZE = 32
HINT_TEXT = "點擊右鍵或ESC離開"
HINT_SIZE = 24
TITLE_GAP = 12  # 標題列跟面板外框上緣之間的垂直間距

state = {
    "group_uid": None,     # 目前正在編輯的group(only這個group的items會顯示)
    "cols": DEFAULT_GRID_CELLS,
    "rows": DEFAULT_GRID_CELLS,
    "cell_px": DEFAULT_CELL_PX,  # 一格的螢幕像素尺寸,固定值,不再提供縮放
    "pan": [0.0, 0.0],      # 內容平移量(dx, dy),恆<=0——見_pan_bounds()。
    # 格子總數超過視窗大小(DEFAULT_GRID_CELLS)時,拖曳畫布空白處平移用。
    "dragging": None,      # 正在拖曳的SliderRigItem,None代表沒有拖曳
    "drag_target": None,   # 拖曳中,item左上角錨點應該對齊的格子(gx, gy)
    "drag_offset": (0, 0),  # 按下當下(滑鼠所在格 - item左上角格)的偏移量;
    # 拖曳判斷要固定以item自己的左上角格跟隨滑鼠,不能直接把「滑鼠當下
    # 懸停的格子」當成新錨點——按下的位置可能是方塊中間或邊緣,不扣掉
    # 這個偏移量會導致item在拖曳當下產生跳動,且在多格footprint時可能讓
    # 夾限邊界算錯,導致某些方向明明還有空間卻無法移動。
    "panning": False,       # 正在拖曳空白處平移畫布
    "pan_anchor": None,     # 按下當下的(mx, my, 當時的pan_dx, pan_dy)
    "origin_px": (60, 60),  # 畫布左下角在viewport裡的像素座標,由update_origin()動態算
}


def ui_scale():
    """回傳目前的Blender UI縮放係數(偏好設定裡的UI Scale,已經包含系統
    螢幕DPI縮放——見Blender官方文件,這是特地給POST_PIXEL這類手動繪圖
    用的縮放依據),再乘上這個addon自己的AddonPreferences裡使用者另外
    設定的百分比(見preferences.grid_canvas_ui_scale_factor())。這個畫布
    完全用blf/gpu手動畫像素,不像bpy.types.UILayout那樣會自動套用UI縮放,
    所以DEFAULT_CELL_PX/PANEL_*_MARGIN/TITLE_SIZE等寫死的像素常數,在不同
    電腦(不同螢幕解析度、系統縮放、或使用者自訂的Blender UI Scale)上會
    顯得比例不一致——同樣「96像素」在4K高DPI螢幕或調高UI Scale的機器上,
    實際佔螢幕的視覺比例明顯比較小(真實使用者回報:同一份.blend檔案在
    不同電腦開,編輯排版畫布大小看起來不一樣)。系統的ui_scale解決的是
    「不同電腦之間比例一致」,但使用者可能還想在這個基礎上再自己微調
    (例如系統縮放正確,但這個畫布本身還是想要再大/再小一點),所以疊加
    一個獨立的使用者可調倍率,不是直接取代系統值。
    所有跟螢幕像素相關的常數都要乘上這個係數才能使用,不能直接讀
    DEFAULT_CELL_PX/PANEL_*_MARGIN等原始值。

    `--background`模式下沒有實際視窗系統,bpy.context.preferences.system.
    ui_scale這個值會是0.0(headless測試實測驗證,不是理論猜測)——照樣
    乘下去會讓cell_px整個變成0,畫布完全塌縮。防呆回傳1.0(=不縮放,
    等同這個功能加入前的行為),只影響headless場景,一般互動使用者一定
    有真正的視窗,不會是0.0。"""
    from . import preferences
    system_scale = bpy.context.preferences.system.ui_scale
    system_scale = system_scale if system_scale > 0.0 else 1.0
    return system_scale * preferences.grid_canvas_ui_scale_factor()


def _group_items(context):
    scene = context.scene
    return [
        it for it in scene.slider_rig_items
        if it.group_uid == state["group_uid"]
    ]


def reset_for_group(context, group_uid):
    """開始編輯某個group時呼叫一次:設定要顯示哪個group,並依現有items的
    佔用範圍決定畫布初始大小(至少DEFAULT_GRID_CELLS x DEFAULT_GRID_CELLS,
    若既有內容超過則以內容為準,避免一開啟畫布既有滑桿就被裁到畫面外)。"""
    state["group_uid"] = group_uid
    items = _group_items(context)
    if items:
        min_x, max_x, min_y, max_y = content_bounds(items)
        state["cols"] = max(DEFAULT_GRID_CELLS, max_x)
        state["rows"] = max(DEFAULT_GRID_CELLS, max_y)
    else:
        state["cols"] = DEFAULT_GRID_CELLS
        state["rows"] = DEFAULT_GRID_CELLS
    state["dragging"] = None
    state["drag_target"] = None
    state["panning"] = False
    state["pan_anchor"] = None
    state["pan"] = [0.0, 0.0]
    _clamp_pan()


def window_dims():
    """回傳目前實際畫出來的「視窗」欄列數——格子總數(state["cols"]/
    ["rows"])超過DEFAULT_GRID_CELLS時,視窗維持在DEFAULT_GRID_CELLS,不
    再跟著格子總數繼續長大,靠pan看超出視窗的部分。"""
    return min(state["cols"], DEFAULT_GRID_CELLS), min(state["rows"], DEFAULT_GRID_CELLS)


def _pan_bounds():
    """回傳pan(dx, dy)個別的合法下界(上界固定是0.0——內容永遠不能被拖到
    視窗左/上邊界的右/下方)。內容總尺寸小於等於視窗時下界就是0,等同不能
    移動,天然對應「格子數在DEFAULT_GRID_CELLS以內不需要平移」的需求,不用
    另外寫一個「平移功能是否啟用」的旗標。"""
    cell_px = state["cell_px"]
    window_cols, window_rows = window_dims()
    total_w = state["cols"] * cell_px
    total_h = state["rows"] * cell_px
    window_w = window_cols * cell_px
    window_h = window_rows * cell_px
    min_dx = min(0.0, window_w - total_w)
    min_dy = min(0.0, window_h - total_h)
    return min_dx, min_dy


def _clamp_pan():
    min_dx, min_dy = _pan_bounds()
    dx, dy = state["pan"]
    state["pan"] = [max(min_dx, min(0.0, dx)), max(min_dy, min(0.0, dy))]


def update_origin(region_width, region_height):
    """依當前viewport尺寸,把畫布位置算成「中間偏左上」——水平方向取視窗
    寬度的1/4當左邊界,垂直方向讓畫布頂部落在視窗上方1/4處。視窗被拉伸/
    縮放時畫布位置要跟著動,不能寫死絕對像素值,所以每次draw都重算一次。
    高度用window_dims()(視窗欄列數,恆不超過DEFAULT_GRID_CELLS)而不是
    state["rows"]——面板大小要固定,不能因為格子總數變多就跟著往下長。

    這裡同時重新計算state["cell_px"](= DEFAULT_CELL_PX * ui_scale()),
    不只是設定origin——這個函式本來就是每次draw_callback都會呼叫一次的
    「每幀刷新」時機點,讓cell_px在使用者執行期間調整Blender偏好設定裡
    的UI Scale時也能跟著即時反映,不用重新開啟編輯排版才生效。"""
    state["cell_px"] = DEFAULT_CELL_PX * ui_scale()
    _, window_rows = window_dims()
    grid_px_h = window_rows * state["cell_px"]
    origin_x = region_width / 4
    origin_y = region_height * 3 / 4 - grid_px_h
    state["origin_px"] = (origin_x, origin_y)


def cell_to_px(gx, gy):
    """格子座標(左上角原點,y向下為正)轉成畫布像素座標(左下角原點,y向上
    為正),疊加目前的平移量(state["pan"])。"""
    ox, oy = state["origin_px"]
    cell_px = state["cell_px"]
    dx, dy = state["pan"]
    px = ox + gx * cell_px + dx
    py = oy + (state["rows"] - 1 - gy) * cell_px + dy
    return px, py


def px_to_cell(mx, my):
    ox, oy = state["origin_px"]
    cell_px = state["cell_px"]
    dx, dy = state["pan"]
    gx = (mx - ox - dx) // cell_px
    gy = state["rows"] - 1 - (my - oy - dy) // cell_px
    return int(gx), int(gy)


def grid_extent_px():
    """格子「視窗」(不是內容總範圍)的像素矩形——大小固定在window_dims(),
    平移只改變視窗裡看到內容的哪個部分,不改變視窗本身大小/位置。"""
    ox, oy = state["origin_px"]
    window_cols, window_rows = window_dims()
    x1 = ox + window_cols * state["cell_px"]
    y1 = oy + window_rows * state["cell_px"]
    return ox, oy, x1, y1


def panel_extent_px():
    """回傳整個介面(格子視窗+四周座標數字+外圍+按鈕)的外框像素矩形
    (x0, y0, x1, y1)——比grid_extent_px()大一圈,用來畫「外面再套一層
    外框」的視覺邊界。PANEL_*_MARGIN是「邏輯」像素值(跟DEFAULT_CELL_PX
    一樣),這裡統一乘上ui_scale()才是實際畫面上要留的邊距。"""
    x0, y0, x1, y1 = grid_extent_px()
    scale = ui_scale()
    return (
        x0 - PANEL_LEFT_MARGIN * scale,
        y0 - PANEL_BOTTOM_MARGIN * scale,
        x1 + PANEL_RIGHT_MARGIN * scale,
        y1 + PANEL_TOP_MARGIN * scale,
    )


def begin_pan(mx, my):
    state["panning"] = True
    state["pan_anchor"] = (mx, my, state["pan"][0], state["pan"][1])


def update_pan(mx, my):
    """拖曳空白處平移:內容跟著滑鼠1:1移動(像抓著畫布拖),而不是滑鼠移動
    量映射到反方向——這是「拖曳畫布本身」而非「拖曳scrollbar滑塊」的
    慣例。超出_pan_bounds()允許範圍的部分會被夾限,格子總數沒超過視窗
    大小時範圍是(0,0)~(0,0),等同完全不會動。"""
    if state["pan_anchor"] is None:
        return
    anchor_mx, anchor_my, start_dx, start_dy = state["pan_anchor"]
    min_dx, min_dy = _pan_bounds()
    new_dx = start_dx + (mx - anchor_mx)
    new_dy = start_dy + (my - anchor_my)
    state["pan"] = [max(min_dx, min(0.0, new_dx)), max(min_dy, min(0.0, new_dy))]


def end_pan():
    state["panning"] = False
    state["pan_anchor"] = None


def plus_button_positions():
    """回傳「+」熱區的(direction, center_x, center_y)。只提供右邊/下面——
    (0,0)固定在左上角當座標原點,往右/往下擴充不會動到任何既有item座標。
    位置錨定在「格子視窗」邊緣,不是內容總範圍邊緣——格子數超過視窗大小、
    平移到別的位置時,按鈕仍固定顯示在視窗邊上,點了永遠是在目前總格子數
    上再加一欄/一列(不受平移影響)。PLUS_HIT_SIZE是邏輯像素值,這裡乘上
    ui_scale()才是實際畫面座標,跟plus_button_at()命中判斷用的縮放一致。"""
    x0, y0, x1, y1 = grid_extent_px()
    mid_x = (x0 + x1) / 2
    mid_y = (y0 + y1) / 2
    hit = PLUS_HIT_SIZE * ui_scale()
    return [
        ("RIGHT", x1 + hit * 1.5, mid_y),
        ("DOWN", mid_x, y0 - hit * 1.5),
    ]


def plus_button_at(mx, my):
    hit = PLUS_HIT_SIZE * ui_scale()
    for direction, cx, cy in plus_button_positions():
        if abs(mx - cx) <= hit and abs(my - cy) <= hit:
            return direction
    return None


def expand_grid(direction):
    """新增一欄/一列之後,主動把畫面捲到能看到新增那一格的位置——不然格子
    數超過視窗大小(DEFAULT_GRID_CELLS)時,新增的那一格預設會落在視窗外,
    使用者點了+按鈕卻看不到任何變化,很難判斷有沒有真的新增成功。

    x軸(欄)跟y軸(列)的公式方向不對稱,所以「捲到底」在兩個軸上對應
    pan的相反端點:cell_to_px的y公式用(rows-1-gy)反過來算,新增的列
    永遠排在最下面,而pan的上界(0.0)天生就對應「內容下緣貼齊視窗下緣」
    ——新增列之後只要pan維持在0.0,新列自然可見,所以往下新增只需要把
    dy釘回0.0(這裡明確賦值,不是靠「使用者剛好沒手動捲過」這個偶然條件
    才成立)。x公式則是gx直接對應像素、不反轉,新增的欄同樣排在最右邊,
    但pan的上界(0.0)這時對應的是「內容左緣貼齊視窗左緣」——新增欄後
    如果不特地處理,pan維持在0.0只會讓視窗依然對齊最左邊的舊欄,新欄
    落在視窗右側之外被裁掉,所以往右新增要把dx捲到*下界*(_pan_bounds()
    的最小值),讓內容右緣(含新欄)貼齊視窗右緣。"""
    if state["cols"] >= MAX_GRID_SIZE and direction == 'RIGHT':
        return
    if state["rows"] >= MAX_GRID_SIZE and direction == 'DOWN':
        return
    if direction == 'RIGHT':
        state["cols"] += 1
        state["pan"][0] = _pan_bounds()[0]
    elif direction == 'DOWN':
        state["rows"] += 1
        state["pan"][1] = 0.0
    _clamp_pan()


def _draw_quad(shader, px, py, color, w, h):
    quad = [(px, py), (px + w, py), (px + w, py + h), (px, py + h)]
    indices = [(0, 1, 2), (2, 3, 0)]
    batch = batch_for_shader(shader, 'TRIS', {"pos": quad}, indices=indices)
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw_quad_outline(shader, px, py, w, h, color, width=2.0):
    gpu.state.line_width_set(width)
    lines = [
        (px, py), (px + w, py),
        (px + w, py), (px + w, py + h),
        (px + w, py + h), (px, py + h),
        (px, py + h), (px, py),
    ]
    batch = batch_for_shader(shader, 'LINES', {"pos": lines})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.line_width_set(1.0)


def _draw_text(text, x, y, size=14, color=(1, 1, 1, 1), center=False):
    font_id = 0
    blf.size(font_id, size)
    if center:
        w, h = blf.dimensions(font_id, text)
        x -= w / 2
        y -= h / 2
    blf.color(font_id, *color)
    blf.position(font_id, x, y, 0)
    blf.draw(font_id, text)


def _text_width(text, size):
    """量測文字在指定字級下的寬度,用來把提示文字緊接在標題文字右邊——
    不能寫死一個固定間距,標題文字內容/字級任何一個變動,寬度就會跟著變。"""
    font_id = 0
    blf.size(font_id, size)
    w, _ = blf.dimensions(font_id, text)
    return w


def _draw_circle(shader, cx, cy, radius, color, segments=24):
    verts = [(cx, cy)]
    for i in range(segments + 1):
        angle = 2.0 * math.pi * i / segments
        verts.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    batch = batch_for_shader(shader, 'TRI_FAN', {"pos": verts})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw_line(shader, x0, y0, x1, y1, color, width=1.0):
    gpu.state.line_width_set(width)
    batch = batch_for_shader(shader, 'LINES', {"pos": [(x0, y0), (x1, y1)]})
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.line_width_set(1.0)


def _draw_item_icon(shader, item, px, py, w, h):
    """在控制器「本體」矩形(px, py, w, h,不含標籤格)內畫簡易控制器圖示:
    軌道(細長矩形)+圓形把手。方向依control_style——直向樣式畫直的軌道、
    橫向樣式畫橫的,跟實際生成的Track旋轉方向一致,讓使用者在畫布上一眼
    就能分辨每個方塊是哪種控制器。XY_2D(以及任何未來未知樣式)沿用
    else分支的「內縮方框+十字線+中央把手」2D pad圖示——這是刻意共用,
    不是忘記加分支:XY_2D實際生成的Track就是正方形外框、Handle可以在
    平面上自由拖拽,這個圖示本來就正確對應它的行為,不需要另外畫一份。
    純裝飾,不參與點擊/拖曳的命中判斷(那些仍然用_item_full_rect_at的
    完整矩形)。TEXT_LABEL不會呼叫到這裡——它在draw_callback主迴圈裡
    是獨立分支,整個本體矩形直接置中畫大字級的名稱,不需要任何圖示。"""
    cx = px + w / 2
    cy = py + h / 2
    cell_px = state["cell_px"]
    track_color = (0.0, 0.0, 0.0, 0.35)
    track_outline = (1.0, 1.0, 1.0, 0.35)
    handle_color = (0.95, 0.95, 0.95, 1.0)
    handle_radius = cell_px * 0.13

    if item.control_style == 'LINEAR_1D_HORIZONTAL':
        track_w, track_h = w * 0.5, cell_px * 0.16
    elif item.control_style == 'LINEAR_1D':
        track_w, track_h = cell_px * 0.16, h * 0.5
    else:
        pad = min(w, h) * 0.26
        _draw_quad_outline(shader, cx - pad, cy - pad, pad * 2, pad * 2, track_outline)
        _draw_line(shader, cx - pad, cy, cx + pad, cy, track_outline)
        _draw_line(shader, cx, cy - pad, cx, cy + pad, track_outline)
        _draw_circle(shader, cx, cy, handle_radius, handle_color)
        return

    tx, ty = cx - track_w / 2, cy - track_h / 2
    _draw_quad(shader, tx, ty, track_color, track_w, track_h)
    _draw_quad_outline(shader, tx, ty, track_w, track_h, track_outline, width=1.0)
    _draw_circle(shader, cx, cy, handle_radius, handle_color)
    _draw_circle(shader, cx, cy, handle_radius * 0.55, (0.25, 0.35, 0.55, 1.0))


def _rect_from_cells(gx, gy, width_cells, height_cells):
    """把「左上角錨點格+寬高格數」轉成畫布像素矩形(px, py, w, h)。
    cell_to_px回傳的是(gx, gy)這一格的左下角,但佔多格高時y方向要往下
    多算(height_cells - 1)格,因為grid_y是左上角錨點、po是靠grid_y那一列
    的左下角換算出來的位置,再往下疊(height_cells-1)格才是整個footprint
    的左下角。抽成獨立函式,因為控制器本體矩形和含標籤格的完整矩形都要
    用同一套換算,只是傳入的錨點/格數不同。"""
    px, py = cell_to_px(gx, gy)
    cell_px = state["cell_px"]
    py -= (height_cells - 1) * cell_px
    return px, py, width_cells * cell_px, height_cells * cell_px


def _item_full_rect_at(item, gx, gy):
    """回傳「假設item錨點在(gx, gy)」時的完整footprint像素矩形——單一
    矩形,show_label開啟時直接整塊變高一格(不額外分成本體/標籤兩層)。
    跟grid_layout.occupied_cells_at用的是同一套格數規則(cells_for),
    滑鼠點擊命中/拖曳判斷/繪製都用這一個矩形,確保畫面看到的範圍跟
    實際的衝突判斷完全一致。"""
    width_cells, height_cells = cells_for(item.control_style, item.show_label)
    return _rect_from_cells(gx, gy, width_cells, height_cells)


def _item_body_rect_at(item, gx, gy):
    """回傳「假設item錨點在(gx, gy)」時控制器「本體」的像素矩形——不含
    show_label多佔的標籤格。標籤格固定佔最上面那一列(grid_y本身),開啟
    標籤時本體從gy+1起算(跟grid_layout.occupied_cells/cell_center_local_xy
    對「本體從哪裡開始」的認知一致)。只用於繪製圖示/名稱的定位,命中
    判斷仍用_item_full_rect_at的完整矩形。"""
    width_cells, height_cells = CONTROL_STYLE_CELLS.get(item.control_style, (1, 1))
    body_gy = gy + 1 if item.show_label else gy
    return _rect_from_cells(gx, body_gy, width_cells, height_cells)


def item_rect_at(context, mx, my):
    """回傳滑鼠位置(mx, my)落在目前group哪個item的佔用範圍內(沒有就None)。
    比對每個item「含標籤格」的完整像素矩形,而不是只看控制器本體或單一
    格子——標籤格雖然視覺上畫得比較淡,但仍然是這個item可以被點擊/拖曳
    命中的範圍,不然使用者點在標籤格上會誤以為點到空白處。"""
    for item in _group_items(context):
        px, py, w, h = _item_full_rect_at(item, item.grid_x, item.grid_y)
        if px <= mx <= px + w and py <= my <= py + h:
            return item
    return None


def in_grid_window(mx, my):
    """判斷滑鼠是否落在格子視窗範圍內(用來判定「空白處拖曳=平移畫布」
    的合法起點——只有視窗裡、且沒點到任何item/按鈕的空白處才算)。"""
    x0, y0, x1, y1 = grid_extent_px()
    return x0 <= mx <= x1 and y0 <= my <= y1


def draw_callback():
    # 不接收/依賴呼叫端傳入的context快照——draw_handler_add的callback
    # 每次實際繪製時,region/area都可能已經跟invoke()當下不同(使用者
    # 拖動分割視窗、切換area等),必須每次都用bpy.context現抓當下的,
    # 不能凍結成參數傳進來。
    context = bpy.context
    region = context.region
    if region is not None:
        update_origin(region.width, region.height)

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')

    x0, y0, x1, y1 = grid_extent_px()
    cell_px = state["cell_px"]

    # 外層面板:整個介面(格子視窗+座標數字+按鈕)套一層半透明底色跟外框,
    # 讓使用者一眼看出這是一塊獨立的浮動編輯面板,不是散落在viewport上的
    # 零件。畫在格子視窗本體之前,視窗自己的底色/邊框蓋在上面。
    panel_x0, panel_y0, panel_x1, panel_y1 = panel_extent_px()
    _draw_quad(shader, panel_x0, panel_y0, (0.08, 0.08, 0.08, 0.85),
               panel_x1 - panel_x0, panel_y1 - panel_y0)
    _draw_quad_outline(shader, panel_x0, panel_y0, panel_x1 - panel_x0, panel_y1 - panel_y0,
                        (0.75, 0.75, 0.75, 0.9), width=2.0)

    # 標題列畫在面板外框的「外面」(上方),不佔用面板內部的留白/範圍——
    # 「編輯排版」貼齊面板左邊,「點擊右鍵或ESC離開」貼齊面板右邊,各自
    # 對齊自己那一側。這個模態編輯狀態疊在3D Viewport上,沒有其他UI線索
    # 告訴使用者要怎麼結束,右鍵/ESC雖然是Blender modal operator的通用
    # 慣例,但不寫出來還是容易讓人卡住不知道怎麼跳出。
    scale = ui_scale()
    title_size = TITLE_SIZE * scale
    hint_size = HINT_SIZE * scale
    title_y = panel_y1 + TITLE_GAP * scale
    _draw_text(TITLE_TEXT, panel_x0, title_y, size=title_size, color=(1.0, 1.0, 1.0, 1.0))
    hint_w = _text_width(HINT_TEXT, hint_size)
    _draw_text(HINT_TEXT, panel_x1 - hint_w, title_y,
               size=hint_size, color=(0.75, 0.75, 0.75, 0.9))

    # 不透明底色,避免看穿3D場景干擾判斷格子狀態
    _draw_quad(shader, x0, y0, (0.12, 0.12, 0.12, 1.0), x1 - x0, y1 - y0)

    # 格子總數(state["cols"]/["rows"])可能超過目前視窗看得到的範圍(平移
    # 中,或還沒平移過去),網格線/item都要裁掉超出視窗的部分,不能畫出
    # 視窗外蓋住旁邊的座標數字/按鈕/縮放滑塊——用scissor test裁剪,裁剪
    # 範圍就是視窗本身(格子視窗的座標系統本來就跟這個draw callback用的
    # 是同一套region像素座標,不需要額外轉換)。
    gpu.state.scissor_test_set(True)
    gpu.state.scissor_set(int(x0), int(y0), max(1, int(x1 - x0)), max(1, int(y1 - y0)))

    # 網格細線(用cell_to_px的同一套pan偏移量,手動展開成跟cell_to_px一致
    # 的算式,避免每條線都呼叫一次函式)
    dx, dy = state["pan"]
    lines = []
    for col in range(state["cols"] + 1):
        x = state["origin_px"][0] + col * cell_px + dx
        lines.append((x, y0))
        lines.append((x, y1))
    for row in range(state["rows"] + 1):
        y = state["origin_px"][1] + row * cell_px + dy
        lines.append((x0, y))
        lines.append((x1, y))
    batch = batch_for_shader(shader, 'LINES', {"pos": lines})
    shader.bind()
    shader.uniform_float("color", (0.55, 0.55, 0.55, 1.0))
    batch.draw(shader)

    group_items = _group_items(context)

    # 拖曳中:目的地「完整footprint」(含標籤格)預覽反白——已被佔用
    # (放開會跟對方互換)用黃色、空格(放開直接移入)用綠色。用
    # items_overlapping_at檢查拖曳中item移到(gx, gy)後是否跟別人重疊,
    # 不能只查滑鼠落點單一格——2x1/1x2這類多格item的另一半,或是
    # show_label多出的標籤格,都要算進預覽範圍,否則畫面顯示的範圍會
    # 跟實際RELEASE時的判斷不一致。
    if state["dragging"] is not None and state["drag_target"] is not None:
        dragged = state["dragging"]
        gx, gy = state["drag_target"]
        occupant = bool(items_overlapping_at(group_items, dragged, gx, gy))
        preview_color = (0.9, 0.8, 0.2, 0.45) if occupant else (0.2, 0.9, 0.3, 0.45)
        px, py, w, h = _item_full_rect_at(dragged, gx, gy)
        _draw_quad(shader, px, py, preview_color, w, h)

    # 既存資料裡已經重疊的item(不是拖曳造成的,例如切換show_label讓某個
    # item長高一格而壓到鄰居)也要在畫布上標示出來。之前畫布只在拖曳當下
    # 檢查衝突,靜態顯示完全不檢查,導致畫面看起來正常、但按生成卻報
    # 「格子座標衝突」,兩邊說法不一致(真實bug,使用者回報)。用
    # occupied_cells(跟operators.generate()的find_grid_conflicts同一套
    # 邏輯)確保畫布跟後端判斷永遠一致。
    overlapping_ids = set()
    for i in range(len(group_items)):
        for j in range(i + 1, len(group_items)):
            a, b = group_items[i], group_items[j]
            # 拖曳中的item位置還沒寫回grid_x/grid_y,靜態重疊檢查會拿到
            # 它的舊座標而誤判,拖曳中的預覽色本來就另外處理,直接跳過。
            if same_item(state["dragging"], a) or same_item(state["dragging"], b):
                continue
            if occupied_cells(a) & occupied_cells(b):
                overlapping_ids.add(a.as_pointer())
                overlapping_ids.add(b.as_pointer())

    # 每個item:標籤格(淡色,只在show_label開啟時畫)+ 控制器本體(實色)+
    # 名稱文字。正在拖曳中的item要畫在state["drag_target"](滑鼠當前對應
    # 的新位置),不是它自己的item.grid_x/grid_y——後者是資料庫裡還沒寫入
    # 的舊位置,拖曳過程中還沒變。
    for item in group_items:
        # 不能用`state["dragging"] is item`——group_items是每次draw重新從
        # collection取出的新wrapper,is永遠False,拖曳中的item會被當成一般
        # item畫在舊位置,跟畫在新位置的預覽色矩形部分重疊,產生斷裂畫面。
        is_dragging_this = same_item(state["dragging"], item)
        if is_dragging_this and state["drag_target"] is not None:
            gx, gy = state["drag_target"]
        else:
            gx, gy = item.grid_x, item.grid_y

        # 佔用範圍(命中/衝突判斷)仍然是含標籤格的單一完整矩形,跟
        # _item_full_rect_at/occupied_cells_at同一套格數規則;但繪製上
        # 在裡面分層畫:底色鋪滿完整矩形,標籤格畫一條分隔線+名稱文字,
        # 本體格畫簡易控制器圖示(_draw_item_icon)。
        px, py, w, h = _item_full_rect_at(item, gx, gy)
        is_overlapping = item.as_pointer() in overlapping_ids
        if is_dragging_this:
            color = (0.5, 0.5, 0.9, 0.6)
            outline_color = (1.0, 1.0, 1.0, 1.0)
        elif is_overlapping:
            # 紅色警示:這個item目前跟別人重疊,生成時會被擋下
            color = (0.9, 0.25, 0.25, 0.85)
            outline_color = (1.0, 0.4, 0.4, 1.0)
        elif item.control_style == 'TEXT_LABEL':
            # 純文字沒有可拖拽的控制器本體,用綠色跟其他有Track/Handle的
            # 樣式(藍色)區隔,方便使用者在排版畫布上一眼認出哪些格子
            # 只是純文字、不是真正的滑桿。
            color = (0.3, 0.75, 0.35, 1.0)
            outline_color = (1.0, 1.0, 1.0, 0.4)
        else:
            color = (0.3, 0.5, 0.9, 1.0)
            outline_color = (1.0, 1.0, 1.0, 0.4)
        _draw_quad(shader, px, py, color, w, h)
        _draw_quad_outline(shader, px, py, w, h, outline_color)

        bx, by, bw, bh = _item_body_rect_at(item, gx, gy)
        # 名稱文字大小跟著cell_px走(不是寫死的像素值)——DEFAULT_CELL_PX
        # 從48改成固定96之後,原本調校好的11~13px字級相對格子big了一倍,
        # 看起來明顯偏小,所以改成比例算,格子再變大/變小時字級也會跟著
        # 縮放,不會再需要手動重調。
        name_font_size = max(12, round(cell_px * 0.16))

        if item.control_style == 'TEXT_LABEL':
            # 純文字沒有Track/Handle圖示可畫(不像其他樣式還需要在本體
            # 矩形裡擠出空間放圖示),整個本體矩形都拿來置中顯示名稱就好,
            # 字級也比其他樣式的名稱標籤大一點(0.2倍cell_px,其他樣式是
            # 0.16倍),因為文字本身就是這個item唯一要呈現的內容,不需要
            # 替圖示留位置或省字級空間。
            text_size = max(12, round(cell_px * 0.2))
            _draw_text(item.name, bx + bw / 2, by + bh / 2,
                       size=text_size, color=(1.0, 1.0, 1.0, 1.0), center=True)
        elif item.show_label:
            # 有獨立的標籤格:本體圖示佔滿整個本體矩形,標籤格畫一條淡
            # 分隔線區隔+名稱置中——跟實際生成結果(標籤文字在控制器上方)
            # 的相對位置一致。
            _draw_item_icon(shader, item, bx, by, bw, bh)
            _draw_line(shader, px, by + bh, px + w, by + bh, (1.0, 1.0, 1.0, 0.25))
            _draw_text(item.name, px + w / 2, by + bh + cell_px / 2,
                       size=name_font_size, color=(1.0, 1.0, 1.0, 1.0), center=True)
        else:
            # 沒開標籤:本體矩形裡沒有另外保留的標籤格,把控制器圖示縮小、
            # 往上靠在本體矩形的上半部,空出下緣一小段來放大字的名稱——
            # 名稱固定貼底,不會跟圖示的把手/十字線擠在一起。
            text_strip_h = name_font_size + 6
            icon_bh = max(1.0, bh - text_strip_h)
            _draw_item_icon(shader, item, bx, by + text_strip_h, bw, icon_bh)
            _draw_text(item.name, px + w / 2, by + text_strip_h / 2,
                       size=name_font_size, color=(1.0, 1.0, 1.0, 1.0), center=True)

    gpu.state.scissor_test_set(False)

    # 外框(視窗邊界,不是內容總範圍)——裁剪範圍之外畫,邊線本身不需要
    # 也不應該被裁掉。
    frame_lines = [(x0, y0), (x1, y0), (x1, y0), (x1, y1), (x1, y1), (x0, y1), (x0, y1), (x0, y0)]
    batch = batch_for_shader(shader, 'LINES', {"pos": frame_lines})
    shader.bind()
    shader.uniform_float("color", (1.0, 0.6, 0.0, 1.0))
    batch.draw(shader)

    # 座標數字:col在上緣、row在左緣,每5格標示一次,位置隨pan偏移一起
    # 移動——只畫落在目前視窗x/y範圍內的,超出視窗的數字本來就看不到
    # 對應的格子,不畫出來避免數字擠在面板邊界外側。offset/字級都是邏輯
    # 像素值,乘上scale(跟上面title/hint文字用同一個ui_scale()結果)。
    coord_offset = 18 * scale
    coord_size = 13 * scale
    for col in range(0, state["cols"] + 1, 5):
        x = state["origin_px"][0] + col * cell_px + dx
        if x0 - 1 <= x <= x1 + 1:
            _draw_text(str(col), x, y1 + coord_offset, size=coord_size,
                       color=(0.85, 0.85, 0.85, 1.0), center=True)
    for row in range(0, state["rows"] + 1, 5):
        y = state["origin_px"][1] + (state["rows"] - row) * cell_px + dy
        if y0 - 1 <= y <= y1 + 1:
            _draw_text(str(row), x0 - coord_offset, y, size=coord_size,
                       color=(0.85, 0.85, 0.85, 1.0), center=True)

    # 右邊/下面「+」擴充按鈕
    plus_size = 20 * scale
    for direction, cx, cy in plus_button_positions():
        _draw_text("+", cx, cy, size=plus_size, color=(1.0, 0.6, 0.0, 1.0), center=True)

    gpu.state.blend_set('NONE')
