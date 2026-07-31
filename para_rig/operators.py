"""清單增刪/排序操作子,以及生成/清除滑桿的Operator入口。實際的物件建構
邏輯在rig_builder.py,格數/衝突偵測邏輯在grid_layout.py——這裡只負責串接。
"""

import uuid

import bpy
from bpy.props import FloatProperty, EnumProperty
from bpy.types import Operator
from mathutils import Vector

from . import rig_builder
from . import grid_canvas
from .grid_layout import (
    cells_for, cell_center_local_xy, find_grid_conflicts,
    items_overlapping_at, swap_item_positions, swap_would_conflict, CONTROL_STYLE_CELLS,
)
from .mesh_builders import FRAME_MARGIN, LABEL_SIDE_MARGIN
from .properties import group_display_name, get_group_by_uid, get_binding

MOVE_DIRECTION_ITEMS = [('UP', 'Up', ''), ('DOWN', 'Down', '')]


def _move_in_collection(collection, index, direction):
    """把collection[index]往上/下移一格(比照Bone Collections等內建清單的
    ▲▼按鈕手感,Blender沒有開放真正的拖拽排序API)。已經在邊界就不動。
    回傳移動後(或未移動)的index。"""
    new_index = index - 1 if direction == 'UP' else index + 1
    if 0 <= new_index < len(collection):
        collection.move(index, new_index)
        return new_index
    return index


class SLIDERRIG_OT_add_item(Operator):
    bl_idname = "sliderrig.add_item"
    bl_label = "新增滑桿項目"

    def execute(self, context):
        scene = context.scene
        groups = scene.slider_groups
        # 分組欄位預填成Groups清單目前反白的那一筆;清單是空的話就先新增一個
        # 分組再帶入它的uid,避免新滑桿的group_uid指向一個不存在的分組
        if len(groups) == 0:
            new_group = groups.add()
            new_group.uid = uuid.uuid4().hex
            new_group.name = "Group_1"
            scene.slider_group_index = 0
            group_uid = new_group.uid
        else:
            group_idx = min(max(scene.slider_group_index, 0), len(groups) - 1)
            group_uid = groups[group_idx].uid

        items = scene.slider_rig_items
        item = items.add()
        item.name = f"Slider_{len(items)}"
        item.group_uid = group_uid
        new_idx = len(items) - 1
        # 自動接在同一個分組裡目前佔用範圍最右側之後,避免新項目一生成就跟
        # 既有項目的佔用格子重疊。用「佔用格子右界」而不是單純grid_x最大值
        # +1:如果最後一個項目是佔2格寬的橫向樣式,grid_x+1會落在它自己
        # 佔用的第二格裡,還是會衝突,必須加上它實際的width_cells。
        same_group_items = [
            items[i] for i in range(len(items))
            if i != new_idx and items[i].group_uid == item.group_uid
        ]
        if same_group_items:
            right_edges = [
                it.grid_x + cells_for(it.control_style, it.show_label)[0]
                for it in same_group_items
            ]
            item.grid_x = max(right_edges)
        else:
            item.grid_x = 0
        item.grid_y = 0
        # 新item預設control_style='LINEAR_1D'是欄位定義的預設值,不是透過
        # 一次真正的屬性賦值設進去的,不會觸發_on_control_style_changed
        # update callback(collection.add()產生的初始預設值不會經過RNA的
        # set路徑)。這裡明確補一次binding[0],確保面板一打開就能填目標
        # 設定,不用等使用者手動切一次control_style或按過一次生成才長出
        # 這筆資料。這裡是Operator.execute(),寫入ID資料是安全的context。
        get_binding(item, 0)
        scene.slider_rig_index = new_idx
        return {'FINISHED'}


class SLIDERRIG_OT_remove_item(Operator):
    bl_idname = "sliderrig.remove_item"
    bl_label = "移除滑桿項目"

    def execute(self, context):
        items = context.scene.slider_rig_items
        idx = context.scene.slider_rig_index
        if 0 <= idx < len(items):
            # 先清掉這筆項目已生成的Handle/Track,避免刪除清單項目後
            # 這些物件變成場景裡沒人參照的孤兒
            rig_builder.remove_generated_empty(items[idx])
            items.remove(idx)
            context.scene.slider_rig_index = max(0, idx - 1)
        return {'FINISHED'}


