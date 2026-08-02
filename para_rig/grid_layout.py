"""Grid排版計算:每種control_style佔用的格數、格子物理尺寸、佔用範圍衝突
偵測。純函式(不碰bpy.types),operators.py/rig_builder.py生成/排版滑桿時呼叫。

座標系統:grid_x/grid_y代表控制器佔用範圍的「左上角」格子座標(不是中心點)。
一個佔用(w, h)格的控制器,實際佔用的格子是
{(grid_x+i, grid_y+j) for i in range(w) for j in range(h)}。
grid_y數字愈大代表愈往下(跟現有排版的「往下堆疊」方向一致)。
"""

from bpy.app.translations import pgettext_iface as _

from .mesh_builders import CELL_SIZE

# 每種control_style佔用的格數 (width_cells, height_cells)。
# LINEAR_1D(直向)沿Track局部Y軸拖拽,視覺上是站立的長條,佔用1欄2列;
# LINEAR_1D_HORIZONTAL(橫向)只是把同一份Track geometry轉90度,視覺上是
# 躺平的長條,佔用2欄1列。XY_2D(2D XY拖拽板)尚未實作,格數先定案
# (2欄2列)但不出現在CONTROL_STYLE_ITEMS裡,等真正實作時再啟用。
# TEXT_LABEL(純文字)沒有可拖拽的控制器本體,只有文字本身——佔2欄1列
# (使用者定案:文字通常比單一格寬,2x1讓一般長度的名稱不用縮字級)。
CONTROL_STYLE_CELLS = {
    'LINEAR_1D': (1, 2),
    'LINEAR_1D_HORIZONTAL': (2, 1),
    'XY_2D': (2, 2),  # 預留,尚未實作對應的control_style選項
    'TEXT_LABEL': (2, 1),
}


def cells_for(control_style, show_label):
    """回傳這個control_style(加上show_label是否開啟)實際佔用的格數
    (width_cells, height_cells)。開啟標籤會在「標籤方向」多佔一格:
    直向樣式標籤在上方,佔用高度+1(1x2 -> 1x3);橫向樣式的標籤固定水平
    書寫、擺在控制器上方,不隨Track旋轉,所以是佔用高度+1(2x1 -> 2x2),
    不是佔用寬度。"""
    width_cells, height_cells = CONTROL_STYLE_CELLS.get(control_style, (1, 1))
    if show_label:
        height_cells += 1
    return width_cells, height_cells


def occupied_cells(item):
    """回傳這個item實際佔用的格子座標集合(左上角為item.grid_x/grid_y)。
    標籤(如果開啟)佔用最上面那一列(grid_y本身),控制器本身佔用緊接在
    下面的base cells(grid_y+1起算)——這個範圍不只用來算Frame邊界/衝突
    偵測,cell_center_local_xy()置中Track時也是用同一個「本體起算位置」
    (show_label開啟時本體從grid_y+1起算,而不是grid_y),兩處對「標籤格
    在哪裡、本體從哪裡開始」的認知必須一致,否則會出現look-alike-correct
    但實際上互相矛盾的情況(真實bug:Track置中公式假設本體固定不因標籤
    移動,但rig_builder.label_offset_for()的標籤偏移公式卻假設本體已經
    因標籤下移一格,兩者各自「看起來合理」但組合起來讓標籤視覺上跨進
    鄰居的格子)。"""
    width_cells, height_cells = cells_for(item.control_style, item.show_label)
    return {
        (item.grid_x + i, item.grid_y + j)
        for i in range(width_cells)
        for j in range(height_cells)
    }


def find_grid_conflicts(groups, group_labels):
    """檢查每個分組內是否有滑桿的佔用格子範圍互相重疊(不只是起點座標
    相同——不同control_style佔用的格數不一樣,即使起點座標不同,實際佔用
    範圍還是可能重疊)。回傳衝突說明字串的list(空list代表沒有衝突)。
    groups的key是group_uid,group_labels是{group_uid: 顯示用名稱}的
    對照表,只用來組錯誤訊息,不參與分組判斷本身。"""
    conflicts = []
    for group_uid, group_items in groups.items():
        label = group_labels[group_uid]
        occupied_by = {}  # (x, y) -> item,記錄目前每個格子被哪個item佔用
        for item in group_items:
            for cell in occupied_cells(item):
                if cell in occupied_by:
                    other = occupied_by[cell]
                    conflicts.append(
                        _("\"{label}\": {a} and {b} overlap at cell ({x}, {y})").format(
                            label=label, a=other.name, b=item.name, x=cell[0], y=cell[1]
                        )
                    )
                else:
                    occupied_by[cell] = item
    return conflicts


