[English](README.md) | [繁體中文](README.zh-TW.md)

# ParaRig

一個 Blender 插件（Python package），能從一份簡單的清單自動生成可拖拽的滑桿控制器與 Driver 綁定，讓你不用每次想要做 Live2D 風格的角色參數面板時，都手動組裝 Empty、約束（constraint）跟 Driver 表達式。

在清單裡填好每個滑桿的欄位——名稱、分組、控制樣式（直向/橫向拖拽）、目標（Shape Key／自訂屬性／骨骼位置）、數值範圍——按下 **生成** 就能得到：

1. 每筆項目對應一個滑桿控制器：扁平的 2D 矩形軌道 + 可拖拽的圓形把手，依分組收納在可自由移動/縮放的「外框（Frame）」裡，排版採用固定尺寸的網格系統。
2. 一個綁定在目標屬性上的 Driver，把把手的拖拽位置線性映射到 `[min_val, max_val]`。

## 安裝

1. Edit > Preferences > Add-ons > Install，選擇 `para_rig` 資料夾（打包成 zip）或直接指向該資料夾，啟用它。
2. 打開 3D Viewport 的 N 面板，切到 **ParaRig** 分頁。

## 使用方式

1. 用 `+` 按鈕新增滑桿項目，填好每一筆的分組、控制樣式、目標類型/物件、數值範圍。
2. 按下 **生成滑桿綁定 (Generate)**。滑桿依 `group` 欄位分組——每個分組對應一個外框（Frame）——所有生成物件都會統一放進專屬的「ParaRig」collection。改完清單內容後重新按一次 Generate 是非破壞性的：會就地更新，不會重置你已經調整過的把手位置或外框變換。
3. 沿著鎖定的軸向拖拽滑桿的圓形把手，驅動綁定的數值。
4. 按下 **清除已生成的滑桿 (Clear)** 可以整批移除重新開始。

## 狀態

持續開發中——完整的架構演進歷程、已知限制、以及討論過但尚未實作的功能清單（2D XY 拖拽板、一對多映射、JSON 匯出入），請見 [`para-rig-progress.md`](para-rig-progress.md)。

給 AI coding agent 使用的程式碼庫導覽，請見 [`CLAUDE.md`](CLAUDE.md)。