class SLIDERRIG_OT_move_item(Operator):
    bl_idname = "sliderrig.move_item"
    bl_label = "移動滑桿項目"

    direction: EnumProperty(items=MOVE_DIRECTION_ITEMS)

    def execute(self, context):
        scene = context.scene
        scene.slider_rig_index = _move_in_collection(
            scene.slider_rig_items, scene.slider_rig_index, self.direction
        )
        return {'FINISHED'}


class SLIDERRIG_OT_edit_grid_layout(Operator):
    """在3D Viewport疊一層可拖曳的網格畫布,取代直接打grid_x/grid_y數字的
    排版方式。只顯示/操作目前選中分組(scene.slider_group_index)底下的
    滑桿項目——不同分組的格子座標系統各自獨立,混在同一張畫布上編輯沒有
    意義。拖曳/互換/擴充的結果直接寫回item.grid_x/grid_y,不接Undo。"""
    bl_idname = "sliderrig.edit_grid_layout"
    bl_label = "編輯排版"
    bl_description = "在3D Viewport裡用拖曳的方式調整所選分組內滑桿的格子位置"

    _handle = None

    def modal(self, context, event):
        context.area.tag_redraw()
        scene = context.scene
        group_items = [
            it for it in scene.slider_rig_items
            if it.group_uid == grid_canvas.state["group_uid"]
        ]

        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                mx, my = event.mouse_region_x, event.mouse_region_y

                direction = grid_canvas.plus_button_at(mx, my)
                if direction is not None:
                    grid_canvas.expand_grid(direction)
                    return {'RUNNING_MODAL'}

                clicked = grid_canvas.item_rect_at(context, mx, my)
                if clicked is not None:
                    # 按下當下就在方塊上,直接進入拖曳,不需要先點選一次。
                    # 記錄「滑鼠所在格 - item左上角格」的偏移量,拖曳判斷
                    # 固定以item自己的左上角格跟隨滑鼠,不是把滑鼠當下懸停
                    # 的格子直接當成新錨點——否則按在方塊中間/邊緣等不同
                    # 位置去拖,item會在按下當下產生跳動,且2x1/1x2這類
                    # 多格item的移動範圍會被錯誤地少算掉。
                    press_gx, press_gy = grid_canvas.px_to_cell(mx, my)
                    grid_canvas.state["dragging"] = clicked
                    grid_canvas.state["drag_offset"] = (
                        press_gx - clicked.grid_x, press_gy - clicked.grid_y
                    )
                    grid_canvas.state["drag_target"] = (clicked.grid_x, clicked.grid_y)
                elif grid_canvas.in_grid_window(mx, my):
                    # 沒點到任何item,但落在格子視窗範圍內的空白處:進入
                    # 平移模式。格子總數沒超過視窗大小時_pan_bounds()範圍是
                    # (0,0)~(0,0),平移量夾限後永遠不變,等同這個功能自然
                    # 不啟用,不需要另外判斷「是否超過DEFAULT_GRID_CELLS」。
                    grid_canvas.begin_pan(mx, my)

            elif event.value == 'RELEASE':
                if grid_canvas.state["panning"]:
                    grid_canvas.end_pan()
                    return {'RUNNING_MODAL'}

                dragged = grid_canvas.state["dragging"]
                target = grid_canvas.state["drag_target"]
                if dragged is not None and target is not None:
                    gx, gy = target
                    # 用item移動後「完整footprint」去檢查重疊,不能只看
                    # 滑鼠落點單一格——2x1/1x2這類多格item移到新錨點後,
                    # 另外佔用的格子也可能跟別人撞在一起,只查落點那一格
                    # 會漏掉(先前bug:橫向item被放到跟兩個直向item都
                    # 重疊的位置,因為只檢查了落點格,沒檢查它另一半)。
                    overlapping = items_overlapping_at(group_items, dragged, gx, gy)
                    if not overlapping:
                        dragged.grid_x = gx
                        dragged.grid_y = gy
                    elif len(overlapping) == 1:
                        # 剛好跟單一item重疊:互換座標。多個item重疊時
                        # 互換沒有明確語意,一律擋下退回原位(不寫入)。
                        # 互換前必須先驗證「換過去之後」雙方的新footprint
                        # 不會彼此重疊、也不會撞到第三方——形狀不同的
                        # 兩個item(1x2 vs 2x1)單純交換錨點可能產生新的
                        # 重疊,不檢查就寫入等於繞過拖曳的衝突防護。
                        other = overlapping[0]
                        if not swap_would_conflict(group_items, dragged, other):
                            swap_item_positions(dragged, other)
                grid_canvas.state["dragging"] = None
                grid_canvas.state["drag_target"] = None
                grid_canvas.state["drag_offset"] = (0, 0)

        elif event.type == 'MOUSEMOVE' and grid_canvas.state["panning"]:
            grid_canvas.update_pan(event.mouse_region_x, event.mouse_region_y)

        elif event.type == 'MOUSEMOVE' and grid_canvas.state["dragging"] is not None:
            mouse_gx, mouse_gy = grid_canvas.px_to_cell(
                event.mouse_region_x, event.mouse_region_y
            )
            offset_x, offset_y = grid_canvas.state["drag_offset"]
            # item左上角錨點 = 滑鼠所在格 - 按下當下記錄的偏移量,而不是
            # 直接把滑鼠所在格當成錨點——這樣不管按下時抓的是方塊哪個
            # 部位,拖曳過程item跟手的相對位置都保持一致,不會用「滑鼠格」
            # 本身去對邊界做clamp(那樣夾限的其實是滑鼠位置,不是item左上
            # 角實際會落在哪一格,對2x1/1x2這類多格item來說會少算掉可以
            # 移動的範圍,導致某些方向明明還有空間卻被擋住無法移動)。
            gx = mouse_gx - offset_x
            gy = mouse_gy - offset_y
            # 夾限範圍要扣掉這個item自己的footprint寬高(用cells_for,含
            # show_label多佔的標籤格),不能統一用cols-1/rows-1(那是給
            # 1x1item用的),也不能只用CONTROL_STYLE_CELLS(不含標籤格)——
            # 否則2x1/1x2的item,或開了show_label多一列的item,會被允許
            # 拖到「左上角落點合法,但footprint其餘部分超出網格範圍」的
            # 位置,畫面上就會看到方塊懸空跑出橘色外框。
            dragged = grid_canvas.state["dragging"]
            width_cells, height_cells = cells_for(dragged.control_style, dragged.show_label)
            gx = max(0, min(grid_canvas.state["cols"] - width_cells, gx))
            gy = max(0, min(grid_canvas.state["rows"] - height_cells, gy))
            grid_canvas.state["drag_target"] = (gx, gy)

        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            SLIDERRIG_OT_edit_grid_layout.remove_handle_if_active()
            context.area.tag_redraw()
            return {'CANCELLED'}

        # 滾輪/中鍵平移縮放視角放行給Blender本體處理,減少「被卡住」的感覺
        if event.type in {'LEFTMOUSE', 'MOUSEMOVE'}:
            return {'RUNNING_MODAL'}
        return {'PASS_THROUGH'}

    @classmethod
    def remove_handle_if_active(cls):
        """移除目前掛著的draw_handler(如果有的話)。除了modal內部ESC/右鍵
        結束時呼叫,__init__.unregister()也會呼叫這個——避免add-on被停用/
        重載時,modal還開著導致殘留一個指向已卸載程式碼的draw_handler。"""
        if cls._handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(cls._handle, 'WINDOW')
            cls._handle = None

    def invoke(self, context, event):
        if context.area.type != 'VIEW_3D':
            self.report({'WARNING'}, "請在3D Viewport裡執行")
            return {'CANCELLED'}

        scene = context.scene
        groups = scene.slider_groups
        g_idx = scene.slider_group_index
        if not (0 <= g_idx < len(groups)):
            self.report({'WARNING'}, "請先在Groups清單裡選取一個分組")
            return {'CANCELLED'}

        grid_canvas.reset_for_group(context, groups[g_idx].uid)

        # 保險起見:如果上一輪操作還沒正常結束就留著handle,這裡先清掉
        # 再掛新的一份,避免重複執行造成畫面疊層。
        SLIDERRIG_OT_edit_grid_layout.remove_handle_if_active()
        SLIDERRIG_OT_edit_grid_layout._handle = bpy.types.SpaceView3D.draw_handler_add(
            grid_canvas.draw_callback, (), 'WINDOW', 'POST_PIXEL'
        )
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}


