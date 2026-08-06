"""生成/清除滑桿控制器與Driver的核心建構邏輯:建立/更新/移除Frame、Track、
Handle、Label物件,材質,Driver綁定。這裡不含任何Operator類別——operators.py
的SLIDERRIG_OT_generate/.clear()呼叫這裡的函式來做實際的物件操作。
"""

import math

import bpy
import mathutils

from .mesh_builders import (
    CELL_SIZE, FRAME_BORDER_THICKNESS, FRAME_CORNER_RADIUS,
    FRAME_ORIGIN_MARKER_RADIUS, LABEL_GAP,
    HANDLE_TRAVEL, PAD_TRAVEL, GROUP_LABEL_GAP,
    _ensure_track_mesh, _ensure_handle_mesh, _ensure_pad_track_mesh,
    _ensure_empty_track_mesh, _fill_ring_mesh_asym, add_disc_to_mesh,
)
from .grid_layout import CONTROL_STYLE_CELLS
from . import properties

# 所有生成物件(Frame/Track/Handle)統一放進這個Collection,
# 不要散落在使用者當下作用中的Collection裡
SLIDER_COLLECTION_NAME = "ParaRig"

SLIDER_UI_MATERIAL_NAME = "ParaRigUI"


def _resolve_driver_target_fields(target_type, target_object, data_name, bone_name, bone_axis):
    """核心解析邏輯,回傳(id_data, data_path, array_index)供driver_add使用;
    失敗回傳None。抽成接受明確欄位值的純函式(不直接讀binding),讓
    resolve_driver_target()(即時欄位)跟_resolve_bound_driver_target()
    (上一次實際綁定的快照欄位,見properties.TargetBinding.bound_target_type
    等欄位定義處的說明)可以共用同一套switch邏輯,不用維護兩份一樣的
    if/elif。"""
    if target_type == 'SHAPE_KEY':
        obj = target_object
        if not obj or not obj.data or not getattr(obj.data, "shape_keys", None):
            return None
        key = obj.data.shape_keys.key_blocks.get(data_name)
        if not key:
            return None
        return key, "value", -1

    elif target_type == 'CUSTOM_PROP':
        obj = target_object
        if not obj or data_name not in obj.keys():
            return None
        return obj, f'["{data_name}"]', -1

    elif target_type == 'BONE_LOC':
        obj = target_object
        if not obj or obj.type != 'ARMATURE':
            return None
        pbone = obj.pose.bones.get(bone_name)
        if not pbone:
            return None
        axis_idx = {'X': 0, 'Y': 1, 'Z': 2}[bone_axis]
        return pbone, "location", axis_idx

    return None


def resolve_driver_target(binding):
    """回傳 (id_data, data_path, array_index) 供 driver_add 使用;失敗回傳None。
    binding是一筆TargetBinding(見properties.py),不是SliderRigItem本身——
    一個item可能有多筆binding(XY_2D兩軸各一筆),每筆各自獨立解析。用的是
    binding當下的即時欄位(使用者在UI上看到、正在編輯的值),要新建driver
    找目標時用這個;移除舊driver要用_resolve_bound_driver_target()(見該
    函式的說明),不要在remove_driver()裡誤用這個。"""
    return _resolve_driver_target_fields(
        binding.target_type, binding.target_object, binding.data_name,
        binding.bone_name, binding.bone_axis,
    )


def _resolve_bound_driver_target(binding):
    """回傳上一次rig_builder.add_driver()成功建立driver時,實際使用的目標
    (讀binding.bound_*快照欄位,不是即時欄位)。remove_driver()一律靠這個
    (不是resolve_driver_target())決定去哪裡拆driver——使用者改
    target_object/data_name之後,即時欄位已經指向新目標,沒有辦法回推
    「原本綁在哪裡」,只有這份快照留著改動前的紀錄(見
    properties.TargetBinding.bound_target_type等欄位定義處的完整說明)。
    bound_target_type是空字串代表這筆binding目前沒有已知的既有driver
    (從沒建立過,或上次remove_driver()執行完已經清空),直接回傳None,
    不會誤觸_resolve_driver_target_fields()裡任何一個分支。"""
    if not binding.bound_target_type:
        return None
    return _resolve_driver_target_fields(
        binding.bound_target_type, binding.bound_target_object, binding.bound_data_name,
        binding.bound_bone_name, binding.bound_bone_axis,
    )


def _snapshot_bound_driver_target(binding):
    """把binding即時欄位目前指向的目標存進bound_*快照,供之後
    remove_driver()使用。只在add_driver()成功建立driver之後呼叫——沒有
    成功建立就存快照的話,快照會跟「實際場景裡到底有沒有driver」對不上。"""
    binding.bound_target_type = binding.target_type
    binding.bound_target_object = binding.target_object
    binding.bound_data_name = binding.data_name
    binding.bound_bone_name = binding.bone_name
    binding.bound_bone_axis = binding.bone_axis


def _clear_bound_driver_snapshot(binding):
    """清空bound_*快照,代表「這筆binding目前沒有任何已知綁定」。
    remove_driver()不論有沒有真的找到driver可拆,執行完都會呼叫這個。"""
    binding.bound_target_type = ""
    binding.bound_target_object = None
    binding.bound_data_name = ""
    binding.bound_bone_name = ""
    binding.bound_bone_axis = ""


def ensure_slider_collection(scene):
    """回傳(必要時建立)存放所有生成滑桿物件的專屬Collection,並確保它有連結到
    scene底下,讓生成的物件統一歸類,不會散落在使用者當下作用中的Collection裡。"""
    coll = bpy.data.collections.get(SLIDER_COLLECTION_NAME)
    if coll is None:
        coll = bpy.data.collections.new(SLIDER_COLLECTION_NAME)
    if coll.name not in scene.collection.children:
        scene.collection.children.link(coll)
    return coll


def ensure_slider_ui_material():
    """回傳(必要時建立)所有控制介面物件(Frame/Track/Handle/Label)共用的預設
    材質:純Emission、不受場景燈光/角度影響,確保在Material Preview/Rendered
    視圖下這些UI元件仍然清楚可見,不會因為沒有材質資訊而顯示成預設的灰/黑。
    只在物件當下沒有任何材質slot時才會被套用(見ensure_ui_material_on),
    使用者事後在材質面板自己改的顏色不會被regenerate洗掉。"""
    mat = bpy.data.materials.get(SLIDER_UI_MATERIAL_NAME)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(SLIDER_UI_MATERIAL_NAME)
    mat.use_nodes = True
    mat.diffuse_color = (1.0, 1.0, 1.0, 1.0)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    emission = nodes.new('ShaderNodeEmission')
    emission.inputs['Color'].default_value = (1.0, 1.0, 1.0, 1.0)
    output = nodes.new('ShaderNodeOutputMaterial')
    links.new(emission.outputs['Emission'], output.inputs['Surface'])
    return mat


