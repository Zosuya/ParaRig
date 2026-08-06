bl_info = {
    "name": "ParaRig",
    "author": "Zosuya",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "View3D > N-Panel > ParaRig",
    "description": "Auto-generates draggable slider controls and binds them via Drivers to "
    "Shape Keys / custom properties / bone locations",
    "category": "Rigging",
    "license": "SPDX:GPL-3.0-or-later",
}

import bpy
from bpy.props import CollectionProperty, IntProperty, BoolProperty, EnumProperty

from . import icons
from . import preferences
from . import properties
from . import operators
from . import panels
from . import translations

classes = preferences.classes + properties.classes + operators.classes + panels.classes


def register():
    # icons.register()要在其他東西之前跑——control_style的EnumProperty用
    # 動態items callback(icons.control_style_enum_items())取縮圖icon_value,
    # 這個callback實際被呼叫的時間點雖然是UI真的要畫出來才觸發(不是
    # class註冊當下),但縮圖本身(bpy.utils.previews collection)最好在
    # 整個addon開始運作前就先備好,不要留有任何「已經註冊完但圖示還沒
    # 生成」的空窗期。
    icons.register()
    for cls in classes:
        bpy.utils.register_class(cls)
    # 翻譯表要在register_class之後才註冊——bpy.app.translations是把翻譯
    # 套用在"已經註冊好的RNA屬性"上(bl_label/Property的name=/description=
    # 等),順序反過來的話Blender在這個時間點還找不到對應的屬性可套用。
    translations.register()
    bpy.types.Scene.slider_rig_items = CollectionProperty(type=properties.SliderRigItem)
    bpy.types.Scene.slider_rig_index = IntProperty(default=0)
    bpy.types.Scene.slider_groups = CollectionProperty(type=properties.SliderGroupItem)
    bpy.types.Scene.slider_group_index = IntProperty(default=0)
    # N面板分成「分組」/「滑桿」兩頁,靠這個欄位切換目前顯示哪一頁——
    # 兩頁共用同一個Panel.draw(),不是Blender原生的分頁機制(那需要各自
    # 獨立的bl_category/獨立的N面板頁籤),單純是draw()裡的if/else,狀態
    # 存在scene層級(不是window_manager),原因跟其他既有UI狀態
    # (slider_rig_show_all_groups等)一致:切換場景、存檔重開,使用者
    # 上次停留的頁面預期會被記住,不是每次都跳回預設頁。
    # "Group"/"Groups"這兩個字,Blender自己的核心翻譯目錄(不是這個addon
    # 的翻譯表)已經有zh_HANT翻譯("群組",來自Vertex Groups等內建功能)——
    # 跟這個addon翻譯表裡任何登記同一個msgid的譯文撞在一起時,查表結果會
    # 被Blender核心翻譯目錄蓋過去。這裡刻意不迴避這個撞碰,直接沿用
    # "Group"這個字面值,讓zh_HANT使用者看到Blender核心目錄提供的「群組」
    # ——語意上也算合理(這個頁籤本來就是在管理「分組」這件事),不需要
    # 為了避開撞碰另外造一個複合字。
    bpy.types.Scene.slider_rig_active_page = EnumProperty(
        name="Active Page",
        items=[
            ('GROUPS', 'Group', 'Show group settings and the Groups list'),
            ('SLIDERS', 'Sliders', 'Show slider settings and the Sliders list'),
        ],
        default='GROUPS',
    )
    bpy.types.Scene.slider_rig_show_all_groups = BoolProperty(
        name="Show Sliders From All Groups", default=False,
        description="When off, the slider list only shows sliders belonging to the group currently "
        "selected in the Groups list; when on, sliders from every group are shown"
    )
    # 滑桿清單的欄位顯示開關——「名稱」是選取/重新命名該列用的主要欄位,
    # 一律顯示,不開放關閉;分組/目標物件/資料名稱各自獨立可關,關掉純粹
    # 只是不畫那一欄,不影響底層資料。
    bpy.types.Scene.slider_rig_show_col_group = BoolProperty(name="Group", default=True)
    bpy.types.Scene.slider_rig_show_col_target_object = BoolProperty(name="Target Object", default=True)
    bpy.types.Scene.slider_rig_show_col_data_name = BoolProperty(name="Data Name", default=True)


def unregister():
    # 排布編輯畫布(modal operator)可能還開著就被disable/reload——先清掉
    # 它掛在SpaceView3D上的draw_handler,否則3D Viewport之後每次重繪都會
    # 呼叫到已經卸載掉的grid_canvas.draw_callback,導致錯誤。用模組屬性
    # 存取(operators.SLIDERRIG_OT_edit_grid_layout)而不是頂層import這個
    # class本身——Blender的Reload Scripts(importlib.reload)對子模組
    # 重新載入的時機沒有嚴格順序保證,頂層import曾經在reload過程中抓到
    # 尚未更新完的operators模組物件,導致ImportError。
    operators.SLIDERRIG_OT_edit_grid_layout.remove_handle_if_active()

    # 翻譯表要在unregister_class之前先卸載,對稱於register()裡"class先
    # 註冊、翻譯表後註冊"的順序。
    translations.unregister()

    # class(尤其是SLIDERRIG_PT_panel這個N面板)必須先卸載,再刪除下面這些
    # Scene屬性——順序反過來的話,unregister_class()執行完成前這段空窗期
    # 裡,Panel類別仍然註冊在Blender裡、隨時可能被UI系統排程重繪,但
    # scene.slider_rig_items等屬性已經被del掉,draw()讀到不存在的屬性會
    # 直接丟AttributeError(真實踩過:disable這個addon時在3D Viewport
    # 重繪的呼叫堆疊裡炸開,伴隨VS Code除錯器中斷點使Blender整個卡死;
    # 先在Pro版踩到,回頭確認免費版有一樣的bug)。這裡改成跟register()
    # 對稱:register()是「先註冊class、後新增Scene屬性」,unregister()
    # 理應反過來是「先移除Scene屬性依賴方(class)、後刪除Scene屬性本身」。
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    del bpy.types.Scene.slider_rig_show_col_data_name
    del bpy.types.Scene.slider_rig_show_col_target_object
    del bpy.types.Scene.slider_rig_show_col_group
    del bpy.types.Scene.slider_rig_show_all_groups
    del bpy.types.Scene.slider_rig_active_page
    del bpy.types.Scene.slider_group_index
    del bpy.types.Scene.slider_groups
    del bpy.types.Scene.slider_rig_index
    del bpy.types.Scene.slider_rig_items
    icons.unregister()