def content_bounds(group_items):
    """回傳這個分組所有item佔用格子的聯集邊界:
    (min_x, max_x_exclusive, min_y, max_y_exclusive)——max是exclusive
    (格子座標+佔用格數的最大值),方便直接算內容寬高(max - min) * CELL_SIZE。"""
    all_cells = set()
    for item in group_items:
        all_cells |= occupied_cells(item)
    xs = [c[0] for c in all_cells]
    ys = [c[1] for c in all_cells]
    return min(xs), max(xs) + 1, min(ys), max(ys) + 1


def cell_center_local_xy(item, group_items):
    """回傳這個item的Track在其Frame local空間裡的中心點(x, y)。
    以整個分組內容邊界(含標籤格數,見content_bounds/occupied_cells)的中心
    為原點,讓排版跟Frame外框的置中方式一致。

    Track自己的中心用「基礎樣式格數」(CONTROL_STYLE_CELLS,不含標籤格)
    計算,但錨點起算位置會因show_label而不同:標籤格固定佔用item.grid_y
    本身那一列(occupied_cells的定義),開啟標籤時本體要整個往下讓一格
    (從item.grid_y+1起算),關閉時本體從item.grid_y直接起算——這樣本體
    的實際格子範圍才會跟occupied_cells()回報的佔用範圍(標籤格+本體格)
    一致。

    這裡曾經寫成「本體永遠固定從item.grid_y起算,不受show_label影響」,
    理由是「標籤格只是Frame要多留的空間,不是控制器要讓出的格子」——這個
    假設本身是錯的:rig_builder.label_offset_for()算標籤偏移距離時,
    公式(height_cells/2+0.5)*CELL_SIZE假設的正是「本體已經因為標籤而
    下移一格」這個前提,兩處各自看起來都合理,但組合起來就會讓標籤的
    實際物理位置比格子系統认定的標籤格中心多推了一整格,跨進上面緊鄰
    的另一個item的格子範圍(真實bug,使用者截圖回報:B開啟標籤後,B的
    標籤文字視覺上壓在緊鄰的C控制器本體上,即使兩者的occupied_cells()
    完全不重疊)。"""
    min_x, max_x, min_y, max_y = content_bounds(group_items)
    content_center_x = (min_x + max_x) / 2
    content_center_y = (min_y + max_y) / 2

    width_cells, height_cells = CONTROL_STYLE_CELLS.get(item.control_style, (1, 1))
    body_start_y = item.grid_y + 1 if item.show_label else item.grid_y
    item_center_x = item.grid_x + width_cells / 2
    item_center_y = body_start_y + height_cells / 2

    x = (item_center_x - content_center_x) * CELL_SIZE
    y = -(item_center_y - content_center_y) * CELL_SIZE
    return x, y


def same_item(a, b):
    """判斷兩個PropertyGroup參照是否指向同一筆資料。Blender每次從
    bpy_prop_collection取出元素都會產生全新的Python wrapper物件,
    `a is b`即使指向同一筆資料也永遠是False——必須比對as_pointer()
    (跟properties._on_group_changed既有的做法一致)。任何需要「這兩個
    參照是不是同一個item」的判斷都要用這個,不能用is。"""
    return a is not None and b is not None and a.as_pointer() == b.as_pointer()


def occupied_cells_at(item, gx, gy):
    """回傳「假設item的錨點(左上角)移到(gx, gy)」會佔用的格子集合,不讀取
    item目前實際的grid_x/grid_y——用來在真正寫入前預判「如果放在這裡」
    會不會跟別人重疊,拖曳/互換判斷都要用這個,不能只檢查滑鼠落點單一格
    (那樣2x1/1x2這類多格footprint的item會漏檢查自己另外佔用的格子)。

    用cells_for(不是CONTROL_STYLE_CELLS)——要把show_label多佔的那一列
    標籤格算進去,因為排布編輯畫布(grid_canvas.py)現在會把這格實際畫
    出來(見_item_px_rect),所以佔用範圍計算也要跟畫面一致地含標籤格。
    (先前這裡刻意排除標籤格是因為當時畫面沒有畫出這格,兩邊都改成
    「不含」才能暫時對齊；現在改成兩邊都「含」,做法一致,不是靠繞開
    某一邊的計算來湊合。)"""
    width_cells, height_cells = cells_for(item.control_style, item.show_label)
    return {(gx + i, gy + j) for i in range(width_cells) for j in range(height_cells)}