def ensure_ui_material_on(obj):
    """幫控制介面物件套上共用的預設材質,但只在它目前完全沒有材質slot時才
    套用——這樣使用者事後自己在材質面板換掉的顏色/材質,不會在下次
    regenerate時被重置回預設值(跟非破壞性generate()「不動使用者已經調整
    過的狀態」的精神一致)。"""
    if len(obj.data.materials) == 0:
        obj.data.materials.append(ensure_slider_ui_material())


# 每種control_style依序要驅動Handle局部空間的哪些transform_type,對應
# item.target_bindings[0]、[1]、[2]...(見properties.get_binding)。1D樣式
# 固定只驅動局部Y(不管視覺上是直向還是橫向,拖拽軸永遠是Handle自己的
# 局部Y,見track_rotation_for的說明);XY_2D同時驅動局部X、Y。這個tuple
# 的長度就是:這個control_style需要幾筆target_bindings、Handle要解鎖幾個
# local軸、LIMIT_LOCATION要鉗制哪幾個軸——全部從這裡查表決定,新增樣式
# 只要在這裡登記一筆,create_slider_widgets/can_keep_existing_widgets/
# bind_drivers/面板UI都不用跟著手動加分支。
CONTROL_STYLE_AXES = {
    'LINEAR_1D': ('LOC_Y',),
    'LINEAR_1D_HORIZONTAL': ('LOC_Y',),
    'XY_2D': ('LOC_X', 'LOC_Y'),
    # 純文字沒有可拖拽的軸,也不驅動任何target_bindings——空tuple讓
    # bind_drivers/unbind_drivers/Handle.lock_location/LIMIT_LOCATION
    # 這些依axes_for()迴圈的邏輯自然變成「什麼都不做」,不需要另外加分支。
    'TEXT_LABEL': (),
}

# (lock_location的索引, LIMIT_LOCATION屬性名稱後綴)
_AXIS_INFO = {'LOC_X': (0, 'x'), 'LOC_Y': (1, 'y'), 'LOC_Z': (2, 'z')}


def axes_for(control_style):
    """回傳這個control_style要驅動的transform_type tuple;查不到(理論上
    不會發生,除非CONTROL_STYLE_ITEMS新增了樣式卻忘了來這裡登記)預設
    回傳單一LOC_Y,跟現有1D樣式行為一致,不會直接炸掉。"""
    return CONTROL_STYLE_AXES.get(control_style, ('LOC_Y',))


def _handle_lock_for(control_style):
    """回傳這個control_style底下Handle.lock_location該有的樣子(3個bool的
    tuple)——create_slider_widgets建立時、can_keep_existing_widgets判斷
    要不要重建時都要用同一份邏輯算,抽成共用函式避免兩處各自算一次、
    改了一邊忘記改另一邊。"""
    lock = [True, True, True]
    for axis in axes_for(control_style):
        lock[_AXIS_INFO[axis][0]] = False
    return tuple(lock)


def _expected_track_mesh(control_style):
    """回傳這個control_style底下Track應該用哪一份mesh data——目前只有
    XY_2D用正方形pad mesh,其餘都用1D的長條mesh。mesh形狀是獨立於軸數的
    視覺決定(不是用len(axes_for(...))反推),以後如果有別的2軸樣式但
    長得不一樣,不會被誤判成同一種。
    TEXT_LABEL沒有可拖拽的控制器本體,Track純粹只當Handle(這裡是文字
    物件本身)的定位錨點,不需要畫出任何軌道外框,所以用一份空白mesh。"""
    if control_style == 'XY_2D':
        return _ensure_pad_track_mesh()
    if control_style == 'TEXT_LABEL':
        return _ensure_empty_track_mesh()
    return _ensure_track_mesh()


def track_rotation_for(control_style):
    """回傳這個control_style底下Track應有的初始rotation_euler(Z軸角度,弧度)。
    橫向樣式(LINEAR_1D_HORIZONTAL)只是把Track本身繞Z軸轉90度——Handle掛在
    Track底下,LIMIT_LOCATION的owner_space='LOCAL'鉗制的是Handle自己的局部
    空間,不受parent(Track)旋轉影響,driver讀的也是Handle局部Y座標,所以轉
    Track就能讓拖拽方向在世界空間裡從垂直變水平,不需要另外改driver的
    transform_type或constraint軸向(已用最小可重現案例實測驗證過)。

    **必須是-90度,不是+90度**:driver把Handle局部+Y映射到max_val、
    局部-Y映射到min_val(見add_driver的線性映射公式),繞Z軸轉+90度會
    讓局部+Y指向世界-X,結果是max在左邊、min(通常是0)在右邊,跟橫向
    滑桿「左邊是0、往右變大」的直覺相反(真實使用者回報)。轉-90度讓
    局部+Y指向世界+X,min/0落在左邊、max落在右邊,跟直向樣式
    (局部+Y就是世界+Y,min在下、max在上)的「往正方向拖曳數值變大」
    語意一致。
    這裡的正負號改動不需要動driver/constraint的任何設定——兩者都在
    Handle自己的局部空間運作(見上面的說明),只有Track的世界朝向變了。"""
    if control_style == 'LINEAR_1D_HORIZONTAL':
        return (0.0, 0.0, math.radians(-90))
    return (0.0, 0.0, 0.0)


def label_offset_for(control_style):
    """回傳標籤中心離Track中心的距離,依control_style的本體格數
    (CONTROL_STYLE_CELLS的height_cells)計算,而不是固定值或Track的
    物理長/寬——基礎公式是(height_cells / 2 + 0.5) * CELL_SIZE:「本體
    中心到本體頂端」的距離是height_cells/2格,再加上「標籤格本身半格」
    (標籤永遠佔1整格,格中心距離格頂端/底端各半格)就是0.5格,兩者相加
    就是本體中心到標籤格中心的正確距離;再加上LABEL_GAP這個額外的固定
    物理間距,讓標籤能比格子系統算出的精準中心點再往外推一點,留一些
    視覺呼吸空間(使用者可調整LABEL_GAP微調這個額外間距,不影響格子
    系統本身的置中計算)。

    (height_cells/2+0.5)這部分的公式讓標籤精準落在
    grid_layout.occupied_cells()/cells_for()定義的那個標籤格正中央,
    不管control_style本體佔幾格高:直向(LINEAR_1D, height_cells=2)
    算出(2/2+0.5)*CELL_SIZE=1.5格,橫向(LINEAR_1D_HORIZONTAL,
    height_cells=1)算出(1/2+0.5)*CELL_SIZE=1格——兩者最終標籤格中心的
    世界座標會對齊在一起(因為橫向本體矮1格,但它到標籤格中心只需要
    多走1格,直向本體高2格但到標籤格中心也是多走1格,兩者殊途同歸)。
    額外加的LABEL_GAP不影響這個「兩種control_style互相對齊」的特性,
    因為兩者都是加上同一個常數。

    這裡改過兩次都不對:第一次固定用TRACK_LENGTH/2(直向Track長邊)或
    TRACK_WIDTH/2(橫向Track短邊)——讓不同樣式標籤絕對高度對齊,但兩者
    留白比例差很多,而且Frame半高要另外估算標籤文字實際高度取最大值,
    導致某個item開標籤會連帶撐大同group其他item跟Frame邊界的間隔。
    第二次改成固定用CELL_SIZE(不分height_cells)——這只對height_cells=2
    的直向樣式碰巧算對(本體中心到頂端剛好1格,再加標籤格半格,總共
    1.5格,但固定值只給了1格,實際上少了0.5格,只是這個案例外框夠寬鬆
    沒被抓到);對height_cells=1的橫向樣式則是多算了0.5格,導致標籤
    位置比理論值多推了半格,跡出Frame外框(真實bug,使用者截圖回報)。
    現在這個(height_cells/2+0.5)*CELL_SIZE才是通用公式,兩種height_cells
    都驗證過數值正確,LABEL_GAP是後來在這個已驗證正確的基礎上疊加的
    額外微調量,不會重蹈同樣的覆轍。"""
    _, height_cells = CONTROL_STYLE_CELLS.get(control_style, (1, 1))
    return (height_cells / 2 + 0.5) * CELL_SIZE + LABEL_GAP


