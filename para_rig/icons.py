"""control_style的視覺化圖示選擇器:仿造Bone Widget等rigging addon常見的
shape picker UI——平常顯示目前選中樣式的縮圖,點下去彈出一個縮圖網格讓
使用者直接點選,取代純文字的下拉選單。這裡只負責生成/管理這些縮圖的
`bpy.utils.previews`(自訂icon),純圖示資料,不含任何PropertyGroup/
Operator/Panel類別。

縮圖是**預先烘焙好、隨addon一起打包的256x256 PNG檔**(para_rig/
thumbnails/),register()只做讀檔。要改形狀或配色的話,改
tools/generate_control_style_icons.py再跑一次,把新的PNG commit進去
(那支腳本不會被打包,也不會在執行期被呼叫)。構圖呼應grid_canvas.py
那套「軌道+把手」的視覺語言,使用者一眼就能把選單裡的縮圖跟排布編輯
畫布上的控制器圖示對起來。

**舊版(v1.1.0以前)在register()裡用純Python逐像素畫64x64、手刻PNG寫到
暫存目錄再讀回來**,放大到選擇器格子裡會糊,現在整套拿掉了。會繞那一大
圈是因為`bpy.utils.previews`的`pcoll.load()`只吃檔案路徑、不能直接餵
像素陣列,而`bpy.data.images`在register()等限制context下不能寫
(`_RestrictData`,使用者實測回報過的真實crash)——既然最後無論如何都
必須有一個PNG檔案存在,就直接隨addon打包,不再每次啟用都重新生一份。
解析度256是`bpy.utils.previews`內部的上限,再大也不會更清楚。
"""

import os

import bpy
import bpy.utils.previews

THUMBNAIL_DIR = os.path.join(os.path.dirname(__file__), "thumbnails")

_preview_collections = {}
_control_style_items = None  # 見control_style_enum_items()的說明


# 每個control_style在小尺寸UI(目前是滑桿清單UIList的每一列最前面)顯示的
# 內建Blender icon。這裡刻意不用上面那組自訂縮圖(control_style_icon_id)
# ——自訂縮圖是為了template_icon_view那種夠大的圖示網格設計的,縮到UIList
# 一列的高度後細節整個糊掉,分不出是哪一種樣式。內建icon本來就是為了小
# 尺寸設計,線條簡單、辨識度高。
#
# 內建圖示庫沒有「直向專用的雙向箭頭」,所以只能做到讓使用者一眼分辨
# 「哪一大類方向/類型」,這是刻意接受的限制,不是還沒做完。
_BUILTIN_ICON = {
    'LINEAR_1D': 'TRIA_UP_BAR',
    'LINEAR_1D_HORIZONTAL': 'TRIA_RIGHT_BAR',
    'XY_2D': 'EMPTY_AXIS',
    'TEXT_LABEL': 'SMALL_CAPS',
}


def builtin_icon_for(control_style):
    """回傳這個control_style適合在小尺寸UI(例如UIList清單列)顯示的內建
    Blender icon識別碼。查不到(理論上不會發生,除非CONTROL_STYLE_ITEMS
    新增了樣式卻忘了來_BUILTIN_ICON登記一筆)就回傳'QUESTION',一眼就能
    看出是忘記登記,方便除錯,不會直接炸掉。"""
    return _BUILTIN_ICON.get(control_style, 'QUESTION')


# 每個control_style identifier對應的RNA儲存值(items tuple的第5個欄位)——
# **只能新增,不能修改既有的數字、也不能重新使用已經棄用的數字**。
# 動態EnumProperty的items() callback底層是用每個entry這個數字存使用者
# 選了哪個樣式,不是存identifier字串、也不是存清單裡的位置——如果像
# 舊版那樣直接用enumerate()位置當這個數字,properties.CONTROL_STYLE_ITEMS
# 的顯示順序就完全不能調整,一旦調整(或在中間插入新樣式),任何已經
# 存過control_style的滑桿項目reload後都會讀到別的樣式。用這份固定對照表
# 把「RNA儲存值」跟「清單裡的顯示順序」脫鉤,兩者可以獨立變動:
# CONTROL_STYLE_ITEMS可以自由調整順序(例如把同類型樣式排在一起),
# 不會影響任何舊資料;新增樣式時只在這裡追加一個新數字,不要更動
# 既有identifier對應的數字。
_STYLE_VALUES = {
    'LINEAR_1D': 0,
    'LINEAR_1D_HORIZONTAL': 1,
    'XY_2D': 2,
    'TEXT_LABEL': 3,
}


def control_style_icon_id(control_style):
    """回傳這個control_style對應的自訂縮圖icon_value(int),給
    control_style_enum_items()組EnumProperty items時用。圖示還沒載入
    (理論上只會在register()還沒跑完、或unregister()之後這種不該發生
    UI互動的空窗期發生,或thumbnails/裡缺了這個樣式的PNG)就回傳0(Blender的ICON_NONE),不直接炸掉。"""
    pcoll = _preview_collections.get("main")
    if pcoll is None or control_style not in pcoll:
        return 0
    return pcoll[control_style].icon_id


def control_style_enum_items():
    """回傳control_style這個EnumProperty要用的items清單(每個tuple帶
    icon_value)。這是動態(callback)形式的enum items,Blender官方文件
    明確警告:callback每次被呼叫時,如果都重新配置一份新的list/tuple,
    Python端的字串物件可能在Blender的C端還在使用這份items時就被GC回收,
    導致UI顯示亂碼甚至直接crash——必須讓Python端持有同一份不會被回收的
    固定參照,所以這裡快取成模組層級變數,只在第一次呼叫(或register()
    重建icon之後)才重新組一次。

    另外,動態items的EnumProperty不支援`default`參數(Blender會直接
    忽略/報錯),所以property定義那邊拿掉了`default='LINEAR_1D'`,改成
    依賴「沒有items()['default']的enum屬性in預設情況下取第一筆」——只要
    這裡回傳的list第一筆維持是LINEAR_1D(識別碼、順序都跟
    properties.CONTROL_STYLE_ITEMS原本的第一筆一致),新item的
    control_style實際預設值就還是'LINEAR_1D',效果沒變,只是不是透過
    明講的`default=`關鍵字達成。

    每個tuple的第5個欄位(RNA儲存值)一律查_STYLE_VALUES這份固定對照表,
    不能用enumerate()的位置——見_STYLE_VALUES的完整說明,用位置會讓
    CONTROL_STYLE_ITEMS的顯示順序永遠不能調整,一旦調整就會讓既有資料
    的control_style讀成別的樣式。"""
    global _control_style_items
    if _control_style_items is None:
        from .properties import CONTROL_STYLE_ITEMS
        _control_style_items = [
            (identifier, name, desc, control_style_icon_id(identifier), _STYLE_VALUES[identifier])
            for identifier, name, desc in CONTROL_STYLE_ITEMS
        ]
    return _control_style_items


def register():
    global _control_style_items
    _control_style_items = None  # 舊快取的icon_value對應到即將被
    # remove()的preview collection,reload/重新註冊時必須重建,不能沿用
    pcoll = bpy.utils.previews.new()
    for style in _STYLE_VALUES:
        path = os.path.join(THUMBNAIL_DIR, f"control_style_{style}.png")
        if os.path.exists(path):
            pcoll.load(style, path, 'IMAGE')
    _preview_collections["main"] = pcoll


def unregister():
    global _control_style_items
    for pcoll in _preview_collections.values():
        bpy.utils.previews.remove(pcoll)
    _preview_collections.clear()
    _control_style_items = None