class SLIDERRIG_OT_set_item_group(Operator):
    """把目前選中的滑桿項目指派到某個分組;由panels.SLIDERRIG_MT_group_picker
    選單呼叫,取代原本的prop_search(prop_search只能顯示/寫入name字串,無法
    顯示name但寫入group_uid,所以分組選擇改成這個menu+operator的組合)。"""
    bl_idname = "sliderrig.set_item_group"
    bl_label = "指派分組"
    bl_options = {'INTERNAL'}

    group_uid: bpy.props.StringProperty()

    def execute(self, context):
        scene = context.scene
        items = scene.slider_rig_items
        idx = scene.slider_rig_index
        if 0 <= idx < len(items):
            items[idx].group_uid = self.group_uid
        return {'FINISHED'}


class SLIDERRIG_OT_add_group(Operator):
    bl_idname = "sliderrig.add_group"
    bl_label = "新增分組"

    def execute(self, context):
        groups = context.scene.slider_groups
        group = groups.add()
        group.uid = uuid.uuid4().hex
        group.name = f"Group_{len(groups)}"
        context.scene.slider_group_index = len(groups) - 1
        return {'FINISHED'}


class SLIDERRIG_OT_remove_group(Operator):
    bl_idname = "sliderrig.remove_group"
    bl_label = "移除分組"
    bl_description = (
        "只移除Groups清單裡的這一筆,不會動到已經指派這個分組的滑桿項目"
        "(它們的group_uid仍然指向這個已刪除的uid,UI上會顯示「未指定分組」,"
        "generate()會把它們視為一個獨立的、看不到名稱的分組——之後如果要"
        "重新指派,得手動幫它們選一個新分組)"
    )

    def execute(self, context):
        groups = context.scene.slider_groups
        idx = context.scene.slider_group_index
        if 0 <= idx < len(groups):
            groups.remove(idx)
            context.scene.slider_group_index = max(0, idx - 1)
        return {'FINISHED'}


