"""滑桿清單的資料模型:scene.slider_rig_items(CollectionProperty of SliderRigItem)。"""

import bpy
from bpy.props import (
    StringProperty, FloatProperty, EnumProperty, PointerProperty, BoolProperty, IntProperty,
    CollectionProperty,
)
from bpy.types import PropertyGroup

TARGET_TYPE_ITEMS = [
    ('SHAPE_KEY', 'Shape Key', ''),
    ('CUSTOM_PROP', 'Custom Property', ''),
    ('BONE_LOC', 'Bone Location', ''),
]

AXIS_ITEMS = [('X', 'X', ''), ('Y', 'Y', ''), ('Z', 'Z', '')]

# 「樣式」= 控制器的行為類型(不是語意化的臉部部位清單)。
# 每種樣式要驅動幾個目標軸(對應SliderRigItem.target_bindings第幾筆)
# 由rig_builder.CONTROL_STYLE_AXES決定,新增樣式時要記得去那裡登記一筆。
CONTROL_STYLE_ITEMS = [
    ('LINEAR_1D', '1-Axis Slider (Vertical)', "Linear slider dragged along the Track's local Y axis"),
    ('LINEAR_1D_HORIZONTAL', '1-Axis Slider (Horizontal)',
     "Linear slider dragged along the Track's local X axis (visually horizontal)"),
    ('XY_2D', '2-Axis Drag Pad (XY)', "Free-drag on a plane; X/Y each map to their own independent target"),
    ('TEXT_LABEL', 'Text Label',
     "Displays only text (the item's name); generates no draggable control and drives no target"),
]


class TargetBinding(PropertyGroup):
    """一組完整的驅動目標設定:目標類型+物件+資料名稱/骨骼/軸向+數值範圍+
    反轉。SliderRigItem.target_bindings存一個這個型別的collection,每一筆
    對應這個item的control_style需要驅動的其中一個Handle局部軸——1D樣式
    只用得到第0筆,XY_2D用到第0、1筆,依序對應哪個transform_type由
    rig_builder.CONTROL_STYLE_AXES/axes_for()決定,這裡不重複那份對照表。
    欄位定義原封不動搬自舊版直接放在SliderRigItem上的同名欄位。"""
    target_type: EnumProperty(name="Target Type", items=TARGET_TYPE_ITEMS, default='SHAPE_KEY')
    target_object: PointerProperty(name="Target Object", type=bpy.types.Object)
    bone_name: StringProperty(name="Bone Name", description="Used when Target Type is Bone Location")
    data_name: StringProperty(name="Data Name", description="Shape Key name, or custom property name")
    bone_axis: EnumProperty(name="Bone Axis", items=AXIS_ITEMS, default='Y')
    min_val: FloatProperty(name="Min Value", default=0.0)
    max_val: FloatProperty(name="Max Value", default=1.0)
    invert: BoolProperty(name="Invert", default=False)

    # 上一次rig_builder.add_driver()成功建立driver時,實際使用的目標欄位
    # 快照(內部欄位,不在UI顯示)。存在的理由:remove_driver()必須知道
    # 「原本綁在哪裡」才拆得掉driver,但使用者隨時可以在建立driver之後
    # 改上面那幾個即時欄位(target_object/data_name/bone_name等),改完
    # 之後即時欄位已經指向新目標,沒有任何辦法回推舊目標——只有這份改動
    # 前留下的快照知道。沒有這份快照的話,改綁目標會讓舊目標上的driver
    # 永久殘留成孤兒,連Clear都清不掉(真實踩過的bug,不是預防性寫法)。
    #
    # bound_target_object用PointerProperty(不是存物件名稱字串)——物件被
    # 改名時PointerProperty會自動跟著,存名稱字串則會在改名後對不上而
    # 找不到要拆的driver,等於又繞回同一個孤兒問題。
    #
    # bound_target_type/bound_bone_axis刻意用StringProperty而不是跟即時
    # 欄位一樣的EnumProperty:這兩個欄位純粹是內部快照,不需要UI下拉選單,
    # 而且空字串(EnumProperty沒有這個狀態)正好可以表示「目前沒有任何
    # 已知綁定」,不用另外開一個布林旗標維護同一件事。
    bound_target_type: StringProperty(default="")
    bound_target_object: PointerProperty(type=bpy.types.Object)
    bound_data_name: StringProperty(default="")
    bound_bone_name: StringProperty(default="")
    bound_bone_axis: StringProperty(default="")