def items_overlapping_at(group_items, item, gx, gy, exclude=None):
    """回傳group_items裡,如果item的錨點移到(gx, gy),會跟哪些其他item的
    佔用格子重疊(集合,可能不只一個)。用occupied_cells_at算item移動後的
    完整footprint,而不是只看滑鼠落點的那一格。exclude用來排除item自己
    (item本來就在group_items裡,一定要排除,否則自己一定跟自己"重疊")。"""
    target_cells = occupied_cells_at(item, gx, gy)
    overlapping = []
    for other in group_items:
        # 不能用`other is item`——group_items每次都是重新從collection取出
        # 的新wrapper,is比較永遠False,會導致item跟「自己的舊位置」判定
        # 重疊:只移動一格時新舊footprint相交,鬆手變成「跟自己互換」=
        # 寫回原值=完全沒動(先前「只拖一格拖不過去」的根本原因)。
        if same_item(other, item) or same_item(other, exclude):
            continue
        if target_cells & occupied_cells_at(other, other.grid_x, other.grid_y):
            overlapping.append(other)
    return overlapping


def swap_would_conflict(group_items, item_a, item_b):
    """模擬item_a與item_b互換錨點後,雙方的新footprint是否會彼此重疊、
    或撞到任何第三方item。互換前必須先用這個檢查,會衝突就整個放棄——
    兩個item的control_style形狀不同時(1x2 vs 2x1),單純交換錨點座標
    完全可能產生新的重疊(例如直向item換到橫向item的錨點後,多出來的
    那一格正好壓在對方或第三方身上),不檢查就寫入等於繞過了拖曳的
    衝突防護。"""
    a_cells = occupied_cells_at(item_a, item_b.grid_x, item_b.grid_y)
    b_cells = occupied_cells_at(item_b, item_a.grid_x, item_a.grid_y)
    if a_cells & b_cells:
        return True
    swapped_cells = a_cells | b_cells
    for other in group_items:
        if same_item(other, item_a) or same_item(other, item_b):
            continue
        if swapped_cells & occupied_cells_at(other, other.grid_x, other.grid_y):
            return True
    return False


def swap_item_positions(item_a, item_b):
    """交換兩個item的grid_x/grid_y(左上角錨點座標)。只是單純的座標互換,
    不管兩者的control_style佔用格數是否相同——即使一個是1x2、另一個是2x1,
    互換後的座標依然各自合法(只是佔用的格子形狀跟著各自的control_style
    走,不會因為互換而變形)。呼叫端(operators.py)負責在真正寫入前後
    處理其他狀態同步(例如衝突檢查、UI重繪)。"""
    item_a.grid_x, item_b.grid_x = item_b.grid_x, item_a.grid_x
    item_a.grid_y, item_b.grid_y = item_b.grid_y, item_a.grid_y


def _distance_from_origin(item):
    """回傳這個item的錨點離格子原點(0,0)的距離平方(不開根號,只用來比大小)。
    這裡的(0,0)是「排布編輯畫布左上角」那個格子座標原點,不是3D世界的物體
    原點——格子系統本身就是以左上角為(0,0)、往右往下遞增(見模組docstring)。
    平手時(距離完全相同)用grid_y、grid_x當次要排序鍵,讓結果是決定性的,
    不會因為collection迭代順序不同而每次推開不同的item。"""
    return (item.grid_x ** 2 + item.grid_y ** 2, item.grid_y, item.grid_x)


def _push_offset_for(overlap_cells):
    """依重疊區域的形狀,決定「該被推開的那個item」要往哪個方向、移動幾格,
    回傳(dx, dy)。

    規則(使用者定案):
    - 重疊區寬1格、高>1格(縱向細長)=縱向被擠壓 -> 往下移(0, overlap_h)
    - 重疊區高1格、寬>1格(橫向細長)=橫向被擠壓 -> 往右移(overlap_w, 0)
    - 寬高都是1格 -> 視為最小單位的縱向擠壓,往下移一格
    - 寬高都>1格 -> 比較兩個維度的擠壓量,「擠壓量較大的那個維度」是主要
      的衝突方向,要往「另一個維度」讓開:橫向重疊格數較多(overlap_w >
      overlap_h)就往下移,縱向重疊格數較多就往右移;相等時往右移(使用者
      指定「都大於1就優先往右」)。

    移動距離固定用「該方向的重疊格數」,剛好把重疊完全錯開,不會過度移動
    留下多餘空格,也不會移動不足導致還要再推一次。"""
    xs = [c[0] for c in overlap_cells]
    ys = [c[1] for c in overlap_cells]
    overlap_w = max(xs) - min(xs) + 1
    overlap_h = max(ys) - min(ys) + 1

    if overlap_w == 1 and overlap_h == 1:
        return (0, 1)
    if overlap_w == 1:
        return (0, overlap_h)
    if overlap_h == 1:
        return (overlap_w, 0)
    # 兩個維度都>1:擠壓量大的維度決定要往哪邊讓開(往另一個維度移動)
    if overlap_w > overlap_h:
        return (0, overlap_h)
    return (overlap_w, 0)


