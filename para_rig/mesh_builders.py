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
# 避免文字緊貼著Track外框
LABEL_GAP = -0.08

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


def _fill_ring_mesh(mesh, half_along, half_across, border, along_idx, across_idx):
    """把mesh填成一個扁平的矩形外框(方形圈環),躺在along_idx/across_idx構成的平面上,
    第三軸(深度)恆為0,呈現2D線框的視覺效果。以(0,0)為中心對稱建構。"""
    _fill_ring_mesh_asym(
        mesh, -half_along, half_along, -half_across, half_across,
        border, along_idx, across_idx,
    )


def _fill_ring_mesh_asym(mesh, min_along, max_along, min_across, max_across,
                          border, along_idx, across_idx):
    """跟_fill_ring_mesh一樣是扁平矩形外框,但四個邊界各自獨立指定,不假設
    以(0,0)為中心對稱——目前只有Frame會用到(見rig_builder.update_frame_mesh/
    create_slider_frame),因為Frame的內容(Track/Handle/Label)可能不對稱
    分布:標籤那一側的留白(LABEL_SIDE_MARGIN)刻意比其他側(FRAME_MARGIN)
    小,Frame的局部原點(0,0)因此不再是mesh本身的幾何中心,但仍然是
    grid_layout.cell_center_local_xy()置中Track的基準,兩者互不影響。"""
    bm = bmesh.new()

    def vec(along, across):
        v = [0.0, 0.0, 0.0]
        v[along_idx] = along
        v[across_idx] = across
        return v

    outer = [bm.verts.new(vec(a, c)) for a, c in (
        (min_along, min_across), (max_along, min_across),
        (max_along, max_across), (min_along, max_across),
    )]
    inner = [bm.verts.new(vec(a, c)) for a, c in (
        (min_along + border, min_across + border), (max_along - border, min_across + border),
        (max_along - border, max_across - border), (min_along + border, max_across - border),
    )]
    for i in range(4):
        j = (i + 1) % 4
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


def _ensure_track_mesh():
    """回傳滑桿軌道的長條「外框」mesh data(2D線框風格),所有滑桿共用同一份
    (拖拽方向固定沿Track自己的局部Y軸,不再有多軸向需要分別快取)。"""
    return _get_or_build_mesh(
        "SliderTrackData",
        lambda mesh: _fill_ring_mesh(
            mesh, TRACK_LENGTH / 2, TRACK_WIDTH / 2, TRACK_OUTLINE_THICKNESS,
            AXIS_IDX['Y'], AXIS_IDX['X'],
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
            AXIS_IDX['Y'], AXIS_IDX['X'],
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