def _initial_axis_offset(binding, travel):
    """算這個binding對應的Handle局部軸,新建時應該從哪個座標開始拖——不是
    永遠從Track中心(0)開始。規則依min_val/max_val的正負號分佈決定「中立值」
    該落在哪:跨零(min_val<0<max_val)的參數(例如左右對稱的-45~45)中立值
    就是0,維持在中心;同號的參數(例如0~1的張嘴程度、-1~0的下壓程度)
    沒有真正的「中點」意義,中立值應該是min_val/max_val裡絕對值較小的那個
    (=離0比較近的那個,對0~1、-1~0這類「一端是0」的常見情況直接對應那個
    0;對兩者都不含0的範圍,例如2~10,則落在min_val那端,符合「預設在最
    小值」的直覺)。

    算出「中立值該是多少」之後,還要反解對應的Handle局部座標:
    add_driver()的映射式是「局部座標-travel~travel線性對應到lo~hi」,
    lo/hi在binding.invert時會對調,所以這裡必須用同一份lo/hi反推,不能只看
    min_val/max_val本身,否則invert打開時Handle會停在物理上錯的一端。
    只有binding為None(還沒初始化)或min_val==max_val(退化區間,無法定義
    方向)時回傳0(Track中心),不強行猜測。"""
    if binding is None:
        return 0.0
    lo, hi = binding.min_val, binding.max_val
    if lo == hi:
        return 0.0
    neutral = 0.0 if lo < 0.0 < hi else (lo if abs(lo) <= abs(hi) else hi)
    neutral = max(min(neutral, max(lo, hi)), min(lo, hi))

    driver_lo, driver_hi = (hi, lo) if binding.invert else (lo, hi)
    if driver_hi == driver_lo:
        return 0.0
    ratio = (neutral - driver_lo) / (driver_hi - driver_lo)
    return -travel + ratio * (2 * travel)


def create_slider_widgets(item, location, collection):
    # Track身兼兩職:純視覺的軌道長條/正方形pad(顯示拖拽範圍,不可選取),
    # 同時也是Handle的定位「插座」——Track本身鎖死不可移動,負責在Frame內
    # 的排版local座標,讓Handle自己的local座標永遠從(0,0,0)起算,拖拽範圍
    # 不受排版座標影響(避免排版偏移量超過travel距離時,Handle一生成就被
    # 自己的LIMIT_LOCATION constraint夾死在邊界)。不再需要額外的Anchor
    # Empty。Track mesh依control_style選:目前只有XY_2D用正方形pad,其餘
    # 共用1D的長條mesh(拖拽方向/直向橫向靠Track的初始rotation_euler決定,
    # 見track_rotation_for())。
    track_mesh = _expected_track_mesh(item.control_style)
    track = bpy.data.objects.new(f"SliderTrack_{item.name}", track_mesh)
    collection.objects.link(track)
    track.location = location
    track.rotation_euler = track_rotation_for(item.control_style)
    track.lock_location = [True, True, True]
    track.lock_rotation = [True, True, True]
    track.lock_scale = [True, True, True]
    track.hide_select = True
    track.hide_render = True  # 控制介面,不該出現在最終渲染輸出裡
    ensure_ui_material_on(track)

    if item.control_style == 'TEXT_LABEL':
        # 純文字沒有可拖拽的控制器本體——generated_empty這裡改放一個
        # FONT curve物件,直接顯示item.name,不建Handle圓盤、不加
        # LIMIT_LOCATION(反正axes_for()是空tuple,沒有軸需要鉗制)。仍然
        # 沿用「Track是定位錨點、Handle掛在Track底下」這套既有骨架,
        # 讓Frame parenting/measure_group_extent/remove_generated_empty
        # 等既有管線完全不用另外分支處理這個樣式。
        curve = bpy.data.curves.new(f"SliderTextLabelData_{item.name}", type='FONT')
        handle = bpy.data.objects.new(f"Slider_{item.name}", curve)
        collection.objects.link(handle)
        handle.parent = track
        handle.hide_render = True
        # 純文字沒有可拖拽的意義(axes_for('TEXT_LABEL')是空tuple,不驅動
        # 任何target),不該讓使用者誤以為這是個可以選取/拖拽的控制器
        # 本體——比照上面Track本身的設定,凡是「不該被使用者直接選取
        # 操作」的生成物件都設hide_select。
        handle.hide_select = True
        ensure_ui_material_on(handle)
        handle.lock_location = _handle_lock_for(item.control_style)
        handle.lock_rotation = [True, True, True]
        handle.lock_scale = [True, True, True]
        curve.body = item.name
        curve.size = item.label_size_raw
        curve.align_x = 'CENTER'
        curve.align_y = 'CENTER'
        return track, handle

    handle_mesh = _ensure_handle_mesh()
    handle = bpy.data.objects.new(f"Slider_{item.name}", handle_mesh)
    collection.objects.link(handle)
    handle.parent = track
    handle.hide_render = True  # 同上
    ensure_ui_material_on(handle)

    # 依control_style需要驅動的軸(見CONTROL_STYLE_AXES/axes_for)解鎖
    # Handle對應的局部軸、設定LIMIT_LOCATION的鉗制範圍——寫成迴圈是刻意
    # 的,以後真的加第三軸的樣式,只要CONTROL_STYLE_AXES多登記一筆
    # 'LOC_Z',這裡完全不用改。
    handle.lock_location = _handle_lock_for(item.control_style)
    handle.lock_rotation = [True, True, True]
    handle.lock_scale = [True, True, True]

    con = handle.constraints.new('LIMIT_LOCATION')
    con.owner_space = 'LOCAL'
    travel = PAD_TRAVEL if item.control_style == 'XY_2D' else HANDLE_TRAVEL
    axes = axes_for(item.control_style)
    for axis in axes:
        suffix = _AXIS_INFO[axis][1]
        setattr(con, f'use_min_{suffix}', True)
        setattr(con, f'use_max_{suffix}', True)
        setattr(con, f'min_{suffix}', -travel)
        setattr(con, f'max_{suffix}', travel)

    # 新建的Handle不再固定從Track中心(0,0,0)開始——依每一軸binding的
    # min_val/max_val算出「中立值」該落在哪個局部座標(見
    # _initial_axis_offset的完整說明),同號區間(例如0~1)落在對應的
    # min_val端,跨零區間(例如-45~45)維持在中心。用peek_binding(唯讀)
    # 不是get_binding——這裡雖然是允許寫入的執行期context,但這個位置只
    # 需要讀,不該在建立Handle的路徑上意外把target_bindings的collection
    # 補長度。還沒設定binding的軸維持0(Track中心),不強行猜測。
    init_loc = [0.0, 0.0, 0.0]
    for i, axis in enumerate(axes):
        binding = properties.peek_binding(item, i)
        init_loc[_AXIS_INFO[axis][0]] = _initial_axis_offset(binding, travel)
    handle.location = init_loc

    return track, handle


