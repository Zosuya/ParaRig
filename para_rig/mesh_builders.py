"""扁平2D風格滑桿視覺元件的幾何常數與bmesh生成函式。

這裡的東西都不碰bpy.types(沒有PropertyGroup/Operator/Panel),純粹是「給定尺寸
參數,回傳/填入一份mesh data」的工具函式,operators.py在生成Track/Handle/Frame
物件時呼叫。
"""

import math
import bpy
import bmesh

# SLIDER_TRAVEL是滑桿視覺尺寸的基準單位(米),用來定Track/Frame等的大小比例。
# 實際Handle可拖拽的距離是HANDLE_TRAVEL(見下方),兩者故意分開:如果Handle能拖拽
# 的距離跟SLIDER_TRAVEL一樣大,Handle在極限位置時「中心距離+半徑」會超出Track本
# 身的長度端點(跑出長方形外框外面);HANDLE_TRAVEL刻意抓小一點,確保Handle+半徑
# 在兩端都還留在Track的長方形範圍內,不會超框。
SLIDER_TRAVEL = 0.1

# 1軸滑桿樣式的視覺尺寸:扁平2D風格,Track是長方形外框、Handle是實心圓盤,
# 都是躺在一個平面上的零厚度mesh(取代舊版立體icosphere+長方體)。
TRACK_LENGTH = SLIDER_TRAVEL * 2.3        # 軌道外框的全長,略長於2*SLIDER_TRAVEL讓兩端露出把手外
TRACK_OUTLINE_THICKNESS = SLIDER_TRAVEL * 0.05  # 軌道外框線本身的粗細
HANDLE_RADIUS = SLIDER_TRAVEL * 0.3       # 把手圓盤半徑
TRACK_WIDTH = HANDLE_RADIUS * 3.4         # 軌道外框的截面寬度,要明顯比Handle直徑(2*HANDLE_RADIUS)
                                            # 寬,確保圓形把手完整被框住且兩側留有可見的邊界留白
# 軌道外框的圓角半徑——只是「加一點圓角」的視覺調整,不是完全的膠囊/藥丸
# 造型(那樣半徑要等於TRACK_WIDTH/2,兩端會變成半圓)。實際生成時會被
# _rounded_rect_points()自動夾限到不超過短邊的一半,不會因為跟TRACK_LENGTH/
# PAD_SIZE的比例算錯而爆出異常形狀。
TRACK_CORNER_RADIUS = TRACK_WIDTH * 0.3

# Handle實際可拖拽的距離(兩端分別對應min_val/max_val),刻意比SLIDER_TRAVEL小,
# 確保Handle+HANDLE_RADIUS的極限位置不會超出TRACK_LENGTH/2
HANDLE_TRAVEL = SLIDER_TRAVEL * 0.7

# 外框(Frame,群組容器)的視覺尺寸
FRAME_MARGIN = SLIDER_TRAVEL * 0.4         # 外框內緣與最外側滑桿軌道之間的留白
# 標籤那一側的留白刻意比FRAME_MARGIN小——文字本身視覺上已經比控制器輪廓
# 稀疏,不需要跟純控制器那幾側一樣寬的緩衝,見rig_builder.measure_group_extent
# 對四邊分別套用哪一個margin的判斷邏輯。
LABEL_SIDE_MARGIN = SLIDER_TRAVEL * 0.2
FRAME_BORDER_THICKNESS = SLIDER_TRAVEL * 0.1  # 外框邊線的粗細
# Frame外框的圓角半徑,跟TRACK_CORNER_RADIUS同樣是「加一點圓角」的視覺調整
# ——刻意用跟TRACK_CORNER_RADIUS相近的絕對值(SLIDER_TRAVEL*0.3)而不是
# 依Frame自己的尺寸算比例,讓Track跟Frame的圓角視覺弧度一致,不會因為
# Frame通常比Track大很多而顯得比例失調。Frame的extent是動態量測出來的
# (見measure_group_extent),不是固定尺寸,所以一律靠_rounded_rect_points
# 內部的夾限保證不會超出Frame實際大小,即使只有單一個小滑桿的極小Frame
# 也不會出現圓角互相重疊或超框的異常形狀。
FRAME_CORNER_RADIUS = SLIDER_TRAVEL * 0.3
# show_frame關閉時,畫在Frame內容範圍左上角的原點標記小圓點半徑。
# show_frame=False會讓Frame的mesh完全沒有geometry,viewport的GPU picking
# 沒有東西可畫,結果是這個Frame在3D視圖裡點不到也框不到,只能從Outliner
# 或Shift+G選父層繞過去(使用者回報的互動缺陷)——這個小圓點就是「至少
# 留一點可以點得到的幾何體」的最小解法,不是裝飾。
# 取HANDLE_RADIUS的一半:夠小不干擾畫面(Handle圓盤本身已經是控制器裡
# 最小的視覺元素之一),但仍然點得到。刻意用HANDLE_RADIUS的比例而不是
# SLIDER_TRAVEL,是為了讓標記跟Handle的大小關係固定,調整Handle尺寸時
# 標記會等比例跟著走。
FRAME_ORIGIN_MARKER_RADIUS = HANDLE_RADIUS * 0.5