class SLIDERRIG_OT_move_group(Operator):
    bl_idname = "sliderrig.move_group"
    bl_label = "移動分組"

    direction: EnumProperty(items=MOVE_DIRECTION_ITEMS)

    def execute(self, context):
        scene = context.scene
        scene.slider_group_index = _move_in_collection(
            scene.slider_groups, scene.slider_group_index, self.direction
        )
        return {'FINISHED'}


class SLIDERRIG_OT_align_frame_to_view(Operator):
    """把目前選中分組的Frame外框旋轉,重新對齊到目前3D視窗的視角——用跟
    generate()新建Frame時同一套計算(rig_builder.view_facing_rotation),
    差別在於generate()的view-facing對齊只在Frame「新建」當下套用一次,
    upsert流程刻意不去動既有Frame的旋轉(保護使用者可能已經手動Rotate過
    的朝向,見CLAUDE.md)。這個operator反過來是使用者主動要求的動作:
    Frame已經生成過、視角轉了想重新對齊時用,不用整個Clear+Generate。"""
    bl_idname = "sliderrig.align_frame_to_view"
    bl_label = "將此面板對準當前視圖"
    bl_description = "把目前選中分組的Frame外框旋轉,正面朝向目前3D視窗的視角"

    def execute(self, context):
        scene = context.scene
        groups = scene.slider_groups
        g_idx = scene.slider_group_index
        if not (0 <= g_idx < len(groups)):
            self.report({'WARNING'}, "請先在Groups清單裡選取一個分組")
            return {'CANCELLED'}
        group = groups[g_idx]
        frame = rig_builder.find_existing_frame(group.uid)
        if frame is None:
            self.report({'WARNING'}, "這個分組還沒有生成過Frame,請先按「生成滑桿綁定」")
            return {'CANCELLED'}
        face_rotation = rig_builder.view_facing_rotation(context)
        if face_rotation is None:
            self.report({'WARNING'}, "請在3D Viewport裡執行(找不到目前視角)")
            return {'CANCELLED'}
        frame.rotation_euler = face_rotation.to_euler()
        return {'FINISHED'}