def sync_text_label_content(item):
    """TEXT_LABEL樣式的item.generated_empty是FONT curve(見
    create_slider_widgets),但can_keep_existing_widgets為True時該物件會
    被整個跳過、完全不碰——這對其他樣式是對的(保留使用者拖曳過的
    Handle位置),但對純文字來說,文字內容/大小是「每次都該反映當下
    item.name/label_size_raw」的東西,不是使用者手動調整過、需要保留的
    拖曳狀態。所以另外抽成一個每次generate()都執行的同步函式,呼叫時機
    跟rig_builder.sync_label()一樣——不管是新建或保留分支,都要跑一次,
    確保改了item名稱之後不用整個重建Handle才會反映到畫面上。
    非TEXT_LABEL樣式或Handle還不存在時直接跳過,不是這個函式的職責。"""
    if item.control_style != 'TEXT_LABEL' or item.generated_empty is None:
        return
    curve = item.generated_empty.data
    curve.body = item.name
    curve.size = item.label_size_raw
    # hide_select比照create_slider_widgets()新建時的設定(見該函式)——這裡
    # 補一份是為了讓「這次修正之前就已經生成過」的既有純文字滑桿,不用
    # 整個Clear+Generate重建,按一次「更新滑桿綁定」就能補上這個設定
    # (can_keep_existing_widgets為True時Handle物件本身完全不會重建,只有
    # 這個每次都會執行的同步函式碰得到它)。
    item.generated_empty.hide_select = True


def can_keep_existing_widgets(item):
    """判斷這個item的Track/Handle能不能在非破壞性generate()裡被保留(只更新
    Track位置,Handle完全不碰,見operators.SLIDERRIG_OT_generate.execute())。
    條件全部要滿足:generated_empty(Handle)存在;它掛靠的Track目前的旋轉
    跟item.control_style此刻應有的旋轉一致;Track的mesh data跟這個
    control_style現在應該用的mesh是同一份;Handle的lock_location也跟這個
    control_style現在應該解鎖的軸一致。用物件目前狀態直接比對(而不是
    額外存一個last_control_style欄位),這是跟先前slider_axis換軸偵測同一套
    做法:不新增持久化狀態,萬一以後control_style的實作方式改變,這段判斷
    可以直接跟著調整,不用另外維護/清理孤兒欄位。

    只比對旋轉是不夠的:LINEAR_1D跟XY_2D的track_rotation_for()都是
    (0,0,0)(XY_2D沒有旋轉需求),如果只看旋轉,LINEAR_1D切換成XY_2D會被
    誤判成「沒變」,導致該重建的Track/Handle被錯誤保留——舊的長方形mesh、
    單軸lock_location/constraint整組留在原地,Handle實際上還是只能沿Y拖,
    根本不是XY_2D該有的行為。所以額外加了mesh identity跟lock_location的
    比對,任一個不符就強制重建、歸零。"""
    handle = item.generated_empty
    if handle is None:
        return False
    track = handle.parent
    if track is None:
        return False
    expected_rotation = track_rotation_for(item.control_style)
    rotation_ok = all(
        abs(a - b) < 1e-6
        for a, b in zip(tuple(track.rotation_euler), expected_rotation)
    )
    if not rotation_ok:
        return False
    if track.data is not _expected_track_mesh(item.control_style):
        return False
    return tuple(handle.lock_location) == _handle_lock_for(item.control_style)


def sync_label(item, track, collection):
    """依item.show_label同步這個滑桿的名稱標籤(Text Mesh):關閉就移除已生成
    的標籤(如果有),開啟就建立(不存在時)或更新內容/大小(已存在時)。標籤
    掛在Track底下(跟Handle平級),位置固定在Track正上方一整格(CELL_SIZE)
    的距離,跟著Track/Frame的parenting自動走(包含橫向樣式:Track轉90度後,
    標籤的local(0, CELL_SIZE, 0)位置也會跟著轉——這個距離固定用CELL_SIZE,
    不依control_style分流,見label_offset_for的說明;標籤文字本身不會跟著
    旋轉,見下方align設定與curve.rotation處理)。
    每個滑桿的文字內容都不同,curve data不能像Track/Handle那樣共用快取,
    每個滑桿獨立一份。"""
    if not item.show_label:
        if item.generated_label:
            curve = item.generated_label.data
            bpy.data.objects.remove(item.generated_label, do_unlink=True)
            if curve and curve.users == 0:
                bpy.data.curves.remove(curve)
            item.generated_label = None
        return

    label = item.generated_label
    if label is None:
        curve = bpy.data.curves.new(f"SliderLabelData_{item.name}", type='FONT')
        label = bpy.data.objects.new(f"SliderLabel_{item.name}", curve)
        collection.objects.link(label)
        label.parent = track
        label.hide_render = True  # 控制介面,不該出現在最終渲染輸出裡
        label.hide_select = True  # 純文字標示,不需要被使用者選取/拖拽
        item.generated_label = label
    ensure_ui_material_on(label)  # 補材質不受label是新建/既有影響,邏輯跟Frame一致
    curve = label.data
    curve.body = item.name
    # 讀label_size_raw(底層真實值),不是label_size——後者是給UI用的顯示層
    # (get/set包了*1000的轉換,見properties.py),curve.size要的是原始小數,
    # 讀item.label_size在這裡會直接把文字放大1000倍。
    curve.size = item.label_size_raw
    curve.align_x = 'CENTER'
    curve.align_y = 'BOTTOM'
    # 標籤文字永遠水平書寫、擺在控制器「螢幕上方」,不隨Track的rotation_euler
    # 轉動(橫向樣式Track轉了90度,如果標籤跟著轉,文字會變成直的、難以閱讀)。
    # rotation_euler抵銷Track的旋轉是第一步,但location本身也需要處理:
    # label.parent = track,而location是「Track局部空間裡的一個點」,這個
    # 點在算世界座標時一樣會先被Track的旋轉矩陣轉換過——單純抵銷
    # rotation_euler只讓文字本身不歪斜,不會讓location代表的位置維持在
    # 「螢幕上方」;Track轉90度後,原本設計成「局部+Y=視覺上方」的
    # location,會被同一個90度旋轉轉成水平方向,導致標籤跑到Track側邊、
    # 跟外框重疊(真實bug,使用者截圖回報)。修法:location先套用Track
    # 旋轉矩陣的反矩陣,兩次旋轉互相抵銷,讓標籤在Track局部座標系統裡的
    # 「絕對距離」不變,但轉換到世界空間後的方向不受Track旋轉影響,永遠
    # 對應到螢幕上方。
    #
    # 這個「絕對距離」固定用label_offset_for()回傳的CELL_SIZE(格子系統
    # 的一整格),不依control_style分流——見label_offset_for的完整說明:
    # 曾經依control_style分別用Track的長邊/短邊半長當距離,雖然讓不同
    # 樣式的標籤絕對高度對齊了,卻導致標籤與Track邊緣的留白比例不一致
    # (橫向樣式間隔明顯比直向寬鬆),而且Frame半高得另外估算每個item的
    # 標籤實際伸出距離取最大值,還會讓某個item開啟標籤,連帶撐大同group
    # 裡其他item跟Frame邊界的間隔(即使那個item自己的標籤位置沒變)。
    # 固定用CELL_SIZE後,兩個問題一併解決:每個item標籤都固定佔「一格」,
    # Frame邊界只要用content_bounds()的格子數就天然足夠,不需要額外估算。
    track_rotation = track_rotation_for(item.control_style)
    label.rotation_euler = tuple(-r for r in track_rotation)
    offset = mathutils.Euler(track_rotation).to_matrix().inverted() @ mathutils.Vector(
        (0, label_offset_for(item.control_style), 0)
    )
    label.location = offset