# grid_layout.py用的固定格子物理尺寸(一格的寬/高,米):約等於目前相鄰控制器
# 中心點之間的間距(TRACK_WIDTH,即控制器截面寬度,加上FRAME_MARGIN當左右
# 留白),讓佔用格數系統算出來的排版跟改版前的視覺比例接近,不用重新調整
# 使用者已經習慣的密度。
CELL_SIZE = TRACK_WIDTH + FRAME_MARGIN

# XY_2D(2軸拖拽板)樣式的視覺尺寸:佔用grid_layout.CONTROL_STYLE_CELLS裡
# 2x2格的footprint,套用跟1D Track(TRACK_WIDTH = CELL_SIZE - FRAME_MARGIN,
# 1格寬扣一份留白)同樣的比例邏輯——2格寬扣一份留白,而不是扣兩份,因為
# 這份margin是「外框到最外側邊」的留白,不是每一格各自留一份。
PAD_SIZE = 2 * CELL_SIZE - FRAME_MARGIN
# Handle在pad上可拖拽的距離(X/Y兩軸共用同一個值,pad是正方形),乘0.9是
# 刻意抓小一點,比照HANDLE_TRAVEL「確保Handle+半徑不超框」的設計精神。
PAD_TRAVEL = (PAD_SIZE / 2 - HANDLE_RADIUS) * 0.9

# 名稱標籤(Text Mesh)與Track頂端(+Y方向,固定拖拽軸的正向)之間的間距,
# 避免文字緊貼著Track外框。從-0.08調整為-0.03(往外/上多推一點)——
# 使用者要求所有控制器的名稱標籤統一往上調整一點空間,原本的間距會讓
# 文字壓到Track外框上緣。
LABEL_GAP = -0.03

# 估算標籤文字實際佔用的高度:Text物件的curve.size大致對應字高,但實際
# render出來的bounding box會因字型/內容略有出入,乘一個略大於1的係數當
# 保守估計,用於Frame尺寸計算(見operators.generate()),避免文字貼著或
# 超出外框邊緣。
LABEL_HEIGHT_FACTOR = 1.2

# 分組名稱標籤(Text Mesh)固定顯示在Frame外框正上方,位置基準是Frame的
# 真實量測範圍(rig_builder.measure_group_extent()算出來、已經加過margin
# 的extent),不是格子系統——這裡只是「量測到的上緣」再往外推的固定間距,
# 跟LABEL_GAP(滑桿標籤用,基準是格子系統的CELL_SIZE)是兩個獨立的知。
GROUP_LABEL_GAP = SLIDER_TRAVEL * 0.3
# 分組名稱文字大小(per-group可調,見properties.SliderGroupItem.
# name_label_size/name_label_size_raw)曾經是這裡的固定常數GROUP_LABEL_SIZE
# =0.06,使用者要求改成可調整之後,0.06變成該欄位的預設值,不再是共用常數。

AXIS_IDX = {'X': 0, 'Y': 1, 'Z': 2}


def _get_or_build_mesh(name, build_fn):
    """回傳快取的mesh data(用bpy.data.meshes的名稱當key);不存在才呼叫build_fn建立內容。"""
    mesh = bpy.data.meshes.get(name)
    if mesh is not None:
        return mesh
    mesh = bpy.data.meshes.new(name)
    build_fn(mesh)
    return mesh


