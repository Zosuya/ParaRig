"""這個addon的AddonPreferences:Edit > Preferences > Add-ons展開這個addon
後看到的設定區塊,跟N-panel的scene層級屬性(properties.py)是完全不同的
儲存位置——這裡的設定綁在Blender使用者本身(存在使用者的userpref.blend),
不隨.blend檔案走,適合放「這台電腦/這個使用者的顯示偏好」這類設定。

目前只有一個選項:編輯排版畫布(grid_canvas.py)的UI縮放百分比。
"""

import bpy
from bpy.props import EnumProperty
from bpy.types import AddonPreferences

# (identifier, 顯示名稱, 說明)。identifier存成字串而不是直接存百分比數字
# ——EnumProperty的items慣例都是字串identifier,轉換成實際倍率的工作交給
# grid_canvas_ui_scale_factor(),這裡只負責定義選項本身。
_SCALE_ITEMS = [
    (str(pct), f"{pct}%", "") for pct in (50, 75, 100, 125, 150, 175, 200)
]


class SliderRigAddonPreferences(AddonPreferences):
    # 必須是這個addon的模組名稱(__package__),Blender用這個字串把
    # AddonPreferences跟對應的addon模組配對起來——寫死字串會在addon改資料夾
    # 名稱時悄悄失效,用__package__讓兩者永遠保持一致。
    bl_idname = __package__

    grid_canvas_ui_scale: EnumProperty(
        name="編輯排版畫布UI大小",
        description="調整「編輯排版」畫布(3D Viewport裡的格子編輯介面)的顯示大小,"
        "跟系統/Blender本身的UI Scale設定相乘——不同螢幕解析度或系統縮放的電腦"
        "可以各自再微調,不用共用同一個絕對像素大小",
        items=_SCALE_ITEMS,
        default='100',
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "grid_canvas_ui_scale")


def grid_canvas_ui_scale_factor():
    """回傳使用者在偏好設定裡選的百分比,轉成倍率(100% -> 1.0)供
    grid_canvas.ui_scale()相乘。取不到偏好設定(理論上只會在addon還沒
    完整註冊完成的空窗期發生)時回傳1.0,不影響原本的縮放行為。"""
    prefs = bpy.context.preferences.addons.get(__package__)
    if prefs is None:
        return 1.0
    return int(prefs.preferences.grid_canvas_ui_scale) / 100.0


classes = (
    SliderRigAddonPreferences,
)