def remove_generated_empty(item):
    """移除item已生成的Handle、它掛靠的Track(Track本身兼作Handle的定位父層)、
    名稱標籤(如果有),以及綁在目標屬性上的Driver(避免刪除滑桿後留下指向
    已刪除物件的壞掉Driver)。"""
    handle = item.generated_empty
    if item.generated_label:
        curve = item.generated_label.data
        bpy.data.objects.remove(item.generated_label, do_unlink=True)
        if curve and curve.users == 0:
            bpy.data.curves.remove(curve)
        item.generated_label = None
    if not handle:
        return
    unbind_drivers(item)
    track = handle.parent
    # TEXT_LABEL的Handle是FONT curve,而且是per-item獨立資料(不像
    # SliderHandleData_Knob那樣所有滑桿共用一份、靠refcount+另外的孤兒
    # 清除流程處理)——跟sync_label()清除item.generated_label的做法一樣,
    # 這裡刪物件的同時必須連帶清curve data,否則每次TEXT_LABEL被刪除/
    # 重建就會留下一個0-user的孤兒curve永久累積在.blend檔裡。其他樣式的
    # Handle用共用mesh,不受這段影響(mesh的0-user清除仍然交給
    # operators.generate()/clear()裡既有的purge邏輯)。
    handle_curve = handle.data if isinstance(handle.data, bpy.types.Curve) else None
    bpy.data.objects.remove(handle, do_unlink=True)
    if handle_curve and handle_curve.users == 0:
        bpy.data.curves.remove(handle_curve)
    if track and track.name.startswith("SliderTrack_"):
        bpy.data.objects.remove(track, do_unlink=True)
    item.generated_empty = None


def remove_stray_root():
    """移除舊版架構留下的全域SliderRig_Root(如果存在)。現在每組Frame是獨立的
    頂層物件,不再需要一個共用的root來承載整個rig。"""
    root = bpy.data.objects.get("SliderRig_Root")
    if root:
        bpy.data.objects.remove(root, do_unlink=True)


def _remove_object_and_data(obj):
    """刪除obj,並在它的data(mesh或curve)因此變成0-user時一併清掉——
    Frame用mesh、分組名稱標籤用curve,兩種data type共用同一段清除邏輯,
    不用各自重複寫一份users==0判斷。"""
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data and data.users == 0:
        if isinstance(data, bpy.types.Mesh):
            bpy.data.meshes.remove(data)
        elif isinstance(data, bpy.types.Curve):
            bpy.data.curves.remove(data)


def remove_all_slider_frames():
    """移除場景裡所有的SliderFrame_*物件跟它們的分組名稱標籤
    (SliderGroupLabel_*),連同各自的mesh/curve data。用於clear()整批砍掉
    的情境——generate()改成非破壞性(upsert)之後不再呼叫這個函式,改用
    find_existing_frame()/remove_orphan_frames()只處理真正不再需要的Frame,
    見下方說明。分組名稱標籤是Frame的child,但Blender刪除Frame不會連帶
    刪除child物件(child只會變成場景裡沒有parent的孤兒),所以要在這裡
    明確一併處理,不能只刪Frame。"""
    for obj in list(bpy.data.objects):
        if obj.name.startswith("SliderFrame_") or obj.name.startswith("SliderGroupLabel_"):
            _remove_object_and_data(obj)


def find_existing_frame(group_uid):
    """依group_uid在場景裡找上次generate()已經建立的Frame(用自訂屬性
    frame["group_uid"]比對,不依賴物件名稱——使用者在Outliner裡手動改過
    Frame的物件名稱也不會讓這個查找失效)。找不到回傳None。"""
    for obj in bpy.data.objects:
        if obj.name.startswith("SliderFrame_") and obj.get("group_uid") == group_uid:
            return obj
    return None


def find_group_label(group_uid):
    """依group_uid在場景裡找這個分組的名稱標籤物件(用自訂屬性
    label["group_uid"]比對,跟find_existing_frame同一套做法)。找不到
    回傳None。"""
    for obj in bpy.data.objects:
        if obj.name.startswith("SliderGroupLabel_") and obj.get("group_uid") == group_uid:
            return obj
    return None


def remove_orphan_frames(valid_group_uids):
    """generate()是upsert:分組被改名/移出/整組刪除後,舊Frame不會再被任何
    item的group_uid對應到,不會自動被find_existing_frame()找到、也就不會被
    保留或更新。這裡在每次generate()時主動清掉這些真正變成孤兒的Frame
    跟它的分組名稱標籤(連同mesh/curve data),避免場景裡累積沒人管的舊
    物件。用自訂屬性group_uid判斷,不是SliderGroupItem.generated_label——
    分組整個被_remove_group()刪掉時,那個PropertyGroup實例已經不存在了,
    沒辦法透過它找到自己生成過的標籤物件,必須跟Frame一樣靠場景裡物件
    本身的自訂屬性反查。"""
    for obj in list(bpy.data.objects):
        is_frame = obj.name.startswith("SliderFrame_")
        is_group_label = obj.name.startswith("SliderGroupLabel_")
        if (is_frame or is_group_label) and obj.get("group_uid") not in valid_group_uids:
            _remove_object_and_data(obj)