class SLIDERRIG_OT_generate(Operator):
    bl_idname = "sliderrig.generate"
    bl_label = "生成滑桿綁定"
    bl_description = "依照清單資料自動生成滑桿控制器與Driver"

    spacing_x: FloatProperty(default=0.12)
    spacing_y: FloatProperty(default=0.2)

    def execute(self, context):
        scene = context.scene
        items = scene.slider_rig_items
        if not items:
            self.report({'WARNING'}, "尚未新增任何滑桿項目")
            return {'CANCELLED'}

        # 用group_uid分組,不是分組的name字串——name可能重複或曾經重複過,
        # uid才是穩固的識別碼。group_labels只用來組Frame物件名稱/錯誤訊息,
        # 純顯示用途,不參與「這幾筆滑桿算不算同一組」的判斷。
        groups = {}
        group_labels = {}
        for item in items:
            groups.setdefault(item.group_uid, []).append(item)
        for group_uid in groups:
            group_labels[group_uid] = group_display_name(scene, group_uid)

        # 格子佔用範圍衝突就整個取消生成,不生成一半、也不讓物件疊在一起。
        # 用佔用格數(見grid_layout.py)判斷,不只是起點座標相同——不同
        # control_style佔用的格數不一樣,座標不同也可能實際重疊。
        conflicts = find_grid_conflicts(groups, group_labels)
        if conflicts:
            self.report({'ERROR'}, "格子座標衝突,已取消生成:" + "; ".join(conflicts))
            return {'CANCELLED'}

        collection = rig_builder.ensure_slider_collection(context.scene)

        # 非破壞性(upsert):不再無條件砍掉重建每個Frame/Track/Handle,只清
        # 掉「現在已經不再對應任何滑桿/分組」的孤兒物件,以及Track/Handle的
        # 孤兒mesh data快取(addon程式碼更新過形狀/比例常數時,場景裡同名的
        # 舊mesh data不會自動跟著換掉,必須主動清除,確保新建的物件一定是照
        # 當下程式碼建立幾何——只影響「新建」分支,既有物件保留的mesh data
        # 不受影響,因為它們是直接在原地重算geometry,不是重新抓快取)。
        rig_builder.remove_orphan_frames(set(groups.keys()))
        for mesh in list(bpy.data.meshes):
            if mesh.users == 0 and (
                mesh.name == "SliderTrackData"
                or mesh.name == "SliderPadTrackData"
                or mesh.name == "SliderEmptyTrackData"
                or mesh.name.startswith("SliderHandleData_")
            ):
                bpy.data.meshes.remove(mesh)
        rig_builder.remove_stray_root()  # 舊版曾經生成過全域SliderRig_Root,現在架構不再用它

        # 只有新建的Frame會套用這個一次性view-facing對齊;既有Frame保留
        # 使用者可能已經手動Rotate過的朝向,不會被這裡覆寫(見rig_builder裡
        # create_slider_frame與update_frame_mesh的分工)。headless背景模式
        # 沒有3D視窗,face_rotation會是None,新建的Frame也維持原本躺平朝向不變。
        face_rotation = rig_builder.view_facing_rotation(context)

        failed = []
        # 第一個全新分組的起始位置改成3D游標(scene.cursor.location),不再
        # 固定寫死在世界原點——這樣使用者可以先把3D游標移到想要的位置再按
        # 生成,滑桿面板就會出現在那裡。只影響「本來就沒有Frame、要新建」
        # 的起點;後續分組疊加、以及既有Frame的位置完全不受影響(見下方
        # cursor的累加邏輯,既有Frame一律讀它自己實際的frame.location)。
        cursor = scene.cursor.location.copy()
        for group_uid, group_items in groups.items():
            group = get_group_by_uid(scene, group_uid)
            # group為None代表這個分組已經被刪除(見_remove_group的說明:滑桿
            # 的group_uid不會被清掉),show_frame預設顯示外框、沒有綁定目標
            show_frame = group.show_frame if group else True

            existing_frame = rig_builder.find_existing_frame(group_uid)
            if existing_frame is not None:
                frame = existing_frame
            else:
                # 全新的分組:才會走預設排版位置+一次性view-facing對齊。
                # 尺寸先給(0,0,0,0)(暫定),生成完這個group底下所有Track/
                # Handle/Label之後,會依它們的真實bound_box重新mesh一次
                # ——Frame的最終尺寸不再靠格子數估算,見下方
                # measure_group_extent。
                frame = rig_builder.create_slider_frame(
                    group_uid, group_labels[group_uid],
                    (0.0, 0.0, 0.0, 0.0), collection, face_rotation, show_frame
                )
                frame.location = cursor

            if group is not None:
                rig_builder.sync_frame_binding(frame, group)

            group_tracks = []
            for item in group_items:
                # 以Frame中心為基準置中(依佔用格子聯集邊界的中心,不是座標
                # 範圍中心),讓滑桿分佈跟Frame外框的置中方式一致。
                x, y = cell_center_local_xy(item, group_items)

                if rig_builder.can_keep_existing_widgets(item):
                    # 保留Handle:使用者目前拖出來的數值(=局部座標)完全不碰,
                    # 只更新Track的排版位置(Track本來就鎖死,每次都是照當下
                    # 算出來的座標走,不存在「使用者手動調過Track」的情況)。
                    track = item.generated_empty.parent
                    track.location = (x, y, 0)
                    track.parent = frame
                else:
                    # Handle不存在:整個重建,舊物件如果還在就先清掉,新Handle
                    # 從局部原點(0,0,0)開始。
                    rig_builder.remove_generated_empty(item)
                    track, empty = rig_builder.create_slider_widgets(item, (x, y, 0), collection)
                    track.parent = frame
                    item.generated_empty = empty

                rig_builder.sync_text_label_content(item)
                rig_builder.sync_label(item, track, collection)
                group_tracks.append(track)
                if item.generated_label:
                    group_tracks.append(item.generated_label)
                group_tracks.append(item.generated_empty)

                if not rig_builder.bind_drivers(item, item.generated_empty):
                    failed.append(item.name)

            # 所有Track/Handle/Label都生成完之後,才動態量測這個group底下
            # 這些子物件在Frame local space的真實幾何邊界(見
            # rig_builder.measure_group_extent的完整說明)——取代先前用
            # grid_layout格子數估算Frame尺寸的作法,不再需要為了標籤文字
            # 實際佔用範圍去猜測/校正偏移公式,Frame永遠精準包住實際內容。
            #
            # 四邊各自套用margin,不是統一的FRAME_MARGIN——標籤永遠往
            # cell_center_local_xy的+Y方向(格子系統的「上」)伸出,只要這
            # group裡有任一item開啟show_label,上緣就用LABEL_SIDE_MARGIN
            # (比FRAME_MARGIN窄,因為文字視覺上比控制器本體稀疏,不需要
            # 一樣寬的緩衝),其餘三邊維持FRAME_MARGIN。Frame局部原點仍是
            # cell_center_local_xy()置中Track的基準,不受這裡mesh邊界是否
            # 對稱影響。
            min_x, max_x, min_y, max_y = rig_builder.measure_group_extent(frame, group_tracks)
            top_margin = LABEL_SIDE_MARGIN if any(it.show_label for it in group_items) else FRAME_MARGIN
            extent = (
                min_x - FRAME_MARGIN, max_x + FRAME_MARGIN,
                min_y - FRAME_MARGIN, max_y + top_margin,
            )
            rig_builder.update_frame_mesh(frame, extent, show_frame)
            # 分組名稱標籤(顯示在Frame外框正上方)也要在extent量測/margin
            # 套用完之後才能算位置——跟Frame外框mesh本身用同一份extent,
            # 不是另外用格子數估算。group為None(分組已被刪除)時沒有名稱
            # 可顯示,直接跳過,既有標籤(如果之前有生成過)留給
            # remove_orphan_frames清理。
            if group is not None:
                rig_builder.sync_group_label(group, frame, collection, extent)

            # 累加這個Frame實際佔用的高度(而不是用「index * 固定間距」),
            # 避免某個分組因為grid_y用了多列而變高時,疊到下一個Frame身上。
            # 用frame.location(既有Frame讀它實際所在的位置,新建的Frame則是
            # 剛設好的cursor)當起點繼續往下推算,這樣即使使用者手動搬動過
            # 某個Frame,後面新加入的分組還是接在它實際的位置之後,不會跟
            # 已存在、位置被使用者調整過的Frame重疊。疊加方向沿著這個Frame
            # 自己目前的局部Y軸(而不是固定的世界Y軸)查詢,讓面板轉向後,
            # 下一個Frame仍然疊在「螢幕空間的下方」。這段移到量測Frame
            # 真實尺寸之後,才能用上剛量出來的邊界。總高度用
            # extent[3]-extent[2](非對稱邊界的實際跨距),不是
            # 2*frame_half_height(那假設了對稱)。
            local_down = frame.rotation_euler.to_matrix() @ Vector((0, -1, 0))
            frame_total_height = extent[3] - extent[2]
            cursor = frame.location + local_down * (frame_total_height + self.spacing_y)

        if failed:
            self.report(
                {'WARNING'},
                f"以下項目找不到目標,已生成滑桿但未綁定Driver: {', '.join(failed)}"
            )
        else:
            self.report({'INFO'}, f"已生成 {len(items)} 個滑桿並完成綁定")
        return {'FINISHED'}