def _rounded_rect_points(min_along, max_along, min_across, max_across, radius, segments_per_corner=6):
    """回傳沿著圓角矩形邊界一圈的(along, across)點,依逆時鐘方向從「右下角
    圓弧起點」開始,依序繞過右下→右上→左上→左下四個圓角銜接回原點。

    radius會自動夾限到不超過矩形短邊的一半(max(0.0, min(radius, half_along,
    half_across))),避免圓弧互相重疊或超出矩形本身範圍——夾限到0時,四段
    圓弧各自收斂成單一個點(剛好是原本的直角頂點),不需要另外分支處理
    「半徑為0」的銳角矩形情況,呼叫端(_fill_ring_mesh_asym)永遠可以假設
    回傳的是同一種「4*(segments_per_corner+1)個點」的等長清單。"""
    half_along = (max_along - min_along) / 2
    half_across = (max_across - min_across) / 2
    r = max(0.0, min(radius, half_along, half_across))

    # 四個圓角的圓心座標,以及各自的起訖角度(度)——起訖角度沿逆時鐘方向
    # 銜接,讓四段圓弧首尾相接剛好繞矩形一圈,不留縫隙也不重疊。
    corners = (
        (max_along - r, min_across + r, -90, 0),    # 右下
        (max_along - r, max_across - r, 0, 90),      # 右上
        (min_along + r, max_across - r, 90, 180),    # 左上
        (min_along + r, min_across + r, 180, 270),   # 左下
    )
    points = []
    for cx, cy, start_deg, end_deg in corners:
        for i in range(segments_per_corner + 1):
            t = i / segments_per_corner
            angle = math.radians(start_deg + (end_deg - start_deg) * t)
            points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return points


def _fill_ring_mesh(mesh, half_along, half_across, border, along_idx, across_idx, corner_radius=0.0):
    """把mesh填成一個扁平的矩形外框(方形圈環),躺在along_idx/across_idx構成的平面上,
    第三軸(深度)恆為0,呈現2D線框的視覺效果。以(0,0)為中心對稱建構。
    corner_radius>0時外框四個角改成圓角(見_rounded_rect_points),預設0
    維持原本的直角。"""
    _fill_ring_mesh_asym(
        mesh, -half_along, half_along, -half_across, half_across,
        border, along_idx, across_idx, corner_radius,
    )


def _fill_ring_mesh_asym(mesh, min_along, max_along, min_across, max_across,
                          border, along_idx, across_idx, corner_radius=0.0):
    """跟_fill_ring_mesh一樣是扁平矩形外框,但四個邊界各自獨立指定,不假設
    以(0,0)為中心對稱——目前只有Frame會用到(見rig_builder.update_frame_mesh/
    create_slider_frame),因為Frame的內容(Track/Handle/Label)可能不對稱
    分布:標籤那一側的留白(LABEL_SIDE_MARGIN)刻意比其他側(FRAME_MARGIN)
    小,Frame的局部原點(0,0)因此不再是mesh本身的幾何中心,但仍然是
    grid_layout.cell_center_local_xy()置中Track的基準,兩者互不影響。

    內圈(inner)用「外圈邊界各自往內縮border、圓角半徑也跟著縮小border」
    的方式算(min_along+border/max_along-border/...、corner_radius-border),
    這是圓角矩形做等距內縮(offset)的標準做法——border < corner_radius時
    內圈的角依然是圓的(半徑變小),border >= corner_radius時
    _rounded_rect_points內部的夾限會讓內圈的角自動收斂回直角,不會產生
    負半徑或形狀跑掉的問題。"""
    bm = bmesh.new()

    def vec(along, across):
        v = [0.0, 0.0, 0.0]
        v[along_idx] = along
        v[across_idx] = across
        return v

    if corner_radius <= 1e-9:
        # corner_radius關掉:維持原本4點直角矩形,不要走下面的
        # _rounded_rect_points——半徑0時該函式雖然數學上也能收斂出正確
        # 形狀,但每個角會產生segments_per_corner+1個重合在同一點的重複
        # 頂點,徒增mesh的頂點數(8個頂點會膨脹成56個,視覺上一樣但完全
        # 沒必要)。
        outer_pts = [
            (min_along, min_across), (max_along, min_across),
            (max_along, max_across), (min_along, max_across),
        ]
        inner_pts = [
            (min_along + border, min_across + border), (max_along - border, min_across + border),
            (max_along - border, max_across - border), (min_along + border, max_across - border),
        ]
    else:
        outer_pts = _rounded_rect_points(min_along, max_along, min_across, max_across, corner_radius)
        inner_pts = _rounded_rect_points(
            min_along + border, max_along - border, min_across + border, max_across - border,
            corner_radius - border,
        )
    outer = [bm.verts.new(vec(a, c)) for a, c in outer_pts]
    inner = [bm.verts.new(vec(a, c)) for a, c in inner_pts]
    n = len(outer)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((outer[i], outer[j], inner[j], inner[i]))
    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()