def frame_origin_marker_center(extent):
    """回傳show_frame關閉時,原點標記小圓點的圓心座標(Frame局部空間的
    (x, y))——內容範圍的左上角,也就是外框如果有畫出來的話,左上角那一點
    的位置。

    刻意用extent的(min_x, max_y)而不是Frame自己的局部原點(0,0):Frame的
    局部原點不保證落在內容的左上角,甚至常常落在內容中間(見
    measure_group_extent的說明——內容經常不以Frame原點對稱分布,標籤側的
    margin還刻意比其他側窄),畫在(0,0)會讓標記出現在控制器之間而不是
    使用者預期的角落。用extent則保證「開外框時左上角在哪、關外框時標記
    就在哪」,切換show_frame不會讓標記位置跳動。

    往內縮一整個半徑(不是半個)是為了讓**整個圓點**落在extent內——圓心
    只縮半個半徑的話,圓的外緣仍會凸出extent之外半個半徑(實測驗證過:
    extent左緣-0.1620、圓心-0.1545、但外緣到-0.1695,凸出0.0075)。
    extent已經是加過margin的邊界,凸出去在視覺上會像是飄在框外的孤立點。
    縮一整個半徑之後,圓的外緣剛好內切於extent的角落。"""
    min_x, _max_x, _min_y, max_y = extent
    inset = FRAME_ORIGIN_MARKER_RADIUS
    return (min_x + inset, max_y - inset)


def _fill_frame_mesh(mesh, extent, show_frame):
    """依show_frame填Frame的mesh內容:開啟時畫矩形外框,關閉時改畫一個
    左上角的原點標記小圓點(見frame_origin_marker_center)。

    抽成共用函式是因為create_slider_frame()(新建)跟update_frame_mesh()
    (既有Frame)兩處都要做完全一樣的判斷——先前這段邏輯在兩個函式裡各寫
    一份,任何一邊改了另一邊沒跟上就會出現「新建的Frame有標記、但既有
    Frame按更新之後沒有」這種不一致。呼叫端負責mesh的生命週期
    (新建/clear_geometry),這裡只負責填內容。"""
    if show_frame:
        min_x, max_x, min_y, max_y = extent
        _fill_ring_mesh_asym(
            mesh, min_x, max_x, min_y, max_y,
            FRAME_BORDER_THICKNESS, 0, 1, FRAME_CORNER_RADIUS,
        )
        return
    # show_frame關閉:不畫外框,但仍要留一點幾何體讓這個Frame在viewport
    # 裡選得到(見FRAME_ORIGIN_MARKER_RADIUS的說明)。標記畫在Frame自己的
    # mesh上、不是另外建一個子物件——點到標記就等於選到Frame本身,正好是
    # 這個功能要解決的問題;另建子物件的話點到的是那個子物件,反而沒解決。
    center_x, center_y = frame_origin_marker_center(extent)
    add_disc_to_mesh(
        mesh, FRAME_ORIGIN_MARKER_RADIUS, center_x, center_y, 0, 1,
    )


def create_slider_frame(group_uid, group_label, extent, collection,
                         face_rotation=None, show_frame=True):
    """建立這個group專屬的全新外框(Frame)物件(這個group目前在場景裡還沒有
    對應的Frame,見find_existing_frame):純視覺的矩形外框,完全不鎖任何
    transform,讓使用者可以直接對它做移動/旋轉/縮放,整組底下的滑桿會透過
    parenting自動跟著走(不需要額外程式碼處理縮放/旋轉的傳遞)。
    extent是(min_x, max_x, min_y, max_y)四個獨立邊界(不是half_width/
    half_height對稱假設)——見update_frame_mesh的完整說明,這裡不重複。
    物件命名用「顯示名稱_uid前8碼」而不是純group_uid或純group_label:純uid
    在Outliner裡對使用者是一串看不懂的hex;純label在兩個分組剛好同名時會
    撞名(現在分組用uid判斷是否同一組,允許同名分組同時存在,物件命名不能
    再假設label是唯一的)。物件上另外寫入自訂屬性group_uid,是之後
    find_existing_frame()辨識「這是哪個分組的Frame」的依據,不受使用者
    手動改物件名稱影響。
    face_rotation非None時,套用成Frame的初始旋轉(見operators._view_facing_rotation);
    只有新建的Frame才套用一次性的view-facing對齊,之後這個Frame不管是被
    使用者手動Rotate過、或是單純沒去動它,generate()都不會再覆寫它的旋轉
    (見update_frame_mesh,既有Frame只重算mesh,完全不碰transform)。
    show_frame為False時,Frame物件仍然建立(承載排版與綁定,見下方
    sync_frame_binding),不畫矩形外框,改在內容範圍左上角畫一個原點標記
    小圓點(見_fill_frame_mesh/frame_origin_marker_center)。"""
    suffix = f"{group_label}_{group_uid[:8]}"
    mesh = bpy.data.meshes.new(f"SliderFrameData_{suffix}")
    _fill_frame_mesh(mesh, extent, show_frame)
    frame = bpy.data.objects.new(f"SliderFrame_{suffix}", mesh)
    frame["group_uid"] = group_uid
    frame.hide_render = True  # 控制介面,不該出現在最終渲染輸出裡
    ensure_ui_material_on(frame)
    if face_rotation is not None:
        frame.rotation_euler = face_rotation.to_euler()
    collection.objects.link(frame)
    return frame


def update_frame_mesh(frame, extent, show_frame=True):
    """既有Frame(這個group上次generate()就已經有對應的Frame)只重算mesh
    geometry,完全不碰transform(location/rotation/scale)——保留使用者可能
    已經手動Move/Rotate/Scale過的狀態,這是generate()改成非破壞性的核心
    行為之一。舊mesh data直接在原地重新填內容(不新建/替換mesh block),
    這樣任何指向這份mesh data的引用(理論上只有這個Frame自己)都不會失效。
    show_frame為False時不畫矩形外框,改在內容範圍左上角畫一個原點標記
    小圓點(見_fill_frame_mesh/frame_origin_marker_center),Frame物件本身
    繼續存在。這裡每次都先clear_geometry()再重填,所以show_frame開↔關
    的切換不需要另外偵測——按一次「更新滑桿綁定」就會換成對應的內容,
    不用先Clear再Generate。
    也順便補上hide_render/預設材質——這兩個是這輪才加的行為,既有(在舊版
    程式碼下建立的)Frame物件可能還沒有,補上時只在沒有材質slot時才套用,
    不會動到使用者已經自己調過的材質。

    extent是(min_x, max_x, min_y, max_y)四個獨立邊界,不是half_width/
    half_height對稱假設——operators.generate()會依「這一側是不是標籤側」
    分別套用FRAME_MARGIN或較窄的LABEL_SIDE_MARGIN再組出這四個邊界,所以
    Frame的四邊留白可能不對稱。Frame局部原點(0,0)仍然是
    grid_layout.cell_center_local_xy()置中Track的基準,不受這裡的mesh
    邊界是否對稱影響,兩者各自獨立。"""
    frame.hide_render = True
    ensure_ui_material_on(frame)
    mesh = frame.data
    mesh.clear_geometry()
    _fill_frame_mesh(mesh, extent, show_frame)