def get_binding(item, axis_index):
    """回傳item.target_bindings第axis_index筆,不夠長就自動補到有(新增
    空白TargetBinding,不動/不清除已存在的筆數)。

    只能在允許寫入ID資料的context呼叫(Operator的execute()、update
    callback)——**不能在Panel.draw()/UIList.draw_item()裡呼叫**,那些是
    唯讀RNA context,呼叫collection.add()會直接丟`AttributeError:
    Writing to ID classes in this context is not allowed`(真實bug,
    使用者在N-panel切換control_style時觸發)。draw()裡一律用下面唯讀的
    peek_binding。target_bindings實際補長度的時機是`_add_item`(新item
    建立時)和`_on_control_style_changed`(切換樣式需要更多軸時),不是
    面板讀取的當下。"""
    while len(item.target_bindings) <= axis_index:
        item.target_bindings.add()
    return item.target_bindings[axis_index]


def peek_binding(item, axis_index):
    """唯讀版本:collection長度不夠時回傳None,不會新增。Panel.draw()/
    UIList.draw_item()這些唯讀RNA context一律要用這個,不能用
    get_binding——那些context裡呼叫collection.add()會直接丟例外(見
    get_binding的說明),不只是「不該有副作用」的風格問題。"""
    bindings = item.target_bindings
    return bindings[axis_index] if axis_index < len(bindings) else None


class SliderGroupItem(PropertyGroup):
    """獨立管理的分組清單(比照Bone Collections的操作手感)。滑桿項目用`group_uid`
    (見SliderRigItem)參照這裡的`uid`,不是name字串——改名這裡的`name`不會讓
    已指派的滑桿失效,因為它們存的識別碼跟name完全無關。"""
    name: StringProperty(name="Group Name", default="New Group")
    # 內部識別碼,建立時產生一次(見operators._add_group)、之後不再變動,
    # 不在UI顯示。SliderRigItem.group_uid存的就是這個值。
    uid: StringProperty(default="")
    # Group層級設定:讓整個group(Frame)跟著場景裡某根骨骼/物體走。
    # target_object為空代表不綁定;非空且是Armature且bone_name也填了才是
    # 綁定到骨骼,否則是綁定到target_object本身的origin——不用額外的
    # target_type欄位區分,靠這兩個既有欄位的狀態組合推斷即可。
    target_object: PointerProperty(
        name="Bound Object", type=bpy.types.Object,
        description="Makes this group's Frame follow this object (or the bone specified below); "
        "leave empty to not bind"
    )
    bone_name: StringProperty(
        name="Bound Bone", default="",
        description="When the bound object is an Armature, specifies which bone to follow; "
        "leave empty to follow the object's own origin"
    )
    # 這個分組要不要生成Frame的矩形外框視覺。關掉時Frame物件本身依然存在
    # (Track/Handle照舊parent到它、CHILD_OF constraint照舊掛在它身上),
    # 只是不生成外框mesh——這樣「綁定又不要外框」不需要額外的定位物件。
    show_frame: BoolProperty(
        name="Show Frame Outline", default=True,
        description="When off, this group's Frame won't generate a visible rectangular outline, but "
        "the Frame object itself is still created (to hold layout and bindings); sliders inside are "
        "unaffected"
    )
    # 分組名稱標籤(Text Mesh):顯示在Frame外框正上方,幫助辨識畫面上多個
    # 分組面板各自是誰——跟每個滑桿自己的show_label是同一種UI模式,但這是
    # 分組層級、顯示分組名稱、位置基準是Frame的真實量測外框範圍(見
    # rig_builder.sync_group_label),不是格子系統。
    show_name_label: BoolProperty(
        name="Show Group Name", default=False,
        description="Displays the group's name (as a Text Mesh) directly above this group's Frame outline"
    )
    # name_label_size的底層真實值(直接餵給curve.size,單位跟其他幾何常數
    # 一致)。不在UI顯示,使用者只透過下面的name_label_size(get/set包一層
    # *1000顯示轉換)看到/輸入這個欄位——跟SliderRigItem.label_size/
    # label_size_raw是同一套模式,原本這裡固定用mesh_builders.GROUP_LABEL_SIZE
    # 常數(0.06),使用者要求分組名稱標籤也要能個別調整大小,不再是全域
    # 共用的固定值。
    name_label_size_raw: FloatProperty(default=0.06, min=0.001)

    def _get_name_label_size(self):
        return self.name_label_size_raw

    def _set_name_label_size(self, value):
        self.name_label_size_raw = value

    # UI上顯示/輸入的是底層真實值的1000倍,跟SliderRigItem.label_size
    # 同樣的顯示層轉換,理由一致:量級對齊(0.06這種小數不好直接讓使用者
    # 輸入),get/set各自只做一次*1000//1000,避免轉換邏輯分散兩處維護。
    name_label_size: FloatProperty(
        name="Group Name Text Size", default=0.06 * 1000, min=0.001 * 1000,
        get=lambda self: self._get_name_label_size() * 1000,
        set=lambda self, value: self._set_name_label_size(value / 1000),
    )
    generated_label: PointerProperty(name="Generated Group Name Label Object", type=bpy.types.Object)


