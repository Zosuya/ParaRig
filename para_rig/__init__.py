bl_info = {
    "name": "ParaRig",
    "author": "Zosuya",
    "version": (0, 1, 1),
    "blender": (4, 2, 0),
    "location": "View3D > N-Panel > ParaRig",
    "description": "Auto-generates draggable slider controls and binds them via Drivers to "
    "Shape Keys / custom properties / bone locations",
    "category": "Rigging",
    "license": "SPDX:GPL-3.0-or-later",
}

import bpy
from bpy.props import CollectionProperty, IntProperty, BoolProperty

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

    del bpy.types.Scene.slider_rig_show_col_data_name
    del bpy.types.Scene.slider_rig_show_col_target_object
    del bpy.types.Scene.slider_rig_show_col_group
    del bpy.types.Scene.slider_rig_show_all_groups
    del bpy.types.Scene.slider_group_index
    del bpy.types.Scene.slider_groups
    del bpy.types.Scene.slider_rig_index
    del bpy.types.Scene.slider_rig_items
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    icons.unregister()
