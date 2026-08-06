"""多語系翻譯表,接Blender原生的`bpy.app.translations`機制——`register()`/
`unregister()`要在`__init__.py`的`register()`/`unregister()`裡呼叫,且要在
`bpy.utils.register_class`之後才註冊(翻譯表是套用在已註冊的RNA屬性上,
順序反過來的話Blender在註冊當下找不到對應的屬性可套用)。

程式碼裡的字面預設值(`bl_label`/Property的`name=`/`description=`/
EnumProperty items等)一律是英文——這是extensions.blender.org的要求,
英文是Blender的原生fallback語言,其他語言(含繁體中文)都透過這份翻譯表提供,
不能反過來讓字面預設變成非英文。

TRANSLATIONS_DICT的格式是Blender規定的:
    {locale: {(msgctxt, msgid): msgstr, ...}, ...}
`msgctxt`預設用`bpy.app.translations.contexts.default`(即`"*"`)——這個
add-on沒有用到自訂的translation_context,所有字串都掛在預設context下。

只涵蓋"能被`bpy.app.translations`自動套用"的字串(`bl_label`/`bl_description`/
Property的`name=`/`description=`/EnumProperty items的顯示名稱與說明):這些
Blender會在繪製UI時自動查表,呼叫端(operators.py/properties.py/panels.py)
完全不需要改動任何程式碼。

`self.report(...)`跟`layout.label(text=...)`這類手動組出來、不是透過
Property系統畫出來的字串,Blender不會自動套用翻譯——這些呼叫端改用
`bpy.app.translations.pgettext()`包一層,查的是同一份TRANSLATIONS_DICT
(見panels.py/operators.py/grid_layout.py/grid_canvas.py裡對應的
pgettext()呼叫)。新增這類字串時,要同時把原文(英文)加進這裡的msgid,
兩邊沒對上的話pgettext()會直接回傳原文(找不到翻譯,fail-open,不會噴錯,
但也不會被翻譯)。

見docs/i18n-plan.md的完整字串盤點與架構說明。
"""

import bpy

