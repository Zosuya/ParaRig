"""N面板UI:分組清單 + 滑桿清單UIList + 詳細設定/生成按鈕的Panel。"""

from bpy.app.translations import pgettext_iface as _
from bpy.types import Panel, UIList, Menu

from . import icons
from . import rig_builder
from . import properties
from .properties import group_display_name


class SLIDERRIG_UL_groups(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        layout.prop(item, "name", text="", emboss=False, icon='OUTLINER_COLLECTION')


def _group_filter_mask(items, scene):
    """回傳一個布林list,對應items裡每一筆是否要顯示。抽成不依賴UIList實例的
    純函式,是因為`UIList`沒辦法在無介面的headless模式下直接建立實例測試——
    這個函式本身(篩選的實際邏輯)才是真正需要驗證正確性的部分,`filter_items`
    只是把結果轉成Blender的bitflag格式,風險很低。

    預設(不勾選slider_rig_show_all_groups)就先篩選到目前選中的分組,勾選
    後才顯示所有分組——跟這個布林欄位剛加入時的邏輯正好相反(當時預設不
    篩選,勾選才篩選到單一分組),使用者要求把預設行為換成「先過濾」。"""
    if scene.slider_rig_show_all_groups:
        return [True] * len(items)
    groups = scene.slider_groups
    g_idx = scene.slider_group_index
    if not (0 <= g_idx < len(groups)):
        # 沒有有效的選中分組時,篩選開關形同虛設,不隱藏任何項目(避免使用者
        # 還沒選分組時清單整個變空白,以為功能壞了)
        return [True] * len(items)
    active_uid = groups[g_idx].uid
    return [item.group_uid == active_uid for item in items]


def _active_item(scene):
    """回傳目前應該顯示在下方詳細設定區塊的滑桿項目——沒有選取、索引超出
    範圍、或目前作用中的項目被分組篩選(_group_filter_mask)隱藏時一律
    回傳None,讓詳細設定區塊維持空白。不能只檢查index是否落在
    scene.slider_rig_items的有效範圍內就直接拿item來顯示——那是對「整個
    未篩選collection」的index,篩選(顯示所有分組的滑桿關閉時)只是隱藏
    UIList裡的列,不會連動清掉slider_rig_index,所以選到分組內沒有任何
    滑桿時,detail box原本還是會照樣顯示上一次選中、屬於別的分組的滑桿
    資料(真實bug,使用者回報)。"""
    items = scene.slider_rig_items
    idx = scene.slider_rig_index
    if not (0 <= idx < len(items)):
        return None
    mask = _group_filter_mask(items, scene)
    if not mask[idx]:
        return None
    return items[idx]


def _target_object_names(item):
    """回傳item每一軸binding的目標物件名稱清單,沒設定/還沒初始化的軸顯示
    「—」占位——跟_data_names()是同一種「逐軸收集、缺值用—補位」的模式,
    拆成兩個函式只是分別對應target_object跟data_name兩個不同欄位。
    TEXT_LABEL沒有任何軸(axes_for()回傳空tuple),不驅動任何目標,回傳
    單一「—」而不是空list——避免清單這一欄看起來像空白/資料遺失,跟其他
    樣式「有軸但還沒設定」的—占位視覺上一致。"""
    axes = rig_builder.axes_for(item.control_style)
    if not axes:
        return ["—"]
    names = []
    for i in range(len(axes)):
        binding = properties.peek_binding(item, i)
        if binding and binding.target_object:
            names.append(binding.target_object.name)
        else:
            names.append("—")
    return names



def _data_names(item):
    axes = rig_builder.axes_for(item.control_style)
    if not axes:
        return ["—"]
    names = []
    for i in range(len(axes)):
        binding = properties.peek_binding(item, i)
        if binding and binding.data_name:
            names.append(binding.data_name)
        else:
            names.append("—")
    return names


class SLIDERRIG_UL_items(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        scene = context.scene
        row = layout.row(align=True)
        # 還沒生成過(generated_empty是空的)維持原本的圓點,單純標示「尚未
        # 生成」;已經生成過的改顯示這個滑桿control_style對應的內建Blender
        # icon(icons.builtin_icon_for()),讓清單一眼能看出每個滑桿是哪種
        # 類型,不用展開細節框才知道。這裡用內建icon(icon=字串enum)而不是
        # template_icon_view選擇器那份自訂縮圖(icon_value=int)——自訂縮圖
        # 是為大格子選擇器手繪的,線條在UIList這種小尺寸下太細、辨識度不夠,
        # 內建icon是Blender官方針對這個尺寸設計的。
        if item.generated_empty:
            row.prop(
                item, "name", text="", emboss=False,
                icon=icons.builtin_icon_for(item.control_style),
            )
        else:
            row.prop(item, "name", text="", emboss=False, icon='DOT')
        if scene.slider_rig_show_col_group:
            row.label(text=group_display_name(scene, item.group_uid))
        if scene.slider_rig_show_col_target_object:
            row.label(text=" / ".join(_target_object_names(item)))
        if scene.slider_rig_show_col_data_name:
            row.label(text=" / ".join(_data_names(item)))
        # 每一列自己的show_label快速開關——不用先選取這一列才能切換(選取
        # 後另有一份放在清單下方的常駐列,見_draw_sliders_page,兩處操作
        # 同一個底層欄位,不會資料不同步)。TEXT_LABEL沒有show_label的
        # 意義(文字本身就是內容),這裡不畫。icon依目前開關狀態切換
        # 實心/空心的字型圖示,讓使用者不用先點開才知道目前是開是關。
        if item.control_style != 'TEXT_LABEL':
            row.prop(
                item, "show_label", text="",
                icon='OUTLINER_OB_FONT' if item.show_label else 'FONT_DATA',
                emboss=False,
            )

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        mask = _group_filter_mask(items, context.scene)
        flags = [self.bitflag_filter_item if show else 0 for show in mask]
        return flags, []


def _draw_target_binding(layout, binding):
    """畫一組完整的目標綁定設定(目標類型→目標物件→依類型分支的bone/
    shape key欄位→數值範圍→反轉)。抽成獨立函式是因為1D樣式只需要畫一次
    (對item.target_bindings[0]),XY_2D需要對[0]、[1]各畫一次、分別放進
    「X軸目標」「Y軸目標」兩個區塊——同一段UI邏輯,只是呼叫次數/對象不同,
    不應該複製貼上兩份。"""
    layout.prop(binding, "target_type")
    layout.prop(binding, "target_object")

    if binding.target_type == 'BONE_LOC':
        if binding.target_object and binding.target_object.type == 'ARMATURE':
            layout.prop_search(binding, "bone_name", binding.target_object.pose, "bones")
        else:
            layout.label(text=_("Please specify an Armature object first"), icon='ERROR')
        layout.prop(binding, "bone_axis")
    elif binding.target_type == 'SHAPE_KEY':
        if binding.target_object and binding.target_object.data and getattr(binding.target_object.data, "shape_keys", None):
            layout.prop_search(binding, "data_name", binding.target_object.data.shape_keys, "key_blocks", text="Shape Key")
        else:
            layout.prop(binding, "data_name")
    else:
        layout.prop(binding, "data_name")

    row = layout.row(align=True)
    row.prop(binding, "min_val")
    row.prop(binding, "max_val")
    layout.prop(binding, "invert")


# 選擇滑桿項目所屬分組的下拉選單。取代prop_search——SliderRigItem.group_uid
# 存的是分組的uid而不是name字串,prop_search只能顯示/寫入某個collection項目
# 的name本身,沒辦法「顯示name、寫入另一個欄位」,所以分組選擇改成這個menu
# 搭配sliderrig.set_item_group operator。
#
# 這段刻意用一般註解而不是docstring——Blender會把Menu/Operator類別的
# docstring直接當成使用者滑鼠停留時顯示的tooltip,內部開發筆記(為什麼
# 不用prop_search之類)會整段外洩給使用者看到。
class SLIDERRIG_MT_group_picker(Menu):
    bl_idname = "SLIDERRIG_MT_group_picker"
    bl_label = "Select Group"

    def draw(self, context):
        layout = self.layout
        groups = context.scene.slider_groups
        if not groups:
            layout.label(text=_("No groups created yet"), icon='ERROR')
            return
        for group in groups:
            layout.operator(
                "sliderrig.set_item_group", text=group.name
            ).group_uid = group.uid


class SLIDERRIG_PT_item_columns_filter(Panel):
    """滑桿清單的欄位顯示篩選器——用layout.popover()彈出的小面板,勾選要不要
    顯示分組/目標物件/資料名稱欄。「名稱」欄本身兼作選取/重新命名該列的
    主要欄位,不開放關閉,所以這裡只列另外三個。"""
    bl_idname = "SLIDERRIG_PT_item_columns_filter"
    bl_label = "Show Columns"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_options = {'INSTANCED'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.prop(scene, "slider_rig_show_col_group")
        layout.prop(scene, "slider_rig_show_col_target_object")
        layout.prop(scene, "slider_rig_show_col_data_name")


def _draw_groups_page(layout, scene):
    """畫「分組」頁的內容:分組清單(比照Bone Collections的操作手感)+
    選中分組的專屬設定(是否顯示外框、綁定骨骼/物體、對齊視角)。從
    SLIDERRIG_PT_panel.draw()拆出來,單純是把原本擠在同一頁的兩大塊
    (分組/滑桿)拆成兩個各自獨立的函式,靠scene.slider_rig_active_page
    切換要畫哪一塊,不是Blender原生的分頁機制(那需要各自獨立的
    bl_category)。"""
    row = layout.row()
    row.template_list(
        "SLIDERRIG_UL_groups", "", scene, "slider_groups",
        scene, "slider_group_index", rows=3,
    )
    col = row.column(align=True)
    col.operator("sliderrig.add_group", icon='ADD', text="")
    col.operator("sliderrig.remove_group", icon='REMOVE', text="")
    col.separator()
    col.operator("sliderrig.move_group", icon='TRIA_UP', text="").direction = 'UP'
    col.operator("sliderrig.move_group", icon='TRIA_DOWN', text="").direction = 'DOWN'

    # 選中分組的專屬設定:是否顯示外框、綁定骨骼/物體。跟滑桿頁選中滑桿
    # 項目顯示詳細設定是同一種UI模式,只是欄位對象換成SliderGroupItem。
    groups = scene.slider_groups
    g_idx = scene.slider_group_index
    if groups and 0 <= g_idx < len(groups):
        group = groups[g_idx]
        gbox = layout.box()
        gbox.prop(group, "show_frame")
        name_label_row = gbox.row(align=True)
        name_label_row.prop(group, "show_name_label")
        sub = name_label_row.row(align=True)
        sub.enabled = group.show_name_label
        sub.prop(group, "name_label_size", text="")
        gbox.prop(group, "target_object")
        if group.target_object and group.target_object.type == 'ARMATURE':
            gbox.prop_search(group, "bone_name", group.target_object.pose, "bones")
        # 手動對齊視角:跟generate()新建Frame時的一次性view-facing對齊
        # 是同一套計算,差別是這個隨時可以對「已經生成過」的Frame重新
        # 套用,不用整個Clear+Generate。
        gbox.operator(
            "sliderrig.align_frame_to_view", icon='CAMERA_DATA',
            text=_("Align Panel to Current View"),
        )


def _draw_sliders_page(layout, scene):
    """畫「滑桿」頁的內容:排布編輯按鈕、篩選列、滑桿清單、選中滑桿的
    詳細設定(樣式選擇器+目標綁定)。從SLIDERRIG_PT_panel.draw()拆出來,
    說明見_draw_groups_page。"""
    # 排布編輯(sliderrig.edit_grid_layout)只依賴目前選中的分組
    # (scene.slider_group_index),不依賴選中哪個滑桿項目,所以放在清單
    # 上方、跟單一滑桿的詳細設定box分開,對「這個分組底下所有滑桿」的
    # 排版一次編輯,不用先選單一項目才找得到這個按鈕。
    layout.operator("sliderrig.edit_grid_layout", icon='GRID', text=_("Edit Layout"))

    filter_row = layout.row(align=True)
    filter_row.prop(scene, "slider_rig_show_all_groups", text=_("Show Sliders From All Groups"))
    filter_row.popover("SLIDERRIG_PT_item_columns_filter", text="", icon='FILTER')

    row = layout.row()
    row.template_list(
        "SLIDERRIG_UL_items", "", scene, "slider_rig_items",
        scene, "slider_rig_index", rows=4,
    )
    col = row.column(align=True)
    col.operator("sliderrig.add_item", icon='ADD', text="")
    col.operator("sliderrig.remove_item", icon='REMOVE', text="")
    col.separator()
    col.operator("sliderrig.move_item", icon='TRIA_UP', text="").direction = 'UP'
    col.operator("sliderrig.move_item", icon='TRIA_DOWN', text="").direction = 'DOWN'

    item = _active_item(scene)

    # 名稱/快速開關/分組這三項放在細節設定box外、跟box平級——不要把
    # 「純滑桿設定」(名稱、分組歸屬)跟「樣式/目標綁定」這種比較複雜的
    # 設定擠在同一個box裡,拉高常用欄位的可見度。順序是名稱→快速開關→
    # 分組,名稱前面留一個separator()跟上面清單拉開一點距離。
    if item is not None:
        layout.separator()
        layout.prop(item, "name")

        # 清單下方的快速開關:不用展開下面的詳細設定box就能直接切換
        # 目前選中滑桿的名稱標籤顯示——item.show_label原本只能在細節框
        # 最下面才調得到(見下方TEXT_LABEL以外分支的label_row),搬一份
        # 常駐在清單正下方提高可見度/降低操作步驟。細節框裡原本的
        # show_label控制項維持不動(不是搬移、是額外複製一份在更顯眼的
        # 位置),兩處操作的是同一個底層欄位,不會有資料不同步的問題。
        # TEXT_LABEL沒有show_label這個開關的意義(文字本身就是內容,見
        # 下方該分支的說明),這個樣式時這排索性不畫,避免顯示一個點了
        # 沒作用的欄位。
        if item.control_style != 'TEXT_LABEL':
            quick_label_row = layout.row(align=True)
            quick_label_row.prop(item, "show_label", text=_("Show Name Label"))
            quick_label_sub = quick_label_row.row(align=True)
            quick_label_sub.enabled = item.show_label
            quick_label_sub.prop(item, "label_size", text="")

        layout.menu(
            "SLIDERRIG_MT_group_picker",
            text=group_display_name(scene, item.group_uid),
            icon='OUTLINER_COLLECTION',
        )

        box = layout.box()
        # 圖示式選擇器(仿造Bone Widget等rigging addon常見的shape
        # picker):平常顯示目前選中樣式的縮圖,點下去彈出一個縮圖網格
        # 讓使用者直接點選,取代純文字下拉選單。縮圖本身在icons.py
        # 用bpy.utils.previews程式產生,不依賴外部圖片檔案。
        box.template_icon_view(item, "control_style", show_labels=True)

        if item.control_style == 'TEXT_LABEL':
            # 純文字沒有可拖拽的控制器本體,也不驅動任何target_bindings
            # (axes_for('TEXT_LABEL')是空tuple)——完全跳過目標綁定
            # 區塊。文字內容沿用item.name(上面layout.prop(item, "name")
            # 那欄已經在編輯了,不需要另開一個欄位),字型大小沿用
            # label_size/label_size_raw(跟其他樣式的名稱標籤共用同一組
            # 欄位),但這裡沒有「開關」的意義(文字本身就是內容,不是
            # 額外附加的標籤),所以只畫大小欄,不畫show_label開關。
            box.prop(item, "label_size", text=_("Text Size"))
        else:
            # 目標綁定:1D樣式只需要一組(target_bindings[0]),XY_2D需要
            # X/Y兩組獨立的綁定,各自用一個子box區隔、標示是哪一軸——見
            # rig_builder.axes_for()/CONTROL_STYLE_AXES,新增更多軸的樣式
            # 這裡不用改,自動照軸數畫出對應數量的區塊。
            #
            # 用peek_binding(唯讀),不能用get_binding——Panel.draw()是
            # Blender的唯讀RNA context,呼叫get_binding內部的
            # collection.add()會直接丟AttributeError('Writing to ID
            # classes in this context is not allowed')(真實bug,使用者在
            # N-panel切換control_style時實際觸發)。target_bindings補長度
            # 的時機在_add_item(新增item時)跟
            # properties._on_control_style_changed(切換樣式時)這兩個
            # 允許寫入的地方做,draw()這裡只負責讀,理論上binding一定已經
            # 存在;仍然防呆處理None的情況,避免舊資料或極端情況下面板
            # 直接壞掉。
            axes = rig_builder.axes_for(item.control_style)
            axis_labels = {'LOC_X': 'X', 'LOC_Y': 'Y', 'LOC_Z': 'Z'}
            if len(axes) == 1:
                binding = properties.peek_binding(item, 0)
                if binding is not None:
                    _draw_target_binding(box, binding)
                else:
                    box.label(text=_("Target settings not initialized yet — please refresh the panel"), icon='INFO')
            else:
                for i, transform_type in enumerate(axes):
                    abox = box.box()
                    axis = axis_labels.get(transform_type, transform_type)
                    abox.label(text=_("{axis} Axis Target").format(axis=axis))
                    binding = properties.peek_binding(item, i)
                    if binding is not None:
                        _draw_target_binding(abox, binding)
                    else:
                        abox.label(text=_("Target settings not initialized yet — please refresh the panel"), icon='INFO')

            label_row = box.row(align=True)
            label_row.prop(item, "show_label")
            sub = label_row.row(align=True)
            sub.enabled = item.show_label
            sub.prop(item, "label_size", text="")


class SLIDERRIG_PT_panel(Panel):
    bl_label = "ParaRig"
    bl_idname = "SLIDERRIG_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "ParaRig"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # 生成/清除按鈕維持在面板最上面、兩頁共用——這兩個是使用者最常用、
        # 且不管目前在哪一頁/清單內容改到哪都要按的操作,放最上面不用每次
        # 都往下捲才按得到,也不該因為切到分組頁就看不到。
        # 有任一滑桿已經生成過(generated_empty不是None),代表這次按下去是
        # 「更新」既有的rig(非破壞性upsert,見operators.py),不是從零開始
        # 生成;按鈕文字/icon依這個狀態動態調整,operator本身的行為不變。
        already_generated = any(item.generated_empty for item in scene.slider_rig_items)
        generate_label = _("Update Slider Rig") if already_generated else _("Generate Slider Rig")
        generate_icon = 'FILE_REFRESH' if already_generated else 'PLAY'
        layout.operator("sliderrig.generate", text=generate_label, icon=generate_icon)
        layout.operator("sliderrig.clear", text=_("Clear Generated Sliders"), icon='TRASH')
        layout.separator()

        # 分組/滑桿頁籤切換——用prop_enum畫成左右並排的兩顆切換鈕(原生
        # Blender手感,像Image Editor的Paint/UV模式切換),不是彈出式選單:
        # 只有兩個選項時,平常就能看到兩邊、點哪邊都只是一次點擊,不需要
        # 多一層選單彈出/收合的互動成本。狀態存在scene.slider_rig_active_page
        # (scene層級,不是window_manager),讓使用者上次停留的頁面在切換
        # 場景/存檔重開後還記得,不會每次都跳回預設頁。
        #
        # 原本兩塊內容(分組/滑桿)是上下疊在同一頁,整個面板很長、常用的
        # 滑桿設定要一路往下捲才看得到;拆成兩頁之後每一頁都只有自己那塊,
        # 不用捲動。
        page_row = layout.row(align=True)
        page_row.prop_enum(scene, "slider_rig_active_page", 'GROUPS', text=_("Group"))
        page_row.prop_enum(scene, "slider_rig_active_page", 'SLIDERS', text=_("Sliders"))
        layout.separator()

        if scene.slider_rig_active_page == 'GROUPS':
            _draw_groups_page(layout, scene)
        else:
            _draw_sliders_page(layout, scene)


classes = (
    SLIDERRIG_UL_groups,
    SLIDERRIG_UL_items,
    SLIDERRIG_MT_group_picker,
    SLIDERRIG_PT_item_columns_filter,
    SLIDERRIG_PT_panel,
)