def get_group_by_uid(scene, uid):
    """依uid在scene.slider_groups裡找對應的SliderGroupItem,找不到回傳None
    (uid是空字串,或指向的分組已經被刪除)。"""
    if not uid:
        return None
    for group in scene.slider_groups:
        if group.uid == uid:
            return group
    return None


def group_display_name(scene, uid):
    """給UI顯示用:依uid查目前的分組名稱,查不到就顯示提示字串而不是空白
    (讓使用者知道這個滑桿的分組連結失效了,例如分組被刪除)。"""
    group = get_group_by_uid(scene, uid)
    return group.name if group else "(No Group Assigned)"


def _on_group_changed(self, context):
    """使用者透過下拉選單把這個滑桿改指派到別的分組時,如果它目前的
    (grid_x, grid_y)剛好跟新分組裡的其他滑桿撞在一起,自動挪到新分組裡
    grid_x最大值之後,避免之後generate()因為座標衝突直接被拒絕。如果座標
    沒有撞到就不動,不會無故洗掉使用者已經排好的位置。"""
    items = context.scene.slider_rig_items
    same_group = [
        it for it in items
        if it.group_uid == self.group_uid and it.as_pointer() != self.as_pointer()
    ]
    if any(it.grid_x == self.grid_x and it.grid_y == self.grid_y for it in same_group):
        max_x = max((it.grid_x for it in same_group), default=-1)
        self.grid_x = max_x + 1
        self.grid_y = 0


def _on_show_label_changed(self, context):
    """開啟/關閉名稱標籤會讓這個item的佔用格數改變(cells_for在show_label
    為True時height_cells+1),原本排得剛好的版面可能因此重疊。這裡在屬性
    改變的當下就自動把重疊推開,而不是等到使用者按下「生成滑桿綁定」才
    用find_grid_conflicts擋下來報錯——那時候使用者看到的是一個抽象的
    座標衝突訊息,而且排布編輯畫布上看起來還是「正常的」(畫布只在拖曳
    當下檢查衝突,不會主動標示既存資料的重疊),兩邊說法不一致很困惑
    (真實bug,使用者回報)。

    推開規則見grid_layout.resolve_overlaps:離格子原點(0,0)較遠的那個
    讓開,連鎖被壓到的item沿用同一個offset一起移動。"""
    from . import grid_layout
    items = context.scene.slider_rig_items
    group_items = [it for it in items if it.group_uid == self.group_uid]
    grid_layout.resolve_overlaps(group_items)


def _on_control_style_changed(self, context):
    """切換control_style後,立刻把target_bindings補到這個樣式需要的長度
    (呼叫get_binding,會視需要新增空白TargetBinding)。

    這件事不能留到面板draw()第一次讀取binding時才順便長出來(原本的設計
    就是這樣做,而且_draw_target_binding也確實只在draw()裡被呼叫)——
    Blender的Panel.draw()是唯讀RNA context,在裡面呼叫collection.add()
    這種會寫入ID資料的操作,實際在Blender UI操作時會直接丟
    `AttributeError: Writing to ID classes in this context is not
    allowed`(真實bug,使用者在N-panel切換control_style時觸發),不是理論
    風險。update callback則是安全的寫入時機——跟上面_on_group_changed/
    _on_show_label_changed是同一個模式,這兩個既有callback也都會寫入
    (其他item的)屬性,而且從沒出過事,證明這個時機點是安全的。
    面板draw()那邊改用唯讀的peek_binding,不再依賴get_binding的自動
    成長副作用。"""
    from . import rig_builder
    axes = rig_builder.axes_for(self.control_style)
    for i in range(len(axes)):
        get_binding(self, i)