def measure_group_extent(frame, child_objects):
    """動態量測child_objects(這個group底下已經生成的Track/Handle/Label)
    在frame局部空間裡的真實幾何邊界,回傳(min_x, max_x, min_y, max_y)四個
    獨立邊界(不摺疊成對稱的half_width/half_height)——取代先前「用
    grid_layout格子數×CELL_SIZE估算Frame尺寸」的作法。四個獨立邊界讓
    呼叫端(operators.generate())可以依「哪一側是標籤側」分別加上不同
    的margin(FRAME_MARGIN或較窄的LABEL_SIDE_MARGIN),不用假設內容以
    Frame局部原點對稱分布。

    改用動態量測的原因:格子系統的估算值是「這一格理論上有多大」,不是
    「裡面的東西實際占多少空間」——標籤文字的bound_box會因為字型渲染、
    curve.align_y='BOTTOM'的對齊方式等因素,實際佔用範圍跟格子系統假設
    的理論中心點/半格距離對不上,曾經因為手動推導的偏移公式沒完全對齊
    格子系統的假設,導致標籤精準地跡出Frame外框(真實bug,使用者反覆
    截圖回報)。動態量測直接讀每個子物件的`bound_box`(物件local space
    的8個角點)轉換到frame的local space,取所有子物件所有角點的x/y範圍
    聯集,不管標籤文字實際渲染出來多大、多寬,Frame永遠精準包住,不用
    再猜測公式。

    只掃`Track`(不是每個Track底下的Handle/Label——它們會透過parenting
    自動包含在Track的世界位置關係裡,但bound_box本身不含子物件,所以
    這裡改成直接列舉collection裡所有以child_objects為prefix/parent的
    物件),呼叫端(operators.generate())負責蒐集完整的物件清單傳進來。

    呼叫前必須先view_layer.update():這個函式在同一次generate()呼叫內,
    緊接在剛建立/搬動這些子物件之後就執行——`matrix_world`(尤其是FONT
    curve物件,它的bound_box是文字實際渲染出來的幾何)依賴Blender的
    dependency graph先重新evaluate過,才會反映剛才對parent/location/
    rotation_euler的改動。沒有這一行,第一次generate()量到的會是「上一輪」
    或初始狀態的過期幾何,要使用者再按一次「更新滑桿綁定」才會生效
    (真實bug,使用者實測回報:第一次按外框太小、標籤跑到框外很遠,
    第二次按才正確)。"""
    bpy.context.view_layer.update()
    frame_inv = frame.matrix_world.inverted()
    xs, ys = [], []
    for obj in child_objects:
        if obj.type not in {'MESH', 'FONT'} or obj.data is None:
            continue
        for corner in obj.bound_box:
            world_pos = obj.matrix_world @ mathutils.Vector(corner)
            local_pos = frame_inv @ world_pos
            xs.append(local_pos.x)
            ys.append(local_pos.y)
    if not xs or not ys:
        return 0.0, 0.0, 0.0, 0.0
    return min(xs), max(xs), min(ys), max(ys)


def sync_frame_binding(frame, group):
    """依group.target_object/bone_name同步Frame上的CHILD_OF constraint:
    target_object為空就移除既有的綁定constraint(如果有);非空就建立
    (不存在時)或更新target/subtarget(已存在時)。用CHILD_OF而不是真正的
    物件parenting,是因為Frame目前沒有parent(獨立頂層物件),用constraint
    可以隨時方便地移除/切換綁定目標,不會牽動Frame物件的階層結構。"""
    con = frame.constraints.get("SliderGroupBinding")
    if not group.target_object:
        if con:
            frame.constraints.remove(con)
        return
    if con is None:
        con = frame.constraints.new('CHILD_OF')
        con.name = "SliderGroupBinding"
    con.target = group.target_object
    if group.target_object.type == 'ARMATURE' and group.bone_name:
        con.subtarget = group.bone_name
    else:
        con.subtarget = ""


def sync_group_label(group, frame, collection, extent):
    """依group.show_name_label同步這個分組的名稱標籤(Text Mesh):關閉就
    移除已生成的標籤(如果有),開啟就建立(不存在時)或更新內容/位置
    (已存在時)。標籤掛在Frame底下,固定顯示在Frame實際量測範圍(extent,
    跟update_frame_mesh用的是同一份、已經套用過margin的邊界)正上方——
    跟每個滑桿自己的show_label是同一種UI模式,但這是分組層級、顯示分組
    名稱,而且位置基準是Frame的真實量測範圍,不是格子系統(呼應CLAUDE.md
    「Frame sizing is measured, not estimated from the grid」的原則:
    任何跟Frame範圍相關的位置計算都該用同一份真實數字,不要另外用格子數
    重新猜一次,那個類別的bug已經在Frame/滑桿標籤上出過好幾次)。

    不需要像sync_label()那樣處理「反向旋轉抵銷Track旋轉」的問題——Frame
    本身沒有per-child的旋轉分歧(不像Track會依control_style旋轉90度),
    標籤直接用局部(0,0,0)旋轉,靠parenting自動繼承Frame的view-facing
    朝向即可,跟其他子物件(Track/Handle)的行為一致。"""
    if not group.show_name_label:
        if group.generated_label:
            curve = group.generated_label.data
            bpy.data.objects.remove(group.generated_label, do_unlink=True)
            if curve and curve.users == 0:
                bpy.data.curves.remove(curve)
            group.generated_label = None
        return

    label = group.generated_label
    if label is None:
        curve = bpy.data.curves.new(f"SliderGroupLabelData_{group.uid[:8]}", type='FONT')
        label = bpy.data.objects.new(f"SliderGroupLabel_{group.name}_{group.uid[:8]}", curve)
        label["group_uid"] = group.uid
        collection.objects.link(label)
        label.parent = frame
        label.hide_render = True  # 控制介面,不該出現在最終渲染輸出裡
        label.hide_select = True  # 純文字標示,不需要被使用者選取/拖拽
        group.generated_label = label
    ensure_ui_material_on(label)
    curve = label.data
    curve.body = group.name
    # 讀name_label_size_raw(底層真實值),不是name_label_size——後者是給UI
    # 用的顯示層(get/set包了*1000轉換,見properties.py),curve.size要的是
    # 原始小數,讀name_label_size在這裡會直接把文字放大1000倍。曾經固定用
    # mesh_builders.GROUP_LABEL_SIZE常數,現在改成per-group可調。
    curve.size = group.name_label_size_raw
    curve.align_x = 'CENTER'
    curve.align_y = 'BOTTOM'
    min_x, max_x, min_y, max_y = extent
    label.rotation_euler = (0.0, 0.0, 0.0)
    label.location = ((min_x + max_x) / 2, max_y + GROUP_LABEL_GAP, 0)