class SLIDERRIG_OT_clear(Operator):
    bl_idname = "sliderrig.clear"
    bl_label = "清除已生成的滑桿"
    bl_description = "刪除所有已生成的滑桿物件(Driver會一併移除)"

    def execute(self, context):
        items = context.scene.slider_rig_items
        for item in items:
            rig_builder.remove_generated_empty(item)
        rig_builder.remove_all_slider_frames()
        rig_builder.remove_stray_root()
        coll = bpy.data.collections.get(rig_builder.SLIDER_COLLECTION_NAME)
        if coll and len(coll.objects) == 0:
            bpy.data.collections.remove(coll)
        # Track/Handle的mesh是共用快取(見mesh_builders._ensure_track_mesh/
        # _ensure_handle_mesh),remove_generated_empty()故意不清它們(可能還
        # 有其他滑桿在用同一份)。所有物件都刪完的這個時間點,它們理論上
        # 一定已經變成0-user,一併清掉,避免.blend檔案裡累積用不到的mesh資料。
        for mesh in list(bpy.data.meshes):
            if mesh.users == 0 and (
                mesh.name == "SliderTrackData"
                or mesh.name == "SliderPadTrackData"
                or mesh.name == "SliderEmptyTrackData"
                or mesh.name.startswith("SliderHandleData_")
            ):
                bpy.data.meshes.remove(mesh)
        # 共用UI材質(SliderRigUI)同理:所有Frame/Track/Handle/Label共用同一份,
        # 不能像mesh/curve那樣在個別物件被刪除時順便清——那時候材質可能
        # 還被其他還存在的物件(或它們的mesh/curve datablock)用著。要等上面
        # 的mesh都清完、材質真的變成0-user孤兒,才適合清掉。
        ui_mat = bpy.data.materials.get(rig_builder.SLIDER_UI_MATERIAL_NAME)
        if ui_mat and ui_mat.users == 0:
            bpy.data.materials.remove(ui_mat)
        return {'FINISHED'}


classes = (
    SLIDERRIG_OT_add_item,
    SLIDERRIG_OT_remove_item,
    SLIDERRIG_OT_move_item,
    SLIDERRIG_OT_edit_grid_layout,
    SLIDERRIG_OT_set_item_group,
    SLIDERRIG_OT_add_group,
    SLIDERRIG_OT_remove_group,
    SLIDERRIG_OT_move_group,
    SLIDERRIG_OT_align_frame_to_view,
    SLIDERRIG_OT_generate,
    SLIDERRIG_OT_clear,
)