def _control_style_items_callback(self, context):
    """control_style欄位的動態items callback,委派給icons.py組出帶
    icon_value的清單——放在這裡(而不是直接在EnumProperty()呼叫裡寫
    lambda)是為了讓函式本身有名字,方便追蹤;deferred import icons是
    避免icons.py/properties.py互相import造成的模組載入順序問題(icons.py
    自己也會deferred import properties.py取CONTROL_STYLE_ITEMS)。"""
    from . import icons
    return icons.control_style_enum_items()


class SliderRigItem(PropertyGroup):
    name: StringProperty(name="Slider Name", default="New Slider")
    # 存目標SliderGroupItem的uid,不是name字串——分組改名不會讓這個連結
    # 失效。UI上沒有直接的prop_search可以顯示name但寫入uid,因此分組選擇
    # 改用自訂選單(panels.SLIDERRIG_MT_group_picker + operators裡對應的
    # set_item_group operator)取代,不能再用bpy.types.UILayout.prop_search。
    group_uid: StringProperty(name="Group", default="", update=_on_group_changed)
    grid_x: IntProperty(
        name="Grid X", default=0,
        description="The top-left grid coordinate (horizontal) of this control's occupied area; larger "
        "values are further right. Numbers may be skipped to leave gaps. Actual cell footprint depends "
        "on the control style (see grid_layout.py)"
    )
    grid_y: IntProperty(
        name="Grid Y", default=0,
        description="The top-left grid coordinate (vertical) of this control's occupied area; larger "
        "values are further down. Actual cell footprint depends on the control style (see grid_layout.py)"
    )
    # 驅動目標的完整設定(目標類型/物件/資料名稱/數值範圍/反轉等,見
    # TargetBinding)拆到子PropertyGroup、存成collection而不是直接開一排
    # 平行欄位——1D樣式只用得到第0筆,XY_2D用到第0、1筆,以後如果有更多
    # 軸的樣式,不用再回頭改這裡的欄位定義,只要rig_builder.CONTROL_STYLE_AXES
    # 多登記一筆。不要直接存取這個collection,一律透過properties.get_binding/
    # peek_binding存取,確保「還沒長到那個索引」的情況被一致地處理。
    target_bindings: CollectionProperty(type=TargetBinding)
    # items用動態callback(不是直接傳CONTROL_STYLE_ITEMS這個靜態list),
    # 是為了讓每個選項帶自訂縮圖(icon_value),搭配panels.py用
    # template_icon_view()畫成像Bone Widget那種可點選的圖示網格,而不是
    # 純文字下拉選單——見icons.control_style_enum_items()的完整說明,
    # 包含「動態items不能用default參數」這個Blender限制的因應方式。
    control_style: EnumProperty(
        name="Control Style", items=_control_style_items_callback,
        update=_on_control_style_changed,
    )
    generated_empty: PointerProperty(name="Generated Object", type=bpy.types.Object)
    # 名稱標籤(Text Mesh):顯示在Track上方,方便使用者辨認。show_label是
    # per-item開關,關掉的話這個滑桿不生成標籤。
    show_label: BoolProperty(
        name="Show Name Label", default=False, update=_on_show_label_changed
    )
    # label_size的底層真實值(直接餵給curve.size,單位跟其他幾何常數
    # 一致,量級是0.01~0.1這種小數)。不在UI顯示,使用者只透過下面的
    # label_size(get/set包一層*1000顯示轉換)看到/輸入這個欄位。
    label_size_raw: FloatProperty(default=0.05, min=0.001)

    def _get_label_size(self):
        return self.label_size_raw

    def _set_label_size(self, value):
        self.label_size_raw = value

    # UI上顯示/輸入的是底層真實值的1000倍(例如底層0.02顯示成20),純粹是
    # 顯示層轉換——rig_builder.sync_label()讀的還是這個屬性,取到的還是
    # get()回傳的原始小數,不用改任何下游程式碼。get/set各自只做一次
    # /1000、*1000,避免顯示值跟底層值的轉換邏輯分散在兩處各自維護一份。
    label_size: FloatProperty(
        name="Label Text Size", default=0.05 * 1000, min=0.001 * 1000,
        get=lambda self: self._get_label_size() * 1000,
        set=lambda self, value: self._set_label_size(value / 1000),
    )
    generated_label: PointerProperty(name="Generated Label Object", type=bpy.types.Object)


classes = (
    # TargetBinding是SliderRigItem.target_bindings的元素型別,nested
    # PropertyGroup必須先註冊,SliderRigItem的CollectionProperty(type=
    # TargetBinding)才能成立。
    TargetBinding,
    SliderGroupItem,
    SliderRigItem,
)