def view_facing_rotation(context):
    """回傳讓Frame正面(局部+Z,躺平時的法向量)朝向目前3D視窗鏡頭方向的
    四元數;找不到3D視窗(例如headless背景模式呼叫generate())就回傳None,
    呼叫端維持Frame原本躺平不轉的行為。"""
    region_data = getattr(context, 'region_data', None)
    if region_data is None:
        return None
    # view_rotation把 -Z(鏡頭朝向) 轉到世界空間;Frame預設正面是局部+Z,
    # 所以要對齊的方向剛好是鏡頭朝向反過來,故取view_rotation本身即可讓
    # 局部+Z指向鏡頭。
    return region_data.view_rotation.copy()


def remove_driver(binding):
    """移除binding(一筆TargetBinding)*上一次實際建立*的driver(如果有)——
    靠binding.bound_*快照欄位(_resolve_bound_driver_target)解析要拆
    哪裡,不是即時欄位,因為使用者可能在建立driver之後又改了
    target_object/data_name/bone_name等欄位,這時即時欄位已經指向新
    目標,沒辦法回推原本綁在哪裡(見properties.TargetBinding.bound_target_type
    等欄位定義處的完整說明——這是真實踩過的孤兒driver bug,不是預防性
    寫法)。不論有沒有真的找到driver可拆,執行完都會清空快照,代表
    「這筆binding目前沒有任何已知綁定」。"""
    target = _resolve_bound_driver_target(binding)
    if target is not None:
        id_data, data_path, array_index = target
        try:
            if array_index == -1:
                id_data.driver_remove(data_path)
            else:
                id_data.driver_remove(data_path, array_index)
        except Exception:
            pass
    _clear_bound_driver_snapshot(binding)


def add_driver(binding, empty, transform_type, travel):
    """幫binding(一筆TargetBinding)在empty(Handle)的transform_type軸上
    綁一個SCRIPTED driver,把Handle在[-travel, travel]的局部座標線性映射到
    [binding.min_val, binding.max_val](invert時交換)。transform_type/travel
    由呼叫端(bind_drivers)依item.control_style決定——1D樣式固定
    transform_type='LOC_Y'、travel=HANDLE_TRAVEL;XY_2D兩軸分別用
    'LOC_X'/'LOC_Y'、travel=PAD_TRAVEL(travel距離不一樣,不能沿用
    HANDLE_TRAVEL寫死在算式裡,否則XY_2D的線性映射範圍會算錯)。"""
    target = resolve_driver_target(binding)
    if target is None:
        # 即時欄位解析不出有效目標(例如target_object被清空)——仍然要
        # 呼叫remove_driver()清掉「上一次」可能綁在別的目標上的舊driver,
        # 不能因為新目標無效就放著舊driver不管,變成孤兒(見remove_driver
        # 的說明)。
        remove_driver(binding)
        return False
    id_data, data_path, array_index = target

    # 先移除上一次實際綁定的舊driver(可能在別的目標上),避免重複/孤兒
    remove_driver(binding)

    if array_index == -1:
        fcurve = id_data.driver_add(data_path)
    else:
        fcurve = id_data.driver_add(data_path, array_index)

    drv = fcurve.driver
    drv.type = 'SCRIPTED'
    for v in list(drv.variables):
        drv.variables.remove(v)
    var = drv.variables.new()
    var.name = "slider"
    var.type = 'TRANSFORMS'
    t = var.targets[0]
    t.id = empty
    t.transform_type = transform_type
    t.transform_space = 'LOCAL_SPACE'

    # Shape Key的value有自己的slider_min/slider_max(面板上那條滑桿的顯示
    # 範圍,預設0~1),跟這裡的min_val/max_val是兩件不同的事:driver算出來的
    # 值不會被slider_min/max限制(照樣能把value設到範圍外),只是Shape Key
    # 面板上的滑桿看起來卡住不動,容易讓使用者誤以為驅動沒生效。這裡撐開
    # (只放寬、不縮小,避免覆蓋使用者可能刻意設得更寬的範圍)slider_min/max
    # 讓它至少能容納min_val/max_val,兩者才會一致。用未經invert交換的
    # binding.min_val/max_val(真實數值範圍),不是下面拿去組表達式、可能已經
    # 交換過的lo/hi。
    if binding.target_type == 'SHAPE_KEY':
        id_data.slider_min = min(id_data.slider_min, binding.min_val)
        id_data.slider_max = max(id_data.slider_max, binding.max_val)

    lo, hi = binding.min_val, binding.max_val
    if binding.invert:
        lo, hi = hi, lo

    # 把Handle在 [-travel, travel] 的位置線性映射到 [lo, hi]
    drv.expression = (
        f"(slider + {travel}) / {2 * travel} * ({hi} - ({lo})) + ({lo})"
    )

    # driver確實建立完成後才存快照——之後使用者改target_object/data_name
    # 時,remove_driver()靠這份快照才知道要回去哪裡拆掉這個driver。
    _snapshot_bound_driver_target(binding)
    return True


def bind_drivers(item, empty):
    """依item.control_style把該裝的driver都裝上,回傳是否全部綁定成功。
    1D樣式只需要target_bindings[0]成功(固定驅動Handle局部Y,不管視覺上
    是直向還是橫向);XY_2D需要[0](局部X)、[1](局部Y)都成功才算完整
    綁定。travel距離跟create_slider_widgets設定LIMIT_LOCATION時用的是
    同一個值,兩處都是依control_style是否為XY_2D決定PAD_TRAVEL或
    HANDLE_TRAVEL,保持一致(driver算式的映射範圍要跟Handle實際能拖到的
    範圍一致,不然會出現「拖到底但數值還沒到min/max」的落差)。"""
    axes = axes_for(item.control_style)
    travel = PAD_TRAVEL if item.control_style == 'XY_2D' else HANDLE_TRAVEL
    ok = True
    for i, transform_type in enumerate(axes):
        binding = properties.get_binding(item, i)
        if not add_driver(binding, empty, transform_type, travel):
            ok = False
    return ok


def unbind_drivers(item):
    """移除item目前*所有*target_bindings筆數對應的driver,不是只清目前
    control_style需要的軸數——這樣切換成軸數較少的樣式(例如XY_2D改回
    LINEAR_1D)時,原本Y軸綁定的driver也會被清乾淨,不會留著指向已刪除
    Handle的壞driver。至於target_bindings本身的內容不清除,方便使用者
    切回去時綁定設定還在。"""
    for binding in item.target_bindings:
        remove_driver(binding)