# ---------------------------------------------------------------------------
# 繁體中文翻譯表。key是原文(英文)msgid,value是對應的繁體中文。
# 只列出"會被UI用到"的字串,見docs/i18n-plan.md的盤點清單。
# ---------------------------------------------------------------------------
_ZH_HANT = {
    # properties.py - TARGET_TYPE_ITEMS
    "Shape Key": "形態鍵 (Shape Key)",
    "Custom Property": "自訂屬性 (Custom Property)",
    "Bone Location": "骨骼位置 (Bone Location)",
    # properties.py - CONTROL_STYLE_ITEMS
    "1-Axis Slider (Vertical)": "1軸滑桿(直向)",
    "Linear slider dragged along the Track's local Y axis": "沿Track局部Y軸拖拽的線性滑桿",
    "1-Axis Slider (Horizontal)": "1軸滑桿(橫向)",
    "Linear slider dragged along the Track's local X axis (visually horizontal)":
        "沿Track局部X軸(視覺上水平)拖拽的線性滑桿",
    "2-Axis Drag Pad (XY)": "2軸拖拽板(XY)",
    "Free-drag on a plane; X/Y each map to their own independent target":
        "在平面上自由拖拽,X/Y各自對應一組獨立目標",
    "Text Label": "純文字",
    "Displays only text (the item's name); generates no draggable control and drives no target":
        "只顯示文字(item名稱),不生成任何可拖拽的控制器,也不驅動任何目標",
    # properties.py - TargetBinding fields
    "Target Type": "目標類型",
    "Target Object": "目標物件",
    "Bone Name": "骨骼名稱",
    "Used when Target Type is Bone Location": "target_type為骨骼位置時使用",
    "Data Name": "資料名稱",
    "Shape Key name, or custom property name": "Shape Key名稱 或 自訂屬性名稱",
    "Bone Axis": "骨骼軸向",
    "Min Value": "最小值",
    "Max Value": "最大值",
    "Invert": "反轉",
    # properties.py - SliderGroupItem fields
    "Group Name": "分組名稱",
    "Bound Object": "綁定物件",
    "Makes this group's Frame follow this object (or the bone specified below); leave empty to not bind":
        "讓這個分組的Frame跟著這個物件(或下面指定的骨骼)走,留空代表不綁定",
    "Bound Bone": "綁定骨骼",
    "When the bound object is an Armature, specifies which bone to follow; leave empty to follow the object's own origin":
        "綁定物件是Armature時,指定要跟隨的骨骼;留空代表跟隨物件本身的origin",
    "Show Frame Outline": "顯示外框",
    "When off, this group's Frame won't generate a visible rectangular outline, but the Frame "
    "object itself is still created (to hold layout and bindings); sliders inside are unaffected":
        "關閉後這個分組不會生成Frame的矩形外框視覺,但Frame物件本身仍會生成"
        "(用來承載排版與綁定),底下的滑桿不受影響",
    "Show Group Name": "顯示分組名稱",
    "Displays the group's name (as a Text Mesh) directly above this group's Frame outline":
        "在這個分組的Frame外框正上方顯示分組名稱(Text Mesh)",
    "Group Name Text Size": "分組名稱文字大小",
    "Generated Group Name Label Object": "已生成分組名稱標籤",
    "(No Group Assigned)": "(未指定分組)",
    # properties.py - SliderRigItem fields
    "Slider Name": "滑桿名稱",
    # 註:這個msgid同時也是N面板「分組」頁籤按鈕的文字(見__init__.py的
    # slider_rig_active_page)。Blender核心翻譯目錄本身已經有"Group"的
    # zh_HANT譯文(「群組」,來自Vertex Groups等內建功能),實際顯示時會
    # 蓋過這裡登記的「分組」——語意相近,刻意接受,不另外造複合字迴避。
    "Group": "分組",
    "Grid X": "橫向格子座標",
    "The top-left grid coordinate (horizontal) of this control's occupied area; larger values are "
    "further right. Numbers may be skipped to leave gaps. Actual cell footprint depends on the "
    "control style (see grid_layout.py)":
        "這個控制器佔用範圍的左上角格子座標(橫向),數字愈大愈往右;"
        "可以跳號留出間距。實際佔用格數依control_style而定(見grid_layout.py)",
    "Grid Y": "縱向格子座標",
    "The top-left grid coordinate (vertical) of this control's occupied area; larger values are "
    "further down. Actual cell footprint depends on the control style (see grid_layout.py)":
        "這個控制器佔用範圍的左上角格子座標(縱向),數字愈大愈往下;"
        "實際佔用格數依control_style而定(見grid_layout.py)",
    "Control Style": "控制器樣式",
    "Generated Object": "已生成物件",
    "Show Name Label": "顯示名稱標籤",
    "Label Text Size": "標籤文字大小",
    "Generated Label Object": "已生成標籤物件",
    # operators.py - MOVE_DIRECTION_ITEMS
    "Up": "Up",
    "Down": "Down",
    # operators.py - bl_label / bl_description
    "Add Slider Item": "新增滑桿項目",
    "Remove Slider Item": "移除滑桿項目",
    "Move Slider Item": "移動滑桿項目",
    "Edit Layout": "編輯排版",
    "Drag sliders within the selected group to adjust their grid position, directly in the 3D Viewport":
        "在3D Viewport裡用拖曳的方式調整所選分組內滑桿的格子位置",
    "Assign Group": "指派分組",
    "Add Group": "新增分組",
    "Remove Group": "移除分組",
    "Only removes this entry from the Groups list; sliders already assigned to it are untouched "
    "(their group_uid still points at this deleted uid, shown in the UI as \"No Group Assigned\"; "
    "generate() treats them as one separate, unnamed group — to reassign them, pick a new group "
    "for each manually)":
        "只移除Groups清單裡的這一筆,不會動到已經指派這個分組的滑桿項目"
        "(它們的group_uid仍然指向這個已刪除的uid,UI上會顯示「未指定分組」,"
        "generate()會把它們視為一個獨立的、看不到名稱的分組——之後如果要"
        "重新指派,得手動幫它們選一個新分組)",
    "Move Group": "移動分組",
    "Align Panel to Current View": "將此面板對準當前視圖",
    "Rotates the selected group's Frame outline to face the current 3D viewport's view angle":
        "把目前選中分組的Frame外框旋轉,正面朝向目前3D視窗的視角",
    "Generate Slider Rig": "生成滑桿綁定",
    "Auto-generates slider controls and Drivers from the list data": "依照清單資料自動生成滑桿控制器與Driver",
    "Clear Generated Sliders": "清除已生成的滑桿",
    "Deletes all generated slider objects (Drivers are removed as well)": "刪除所有已生成的滑桿物件(Driver會一併移除)",
    # operators.py - self.report() messages (含模板)
    "Must be run inside the 3D Viewport": "請在3D Viewport裡執行",
    "Please select a group in the Groups list first": "請先在Groups清單裡選取一個分組",
    "This group hasn't generated a Frame yet — click \"Generate Slider Rig\" first":
        "這個分組還沒有生成過Frame,請先按「生成滑桿綁定」",
    "Must be run inside the 3D Viewport (couldn't determine the current view angle)": "請在3D Viewport裡執行(找不到目前視角)",
    "No slider items have been added yet": "尚未新增任何滑桿項目",
    "Grid coordinate conflict, generation cancelled: ": "格子座標衝突,已取消生成:",
    "No target found for the following items — sliders were generated but Drivers were not bound: ":
        "以下項目找不到目標,已生成滑桿但未綁定Driver: ",
    "Generated {n} slider(s) and bound Drivers": "已生成 {n} 個滑桿並完成綁定",
    # panels.py
    "Please specify an Armature object first": "請先指定Armature物件",
    "Select Group": "選擇分組",
    "No groups created yet": "尚未建立任何分組",
    "Show Columns": "顯示欄位",
    "ParaRig": "ParaRig 自動生成",
    "Update Slider Rig": "更新滑桿綁定",
    "Sliders": "滑桿",
    # slider_rig_active_page兩個選項的description(見__init__.py)。頁籤
    # 按鈕本身的文字用"Group"/"Sliders"這兩個msgid,前者見上面的說明。
    "Show group settings and the Groups list": "顯示分組設定與分組清單",
    "Show slider settings and the Sliders list": "顯示滑桿設定與滑桿清單",
    "Active Page": "目前頁面",
    "Show Sliders From All Groups": "顯示所有分組的滑桿",
    "Text Size": "文字大小",
    "Target settings not initialized yet — please refresh the panel": "目標設定尚未初始化,請重新整理面板",
    "{axis} Axis Target": "{axis}軸目標",
    # __init__.py
    "Auto-generates draggable slider controls and binds them via Drivers to "
    "Shape Keys / custom properties / bone locations":
        "自動生成可拖拽的滑桿控制器,並用Driver綁定到Shape Key / 自訂屬性 / 骨骼位置",
    "When off, the slider list only shows sliders belonging to the group currently selected in the "
    "Groups list; when on, sliders from every group are shown":
        "不勾選時,滑桿清單只顯示目前在Groups清單裡選中的那個分組底下的滑桿;勾選後顯示所有分組的滑桿",
    # preferences.py
    "Edit Layout Canvas UI Size": "編輯排版畫布UI大小",
    "Adjusts the display size of the \"Edit Layout\" canvas (the grid-editing overlay in the 3D "
    "Viewport), multiplied against the system/Blender UI Scale setting — lets machines with "
    "different screen resolutions or system scaling fine-tune independently, instead of sharing "
    "one absolute pixel size":
        "調整「編輯排版」畫布(3D Viewport裡的格子編輯介面)的顯示大小,"
        "跟系統/Blender本身的UI Scale設定相乘——不同螢幕解析度或系統縮放的電腦"
        "可以各自再微調,不用共用同一個絕對像素大小",
    # grid_layout.py - conflict message template
    "\"{label}\": {a} and {b} overlap at cell ({x}, {y})": "「{label}」裡的 {a} 與 {b} 在格子 ({x}, {y}) 重疊",
    # grid_canvas.py - POST_PIXEL overlay text (與operators.py的
    # bl_label="Edit Layout"共用同一組msgid,翻譯結果自然一致)
    "Right-click or press ESC to exit": "點擊右鍵或ESC離開",
}

# locale key依Blender的bpy.app.translations慣例,繁體中文用"zh_HANT"
# (對照bpy.app.translations.locales裡實際出現的字串;不是"zh_TW")。
TRANSLATIONS_DICT = {
    "zh_HANT": {("*", msgid): msgstr for msgid, msgstr in _ZH_HANT.items()},
}


def register():
    bpy.app.translations.register(__package__, TRANSLATIONS_DICT)


def unregister():
    bpy.app.translations.unregister(__package__)
