"""N面板UI:分組清單 + 滑桿清單UIList + 詳細設定/生成按鈕的Panel。"""

from bpy.app.translations import pgettext_iface as _
from bpy.types import Panel, UIList, Menu

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
        row.prop(
            item, "name", text="", emboss=False,
            icon='CON_LOCLIMIT' if item.generated_empty else 'DOT'
        )
        if scene.slider_rig_show_col_group:
            row.label(text=group_display_name(scene, item.group_uid))
        if scene.slider_rig_show_col_target_object:
            row.label(text=" / ".join(_target_object_names(item)))
        if scene.slider_rig_show_col_data_name:
            row.label(text=" / ".join(_data_names(item)))

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


class SLIDERRIG_MT_group_picker(Menu):
    """選擇滑桿項目所屬分組的下拉選單。取代prop_search——SliderRigItem.group_uid
    存的是分組的uid而不是name字串,prop_search只能顯示/寫入某個collection項目
    的name本身,沒辦法「顯示name、寫入另一個欄位」,所以分組選擇改成這個menu
    搭配sliderrig.set_item_group operator。"""
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


class SLIDERRIG_PT_panel(Panel):
    bl_label = "ParaRig"
    bl_idname = "SLIDERRIG_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "ParaRig"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # 生成/清除按鈕移到面板最上面——這兩個是使用者最常用、且不管清單
        # 內容改到哪都要按的操作,放最上面不用每次都往下捲才按得到。
        # 有任一滑桿已經生成過(generated_empty不是None),代表這次按下去是
        # 「更新」既有的rig(非破壞性upsert,見operators.py),不是從零開始
        # 生成;按鈕文字/icon依這個狀態動態調整,operator本身的行為不變。
        already_generated = any(item.generated_empty for item in scene.slider_rig_items)
        generate_label = _("Update Slider Rig") if already_generated else _("Generate Slider Rig")
        generate_icon = 'FILE_REFRESH' if already_generated else 'PLAY'
        layout.operator("sliderrig.generate", text=generate_label, icon=generate_icon)
        layout.operator("sliderrig.clear", text=_("Clear Generated Sliders"), icon='TRASH')
        layout.separator()

        # --- 分組(Groups)清單:比照Bone Collections的操作手感 -------------------
        # 標題置中+跟清單之間留一點空隙,用來跟上面的生成/清除按鈕跟下面
        # 的清單本身做出視覺區隔——box包一層是取得置中對齊的最簡單做法
        # (layout.label本身沒有alignment參數,alignment是row/box這層的
        # 屬性)。
        header = layout.box().row()
        header.alignment = 'CENTER'
        header.label(text=_("Groups"))
        layout.separator(factor=0.5)
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

        # 選中分組的專屬設定:是否顯示外框、綁定骨骼/物體。跟下面選中滑桿
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

        layout.separator()

        # --- 滑桿清單 ------------------------------------------------------------
        # 標題置中+上下留空隙,跟上面的分組區塊/下面的清單本身做視覺區隔,
        # 手法跟上面「分組 (Groups)」標題一致。
        header = layout.box().row()
        header.alignment = 'CENTER'
        header.label(text=_("Sliders"))
        layout.separator(factor=0.5)

        filter_row = layout.row(align=True)
        filter_row.prop(scene, "slider_rig_show_all_groups", text=_("Show Sliders From All Groups"))
        filter_row.popover("SLIDERRIG_PT_item_columns_filter", text="", icon='FILTER')

        # 排布編輯(sliderrig.edit_grid_layout)只依賴目前選中的分組
        # (scene.slider_group_index),不依賴選中哪個滑桿項目,所以放在清單
        # 上方、跟單一滑桿的詳細設定box分開,對「這個分組底下所有滑桿」的
        # 排版一次編輯,不用先選單一項目才找得到這個按鈕。
        layout.operator("sliderrig.edit_grid_layout", icon='GRID', text=_("Edit Layout"))

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
        if item is not None:
            box = layout.box()
            box.prop(item, "name")
            box.menu(
                "SLIDERRIG_MT_group_picker",
                text=group_display_name(scene, item.group_uid),
                icon='OUTLINER_COLLECTION',
            )
            # 圖示式選擇器(仿造Bone Widget等rigging addon常見的shape
            # picker):平常顯示目前選中樣式的縮圖,點下去彈出一個縮圖網格
            # 讓使用者直接點選,取代純文字下拉選單。縮圖本身在icons.py
            # 用bpy.utils.previews程式產生,不依賴外部圖片檔案。
            box.template_icon_view(item, "control_style", show_labels=True)

            if item.control_style == 'TEXT_LABEL':
                # 純文字沒有可拖拽的控制器本體,也不驅動任何target_bindings
                # (axes_for('TEXT_LABEL')是空tuple)——完全跳過目標綁定
                # 區塊。文字內容沿用item.name(上面box.prop(item, "name")
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


classes = (
    SLIDERRIG_UL_groups,
    SLIDERRIG_UL_items,
    SLIDERRIG_MT_group_picker,
    SLIDERRIG_PT_item_columns_filter,
    SLIDERRIG_PT_panel,
)