def _fill_disc_mesh(mesh, radius, a0_idx, a1_idx, segments=24):
    """把mesh填成一個扁平的實心圓盤,躺在a0_idx/a1_idx構成的平面上。"""
    bm = bmesh.new()
    verts = []
    for i in range(segments):
        angle = 2 * math.pi * i / segments
        v = [0.0, 0.0, 0.0]
        v[a0_idx] = radius * math.cos(angle)
        v[a1_idx] = radius * math.sin(angle)
        verts.append(bm.verts.new(v))
    bm.faces.new(verts)
    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()


def add_disc_to_mesh(mesh, radius, center_a0, center_a1, a0_idx, a1_idx, segments=16):
    """在既有mesh上「追加」一個扁平實心圓盤(圓心在center_a0/center_a1),
    不清空mesh原本的內容——跟_fill_disc_mesh()的差別有兩個:圓心可以不在
    原點,而且是append不是replace。

    給Frame的原點標記用(見rig_builder.frame_origin_marker_center/
    _fill_frame_mesh):標記要畫在Frame內容範圍的左上角,不是Frame自己的
    局部原點,所以需要能指定圓心;而Frame的mesh在show_frame=True時已經
    有外框的geometry,不能被清掉(雖然目前只在show_frame=False時才畫標記、
    兩者不會同時存在,但用append語意才不會讓「以後想同時畫」變成要重寫
    這個函式)。

    segments預設16而不是_fill_disc_mesh的24——這個標記的實際半徑只有
    Handle圓盤的一半,尺寸小到看不出多邊形邊數的差異,用不著那麼多頂點。"""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    verts = []
    for i in range(segments):
        angle = 2 * math.pi * i / segments
        v = [0.0, 0.0, 0.0]
        v[a0_idx] = center_a0 + radius * math.cos(angle)
        v[a1_idx] = center_a1 + radius * math.sin(angle)
        verts.append(bm.verts.new(v))
    bm.faces.new(verts)
    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()


def _ensure_track_mesh():
    """回傳滑桿軌道的長條「外框」mesh data(2D線框風格),所有滑桿共用同一份
    (拖拽方向固定沿Track自己的局部Y軸,不再有多軸向需要分別快取)。"""
    return _get_or_build_mesh(
        "SliderTrackData",
        lambda mesh: _fill_ring_mesh(
            mesh, TRACK_LENGTH / 2, TRACK_WIDTH / 2, TRACK_OUTLINE_THICKNESS,
            AXIS_IDX['Y'], AXIS_IDX['X'], TRACK_CORNER_RADIUS,
        ),
    )


def _ensure_pad_track_mesh():
    """回傳XY_2D樣式的軌道mesh data(2D線框風格的正方形外框),沿用跟1D
    Track一樣的_fill_ring_mesh helper,只是along/across半長相等(正方形,
    不像1D Track的along/across分別是TRACK_LENGTH/2、TRACK_WIDTH/2)。跟
    "SliderTrackData"是完全獨立的mesh data(不同形狀,不能共用快取key)。"""
    return _get_or_build_mesh(
        "SliderPadTrackData",
        lambda mesh: _fill_ring_mesh(
            mesh, PAD_SIZE / 2, PAD_SIZE / 2, TRACK_OUTLINE_THICKNESS,
            AXIS_IDX['Y'], AXIS_IDX['X'], TRACK_CORNER_RADIUS,
        ),
    )


def _ensure_empty_track_mesh():
    """回傳一份完全沒有geometry的空白mesh data,給TEXT_LABEL樣式的Track用——
    這個樣式沒有可拖拽的控制器本體,Track純粹只當文字物件的定位錨點,
    不需要畫出任何軌道外框。用_get_or_build_mesh共用快取(build_fn什麼都
    不做,mesh.new()出來的預設值本來就是空的),行為模式跟其他_ensure_*_mesh
    一致,方便_expected_track_mesh()統一用身分比對判斷要不要重建。"""
    return _get_or_build_mesh("SliderEmptyTrackData", lambda mesh: None)


def _ensure_handle_mesh():
    """回傳滑桿把手的實心圓盤mesh data(2D風格),所有滑桿共用同一份。
    Track/Handle都躺在局部XY平面上(深度軸固定是局部Z),因為拖拽方向固定
    是局部Y軸,不再需要依軸向分別快取不同平面的mesh。"""
    return _get_or_build_mesh(
        "SliderHandleData_Knob",
        lambda mesh: _fill_disc_mesh(mesh, HANDLE_RADIUS, AXIS_IDX['X'], AXIS_IDX['Y']),
    )