def resolve_overlaps(group_items, max_passes=64):
    """自動把同一group裡重疊的item推開,直到沒有任何重疊為止。就地修改
    item.grid_x/grid_y,回傳實際被移動過的item名稱list(空list代表本來就
    沒有重疊、什麼都沒動)。

    演算法(使用者定案的規則):
    1. 找出第一組互相重疊的item pair。
    2. 這一對裡「離格子原點(0,0)較遠」的那個是要被推開的一方——不是
       「剛剛改變狀態(例如開了標籤)的那個」。愈靠近原點的item位置愈穩定,
       改動集中在外圍,使用者比較不會覺得整個版面突然被打亂。
    3. 依重疊區域形狀算出一個offset(見_push_offset_for)。
    4. 把offset套用在那個item上;如果它移動後又壓到別的item,被壓到的那些
       item「沿用同一個offset」一起往同方向移動(連鎖推移),而不是對每個
       新衝突重新判斷方向——重新判斷會讓連鎖上的item各自往不同方向散開,
       反而更容易互相撞在一起甚至完全重疊(使用者明確指定要固定offset)。
    5. 重複1-4直到沒有重疊。

    max_passes是安全上限:正常情況幾輪就會收斂(每一輪都讓某個item往正
    方向遠離,不會來回震盪),但格子系統允許任意座標,理論上仍可能因為
    未預期的資料狀態(例如兩個item完全同座標同形狀)反覆觸發,加個上限
    避免生成流程整個卡死。"""
    moved = []
    for _ in range(max_passes):
        pair = _find_first_overlap(group_items)
        if pair is None:
            break
        item_a, item_b, overlap_cells = pair
        # 離原點較遠的那個讓開
        if _distance_from_origin(item_a) >= _distance_from_origin(item_b):
            pushed = item_a
        else:
            pushed = item_b
        offset = _push_offset_for(overlap_cells)
        _push_chain(group_items, pushed, offset, moved)
    return moved


def _find_first_overlap(group_items):
    """回傳第一組重疊的(item_a, item_b, 重疊格子集合);沒有重疊回傳None。
    兩兩比對,順序照group_items本身——resolve_overlaps會反覆呼叫直到回傳
    None,所以這裡不需要一次找出所有重疊。"""
    for i in range(len(group_items)):
        for j in range(i + 1, len(group_items)):
            a, b = group_items[i], group_items[j]
            shared = occupied_cells(a) & occupied_cells(b)
            if shared:
                return a, b, shared
    return None


def _push_chain(group_items, item, offset, moved):
    """把item往offset方向移動,並讓所有被它壓到的item「沿用同一個offset」
    一起移動(連鎖)。moved是累積被移動過的item名稱的list(就地append)。

    用while佇列而不是遞迴,避免連鎖很長時吃掉Python的遞迴深度;已經在這
    一輪推過的item不會被重複推(用as_pointer記在pushed_ids裡),否則兩個
    item互相壓到對方時會無限互推。"""
    dx, dy = offset
    queue = [item]
    pushed_ids = set()
    while queue:
        current = queue.pop(0)
        if current.as_pointer() in pushed_ids:
            continue
        pushed_ids.add(current.as_pointer())
        current.grid_x = max(0, current.grid_x + dx)
        current.grid_y = max(0, current.grid_y + dy)
        if current.name not in moved:
            moved.append(current.name)
        # 這次移動之後新壓到的item,沿用同一個offset繼續往下推
        for other in group_items:
            if same_item(other, current) or other.as_pointer() in pushed_ids:
                continue
            if occupied_cells(current) & occupied_cells(other):
                queue.append(other)
