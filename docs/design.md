# C4D 2023 材质替换插件 — 设计规格

## 1. 需求原话

> 模型列表有多个对象使用了同个材质球，想把材质管理器里的指定材质球一键替换。

## 2. 确认后的决策

| 决策点 | 结论 |
| --- | --- |
| 替换语义 | **覆盖旧材质内容**：`M_Old` 这个材质球对象保留不动，把 `M_New` 的全部参数/着色器拷进去 |
| 引用关系 | 标签依旧指向 `M_Old`，所以引用链完全不变，不改任何对象的材质标签 |
| 材质指定方式 | 弹出对话框，两个下拉框分别选「源材质（被替换的）」和「目标材质（提供内容的）」 |
| 作用范围 | 全场景（覆盖语义下材质只有一份，天然全场景生效） |
| 旧材质处理 | 保留在材质管理器，不删除；事后提示影响了多少对象/标签 |
| 材质名 | 保留 `M_Old` 原名，不跟随目标材质改名 |
| 材质类型 | 标准/物理、Redshift、Octane 等混用；**类型不一致必须给人类可读警告，不允许崩溃** |

## 3. 为什么是「覆盖内容」而不是「重定向引用」

用户选择了覆盖，好处是：所有现有引用、渲染队列、XRef、MoGraph 引用都不会断；
代价是材质对象是共享的，改一处全场生效——这与用户「多个对象共用同一个材质球」的场景正好吻合。

## 4. 功能范围

### v1 包含

1. 对话框：列出当前工程的材质球（名称 + 类型），选源 / 选目标，一键执行。
2. 参数覆盖：遍历目标材质的 Description，逐个参数写入源材质。
   - 数值 / 向量 / 颜色 / 字符串 / 布尔 / 时间 / 文件名 直接赋值。
   - 着色器（`BaseShader`）**深拷贝**：克隆后插入源材质再赋值，**绝不移动**目标材质自己的着色器。
   - 组（GROUP）、按钮、分隔符、静态文本等非数据项跳过。
   - 目标材质没有的参数跳过并记入报告。
3. 引用统计：遍历全场景对象层级（含子级、实例内部标签），统计被影响的对象数与标签数，用于结果提示。
4. 撤销：`StartUndo` → `AddUndo(UNDOTYPE_CHANGE, 源材质)` + 新克隆着色器 `UNDOTYPE_NEW` → `EndUndo`，一次 Ctrl+Z 可完整回退。
5. 类型不一致二次确认：`M_Old` 与 `M_New` 的 `GetType()` 不同（如标准材质 → Redshift 材质）时，先弹确认框说明「只能尽量拷贝同名参数，效果可能不完整」。
6. 结果报告：已拷贝参数数、已克隆着色器数、跳过参数数（前 5 个名字）、失败参数数、影响对象/标签数。

### v1 不包含（明确写清，避免预期错位）

- 节点材质（Node Material）内部节点图的完整迁移 —— 走参数层尽力拷贝，并在报告里提示需人工检查。
- 用户数据（User Data）容器迁移。
- 只影响「部分对象」的局部替换（覆盖语义下不可能，已在确认阶段跟用户说明）。
- 材质球改名 / 删除 / 合并。

## 5. 部署形态

单一自包含文件 `MaterialReplace.pyp`，不依赖同目录其它 Python 模块（C4D 的 `sys.path` 在插件与脚本两种模式下不可靠），通过 `__file__` 后缀区分运行模式：

- `.pyp` → 插件模式：`RegisterCommandPlugin` 注册命令，出现在 C4D「扩展」菜单，注册 ID `1056001`。
- `.py` → 脚本模式：放进用户脚本目录（`%APPDATA%\Maxon\Maxon Cinema 4D 2023_*\library\scripts`），出现在「脚本」菜单，运行即弹窗。

插件目录 `C:\Program Files\Maxon Cinema 4D 2023\plugins` 需要管理员权限，脚本目录不需要 —— 两种都给，用户按权限选。

## 6. 技术要点与风险

| 风险 | 处置 |
| --- | --- |
| 不同版本 Python API 差异（`InsertShader` 是否存在、`GetParameter` 签名） | 全部 API 调用包 `try/except` + 降级路径（`InsertUnder` 兜底、`mat[id]` 兜底） |
| 第三方材质 Description 参数类型未知 | 用「取到的 Python 值类型」判断（数值/向量→赋值，BaseList2D→克隆），不硬编码白名单 |
| 克隆着色器导致目标材质被掏空 | 顺序保证：先 `GetClone()`，再插到源材质，源材质对象始终不动 |
| 覆盖后材质缩略图不刷新 | 完成后 `dst.Update(True)` |
| 误操作 | 二次确认框 + 完整撤销 + 不动材质管理器结构 |

## 7. 验收标准

- [ ] 对话框能正确列出工程内全部材质（含第三方材质）。
- [ ] 选同类型材质覆盖后，`M_Old` 的通道参数与 `M_New` 一致，`M_Old` 名字不变。
- [ ] 着色器（如颜色通道里的噪波）被完整复制，且 `M_New` 自身的着色器仍在。
- [ ] 场景中所有引用 `M_Old` 的对象外观同步变化，标签数量不变。
- [ ] 一次 Ctrl+Z 能完全回退。
- [ ] 类型不一致时先警告、可取消。
- [ ] 逻辑层单元测试全绿（用 C4D API 桩件，可在无 C4D 环境运行）。


## 8. 踩坑记录（v1 → v2）

### 症状

v1 在真实 C4D 2023 里点执行，结果区显示「参数拷贝：0 项 / 着色器克隆：0 个」，
但引用统计正常（2 个对象 2 个标签），说明场景遍历没问题，卡在材质参数读取。

### 根因

v1 按 `for pid, entry in mat.GetDescription(...)` 二元组解包，并加了
`if not isinstance(pid, int): continue` 过滤。真实 API 是：

```python
for bc, paramid, groupid in op.GetDescription(c4d.DESCFLAGS_DESC_NONE):
    ...
```

- 迭代产出**三元组** `(BaseContainer, DescID, DescID)` → 二元解包直接 ValueError，
  被 `except: continue` 吃掉；
- 参数 id 是 `c4d.DescID`，不是 `int` → 即使解包对了也会被 int 过滤掉；
- `GetParameter/SetParameter` 的入参是 `DescID`，`SetParameter` 返回 `bool`。

结果：循环体一次没执行，0 拷贝 / 0 跳过 / 0 失败，与截图完全一致。

### 为什么单元测试没拦住

`tests/fake_c4d.py` v1 是按**我的错误假设**写的桩件：description 迭代产出 `(id, entry)`、
id 是 int。桩件和实现犯了同一个错，测试自然全绿。这是"测试通过 ≠ 行为正确"的典型。

### 修复

1. 桩件按官方文档重写：`DescID` 类、三元组迭代、`SetParameter` 返回 bool；
2. 实现改 `_iter_description()`，兼容三元组（并留二元兜底）；
3. 新增回归测试 `test_description_iteration_yields_descid_not_int`、
   `test_iter_description_reads_all_parameters`，锁死这三条语义；
4. 报告增加 `params_seen`，把"读到多少"和"写进多少"分开显示，避免 0 值误判为节点材质；
5. 名称参数（`ID_BASELIST_NAME`）不再计入拷贝统计 —— 它永远拷得成功，会掩盖
   "一个都没写进去"的真实情况。

### 教训

写宿主 API 适配层时，桩件必须逐条对照官方文档签名，否则测试只是自我确认。
文档地址：`developers.maxon.net/docs/py/2023_2/modules/c4d/Description/index.html`。

## 9. v4：材质选择改为拖拽 / 拾取

### 原方案的问题

v3 用两个 `AddComboBox` 列材质，实际运行中下拉项被截断成「1」「3」，用户根本看不出选的是哪个球，
存在选反方向的真实风险。

### 新方案

用 C4D 原生链接框 `c4d.CUSTOMGUI_LINKBOX`：

```python
self.AddCustomGui(gid, c4d.CUSTOMGUI_LINKBOX, "", c4d.BFH_SCALEFIT, 0, 0)
gui = self.FindCustomGui(gid, c4d.CUSTOMGUI_LINKBOX)
gui.SetLink(mat)          # 官方签名 SetLink(obj)
gui.GetLink(doc, c4d.Mmaterial)   # 官方签名 GetLink(doc, instance)
```

链接框原生支持从材质管理器**拖放**材质球（它是 BaseList2D 的 link box），并自带缩略图和名字，
不会再出现「只显示 1、3」的情况。

另加三个按钮兜底与提效：

| 按钮 | 行为 |
| --- | --- |
| 拾取选中 → 源 / 目标 | 取 `doc.GetActiveMaterials()`（回退 `GetActiveMaterial()`）第一个材质填进链接框 |
| 交换 | 源/目标对调 |
| 清空 | 两个链接框一起清空 |

「拾取」这条路径不依赖拖放，即使某个版本链接框不接受材质拖入，也能正常选中。

### 兼容处理

- `SetLink` 官方是 `SetLink(obj)`，但存在 `SetLink(doc, obj)` 的旧写法 → 两种依次尝试；
- `GetLink` 官方是 `GetLink(doc, instance)`，论坛/旧文档有无参形式 → 先用 `(doc, Mmaterial)`、
  `(doc, BaseMaterial)`，最后退回 `()`；
- 拖入的不是材质球（比如拖了个对象）→ `_is_material()` 拦截，统计行明确提示
  「源链接框里的对象不是材质球：xxx」，执行时再拦截一次，不会静默当成材质用；
- 极老版本若没有 `CUSTOMGUI_LINKBOX`，自动退回下拉框（`_use_combo`）。

### 测试

桩件新增 `LinkBoxGui`（`SetLink`/`GetLink`）、`AddCustomGui`/`FindCustomGui`、
`doc.GetActiveMaterials()`；新增 9 条用例覆盖拖放、拾取、交换、清空、非材质拦截、
两种签名兼容、缺材质时的提示。

## 10. v5：真实日志揭示的根因 —— Redshift 节点材质

### 证据（用户实际运行的诊断日志）

```
源材质：橙色 | type=1036224
目标材质：白色1 | type=1036224
读到参数：32 | 写入：7 | 克隆：0 | 跳过：5 | 失败：0
[04] 图标文件/ ID   | 已写入
[05] 图标颜色        | 已写入
[06] 颜色            | 已写入
[13] 主体            | 已写入
[14] 指定            | 已写入
[19] 参数(20000,133,0) | GvNode(...) | 对象链接，跳过
[21] 参数(20001,133,0) | GvNode(...) | 对象链接，跳过
[23] 参数(20002,133,0) | GvNode(...) | 对象链接，跳过
[25] 参数(20003,133,0) | GvNode(...) | 对象链接，跳过
```

`type=1036224` 是 **Redshift 材质**。写进去的 7 项全是 `ID_BASELIST_*` 级别的外壳属性
（图标文件、图标颜色、预览尺寸、动画预览），**外观一个字节都没动**。
真正的外观是 4 个 `GvNode`（RS材质 / 3C材质纹理 / RS凹凸贴图），它们在 Description 里
以 BaseList2D 链接的形式出现，逐参数 `SetParameter` 搬不动（节点之间有端口连线，
单独拷节点等于拷一堆断线的零件）。

### 结论

**逐参数拷贝对节点材质在原理上无效**，不是实现 bug。之前的「7/32」看起来像部分成功，
实际是全部无效 —— 这也是用户两次反馈「替换不生效」的根本原因。

### 方案 A：整材质 CopyTo

`C4DAtom.CopyTo(dst, flags)` 是 C4D 里复制整个 atom（含分支/子对象）的标准手段，
材质管理器里 Ctrl+拖拽复制节点材质就是走这条路径。因此在节点材质上：

1. `src.CopyTo(dst, COPYFLAGS_NONE)`（不能用 `NO_BRANCHES`，节点图属于分支数据）；
2. 回读 `_graph_signature(dst)`，与 `_graph_signature(src)` 比对节点数量与类型；
3. 一致才算成功（`report.method == "copyto"`），不一致则标记 `graph_mismatch` 并落回逐参数，
   同时在结果区明确写「这是节点材质……请改用重定向引用」。

失败不是静默的：日志里会写「整材质拷贝 CopyTo：返回失败（…）」与「节点图核对不一致」。

### 方案 B：重定向引用（保底且必然有效）

改材质标签的引用，不读材质内容，所以对任何材质类型都成立：

```
for (obj, tag) in collect_material_tags(doc, old_mat):
    doc.AddUndo(UNDOTYPE_CHANGE, tag)
    tag.SetParameter(TEXTURETAG_MATERIAL, new_mat)   # 失败再退回 tag[...] = new_mat
```

- 全部包在 `StartUndo/EndUndo` 里，单步可撤销；
- 切换后重算旧材质引用数 `remaining`，为 0 才说明真换完了；
- 「删除旧材质」是可选勾选，且只在 `remaining == 0` 且无失败时执行，否则保留并说明原因。

### 节点材质判定必须收窄

第一版用「description 里有 BaseList2D 值」判定节点材质，把挂了颜色着色器的**普通材质**
也误判成节点材质（普通材质的颜色通道里就是 BaseShader）。改为只认
`c4d.modules.graphview.GvNode`（拿不到模块时按类名兜底），并补了两条回归测试防止再犯。

### 模式默认值

默认仍是「覆盖内容」，与用户最初的选择一致；但当源材质被识别为节点材质时，
统计行第二行直接提示「节点材质，改外观请用「重定向引用」」，让用户在点执行之前就知道。

## 11. v6：确认语义 —— 这就是 Alt 拖拽的批量版

### 用户的关键提问

> 和按住 Alt 拖动材质覆盖的原理一样吗，不用管材质的属性贴图啥的？

完全一样。C4D 里把材质拖到已有材质标签的对象上时，默认会**新建**一个纹理标签；
按住 Alt 拖放则是**替换现有标签里的材质引用**（不新建标签、不复制任何参数）。
底层动作就是一句：

```python
tag[c4d.TEXTURETAG_MATERIAL] = new_material
```

本工具的「重定向引用」模式与之逐字等价，只是把单个对象扩展成整个文档的所有标签。

### 因此调整如下

1. **默认模式改为「重定向引用」**，并排在下拉第一项，标注「同 Alt 拖拽，推荐」；
   用户说的"不用管材质属性贴图"正是这个语义，不需要每次都手动切。
2. `_mode()` 的异常回退也从 OVERWRITE 改为 REDIRECT —— 读不到下拉值时宁可只换引用，
   也不要在用户没要求的情况下去改材质内容（更安全的一侧）。
3. 标题、帮助文字、按钮文案改为「批量换引用（等同 Alt 拖拽）」/「一键替换引用」，
   让界面自解释，不必依赖文档。
4. 结果区第一屏就写明「只换引用：两个材质球的参数、贴图、节点全部原样未动」。
5. 统计行对节点材质不再"劝用户切换"，改为陈述："这是节点材质（Redshift 等）：已按重定向处理，
   只换引用，不需要拷贝节点。"

### 与 Alt 拖拽的差异（也是本工具的价值）

| 维度 | Alt 拖拽 | 本工具 |
| --- | --- | --- |
| 范围 | 一次一个对象 | 整个文档所有引用该材质的标签 |
| 定位 | 需要肉眼找哪些对象用了它 | 自动遍历，含任意层级的子对象 |
| 统计 | 无 | 报出对象数 / 标签数 / 剩余引用 |
| 撤销 | 一步 | 一步（StartUndo/EndUndo 包裹全部标签） |

### 新增回归测试

- `test_dialog_default_run_does_not_touch_material_content`：默认模式执行后，
  两个材质球的参数值必须一字未改（防止默认模式被悄悄改回覆盖）。
- `test_redirect_keeps_tag_own_settings`：纹理标签上的额外参数（偏移、平铺等）
  在重定向后必须保持原值。
- `test_redirect_report_says_it_matches_alt_drag`：结果文案必须声明"只换引用"。
- 原有 `test_dialog_redirect_mode_runs_redirect` 的断言从"默认覆盖"翻转为"默认重定向"。

状态：53 passed。

## 12. v7：界面精简 + 大预览

### 用户反馈

替换成功后提出两点：窗口精简到最小、不要多余描述和选项；材质球预览要大一点。

### 精简掉的东西

| 移除 | 原因 |
| --- | --- |
| 两行说明文字 | 工具只有一个动作，标题 + 两个标签就够 |
| 「替换方式」下拉（覆盖/重定向） | 用户确认语义就是 Alt 拖拽式的换引用，覆盖模式不再需要出现在界面 |
| 「只诊断」勾选 | 已不再需要试探；失败时才写日志，静默成功不打扰 |
| 「重定向后删除旧材质」勾选 | 有风险的可选项，默认不做；要删旧球手动删更直观 |
| 统计行（源/目标 + 引用数） | 与结果区、链接框重复；改名下的信息由预览与链接框直接承担 |

界面只剩：2 个大预览 + 2 个链接框 + 一排 4 个功能按钮 + 结果区 + 执行/关闭。窗口 430×330。

`_mode()` 保留并恒返回 `MODE_REDIRECT`，覆盖模式的引擎函数（`copy_material_content` 等）
与测试仍然保留，日后要恢复双模式不用重写。

### 大预览怎么做

关键事实：**链接框的图标尺寸不可调**。官方 LinkBoxGui 只暴露 `LINKBOX_HIDE_ICON`、
`LINKBOX_LAYERMODE`、`LINKBOX_NO_PICKER`、`LINKBOX_NODE_MODE` 四个开关，没有尺寸参数。
所以「把链接框调高就能放大预览」是行不通的。

方案：自己画。

```python
class MaterialPreview(c4d.gui.GeUserArea):
    SIZE = 76

    def GetMinSize(self):
        return self.SIZE, self.SIZE

    def DrawMsg(self, x1, y1, x2, y2, msg):
        bmp = mat.GetPreview()          # BaseMaterial.GetPreview(flags=0) -> BaseBitmap | None
        self.DrawBitmap(bmp, x1, y1, size, size,
                        0, 0, bmp.GetWidth(), bmp.GetHeight(),
                        c4d.BMP_ALLOWALPHA | c4d.BMP_NORMALSCALED)
```

- `DrawBitmap(bmp, wx, wy, ww, wh, x, y, w, h, mode)`：把位图 (x,y,w,h) 区域缩放绘制到
  目标区域 (wx,wy,ww,wh)，所以 64×64 的预览图能铺满 76×76 的方块。
- `GetPreview()` 返回 None（尚未计算缩略图）时退回 `GetIcon()`；两者都没有就画「空」/「无预览」占位。
- 拿到位图但 `DrawBitmap` 抛异常时也退到占位文字，`DrawMsg` 全程 try/except，
  任何情况下都不会让对话框崩掉。
- 链接框同时设 `LINKBOX_HIDE_ICON = True`，否则会出现「大预览 + 小图标」两个缩略图。

布局用 2 列网格：左列 = 预览（76×76），右列 = 一个 1 列子组（标签 + 链接框），两行各占 76 高。
两个子组用不同 id（`GRP_ROW_SRC` / `GRP_ROW_DST`），避免同 id 嵌套组。

### 刷新时机

`_sync_previews()` 在以下时机会被调用：`InitValues`、链接框 Command 回调、`BFM_ACTION`
（真实拖放后 C4D 走这里）、拾取、交换、清空、执行完成后。

### 日志策略改为「失败才写」

旧版每次执行都写 `材质替换_诊断.log`。现在只有 `report.failed > 0` 或
`tags_changed < tags_total` 时才写，正常成功不往硬盘落任何文件。

### 新增测试（53 → 62）

- 界面精简：没有 AddCheckbox、没有 AddComboBox、静态文本恰好只有「源材质」「目标材质」、
  按钮序列固定为六个。
- 两个 76×76 用户区都加进布局并成功 AttachUserArea。
- 链接框 customdata 里 `LINKBOX_HIDE_ICON` 为 True。
- 预览位图铺满整块区域（断言 `DrawBitmap` 目标矩形 = 0,0,76,76）。
- 无预览图时走占位文字且不抛异常；未选材质时显示「空」。
- 链接变化后预览材质与重绘次数同步更新。
- 成功不写日志、失败必写日志（monkeypatch `write_diagnostics_log` 记录调用）。

---

## 13. v8：撤掉自绘预览，回到官方图标并压缩窗口

v7 把预览做成 76×76 自绘区之后，实际观感反而更糟：链接框图标被隐藏后，
右侧只剩一条空槽 + 名字，左侧一块大色块，信息密度低、窗口却被撑到 430×330。
结论是——**C4D 的链接框本身就带缩略图，没必要自己画**。

### 改了什么

| 项 | v7 | v8 |
| --- | --- | --- |
| 缩略图 | `MaterialPreview(GeUserArea)` 自绘 76×76 | 链接框自带的官方小图标 |
| `LINKBOX_HIDE_ICON` | True（隐藏小图标） | 不设置，保持官方行为 |
| 标签位置 | 链接框上方独占一行 | 链接框左侧同一行（宽 44） |
| 结果区高度 | 84 | 40 |
| 按钮文案 | 拾取 → 源 / 拾取 → 目标 | 拾取源 / 拾取目标 |
| 窗口 | 430×330 | 262×196 |

### 布局结构

```
GRP_MAIN (1 列, 5 行)
├─ GRP_ROW_SRC (2 列)  [源材质][LNK_SRC ▣]
├─ GRP_ROW_DST (2 列)  [目标材质][LNK_DST ▣]
├─ GRP_PICK_BTN (4 列) 拾取源 拾取目标 交换 清空
├─ TXT_RESULT          高 40，不带 BFV_SCALEFIT（不随窗口拉伸）
└─ GRP_BTN (2 列)      一键替换引用 关闭
```

标签与链接框放同一行是关键：v7 把标签单独占一行，两行就多吃掉两条行高，
加上 76px 预览，窗口高度被顶到 330。同行后每行只需 18px。

### 删除的代码

`MaterialPreview` 类整体删除（含 `DrawMsg`/`GetMinSize`/`_bitmap`），
`_pre_src`/`_pre_dst`、`PRE_SRC`/`PRE_DST` 两个 ID、`AttachUserArea` 循环、
以及 `GRP_PICK` 空壳分组一并清掉。`_sync_previews()` 保留名字但职责缩小为
「校验链接框里是不是材质球」，链接变化时只做这一件事。

尺寸常量提到模块级，便于测试锁定：

```python
LINK_HEIGHT = 18      # 容得下官方图标
LABEL_WIDTH = 44
RESULT_HEIGHT = 40
DIALOG_WIDTH = 262
DIALOG_HEIGHT = 196
```

### 测试调整（62 条不变）

删除 4 条自绘预览用例（位图铺满、占位文字、重绘次数、空态「空」），
新增 4 条约束用例：

- `test_layout_has_no_self_drawn_preview_area`：没有 AddUserArea/AttachUserArea，
  且 `mr.MaterialPreview` 与 `dlg._pre_src` 都不存在（防止悄悄回退）。
- `test_linkbox_keeps_its_official_icon`：customdata 里 `LINKBOX_HIDE_ICON` 必须为 False。
- `test_linkbox_uses_compact_height`：两个链接框高度都等于 `LINK_HEIGHT`。
- `test_label_and_linkbox_share_one_row`：两个 row 分组都是 2 列，且组内顺序是
  GroupBegin → AddStaticText → AddCustomGui。
- 另加 `test_result_box_is_short`（≤48）与 `test_dialog_window_is_compact`（≤280×210）。

桩件同步：`GroupBegin` 记录 `(cid, cols, rows)`、`AddCustomGui` 记录 `inith`、
`Open` 记录 `(defaultw, defaulth)` 到 `open_size`。

---

## 14. v9：取消结果框，拾取并入行内，四按钮同排

v8 实测截图暴露两个问题：窗口 262 宽仍然显得空，标签「目标材质」被压成
「目标材」；结果框占掉近一半高度，但它大部分时候只有一行字。

### 最终布局（三行）

```
GRP_MAIN (1 列, 3 行)
├─ GRP_ROW_SRC (3 列)  [源 36][LNK_SRC ▣][拾取 46]
├─ GRP_ROW_DST (3 列)  [目标36][LNK_DST ▣][拾取 46]
└─ GRP_BTN     (4 列)  替换 | 交换 | 清空 | 关闭
```

| 项 | v8 | v9 |
| --- | --- | --- |
| 标签文案 | 源材质 / 目标材质 | 源 / 目标（宽 36） |
| 拾取按钮 | 独立一整排 4 个 | 各自贴在对应链接框右侧 |
| 底部按钮 | 替换 + 关闭（2 列） | 替换/交换/清空/关闭（4 列） |
| 结果框 | 40px 多行文本 | **删除** |
| 窗口 | 262×196 | 224×108 |

### 结果反馈去哪了

删掉 `AddMultiLineEditText` 后不能静默执行，否则用户不知道换了几个。
改成两级输出，都不占窗口空间：

1. **标题栏**：`材质替换 · 替换 2 个标签 → 主色.3`，由 `format_redirect_brief()`
   生成单行短句（失败时是 `替换 1/9，失败 8`）。
2. **C4D 状态栏**：`c4d.StatusSetText(detail)`，出问题时这里会带上诊断日志路径。

出错仍然走 `c4d.gui.MessageDialog` 弹窗（原来就有）。`_set_result(brief, detail)`
同时负责这两处，`_warn()` 不再写界面文本，只弹窗。

### 新增 `format_redirect_brief()`

`format_redirect_report()` 那份多行文本留给日志和测试；界面用新的单行函数：

```python
def format_redirect_brief(report, old_mat, new_mat):
    if report.failed:
        return "替换 %d/%d，失败 %d" % (...)
    if report.tags_total and report.tags_changed < report.tags_total:
        return "替换 %d/%d，部分未换" % (...)
    return "替换 %d 个标签 → %s" % (report.tags_changed, _mat_name(new_mat))
```

### 测试调整（62 → 63）

- `test_layout_has_no_result_box`：没有 `AddMultiLineEditText`，且 `dlg.TXT_RESULT` 不存在。
- `test_pick_button_sits_right_after_each_linkbox`：行分组为 3 列，组内顺序
  GroupBegin → AddStaticText → AddCustomGui → AddButton。
- `test_bottom_buttons_share_one_row_in_order`：`GRP_BTN` 为 4 列，按钮顺序
  替换/交换/清空/关闭，紧跟 GroupEnd。
- 断言反馈的用例统一改走 `_feedback(dlg)`：把标题、状态栏、最近弹窗拼成一个串，
  这样反馈实现从「结果框」换到「标题+状态栏」时断言不必重写成两套。
- 桩件新增 `STATUS_TEXTS` 与 `StatusSetText()`，`SetTitle` 额外记录 `self.title`；
  配合 `autouse` 夹具每条用例前清空。

> 注意：`GroupEnd` 的记录是单元素元组，拼接比较时要补 `None` 占位，
> 否则 `IndexError`。

---

## 15. v10：取消关闭按钮

窗口有标题栏的 ×，底部再放一个「关闭」纯属重复，删掉。

- `GRP_BTN` 从 4 列改 3 列：替换 | 交换 | 清空。
- 删除 `BTN_CLOSE` 常量与 `Command()` 里对应的 `self.Close()` 分支。
- 关窗方式：标题栏 ×（C4D async dialog 默认行为，不需要额外 `AskClose()`）。

按钮每格从 52px 变 69px，文字更宽松。

测试 63 → 64：`test_bottom_buttons_share_one_row_in_order` 改为断言 3 列、
`seq[start+1:start+4]` 三个按钮、`seq[start+4]` 是 GroupEnd；
新增 `test_no_close_button`（按钮表里没有「关闭」，且 `dlg.BTN_CLOSE` 不存在）。

---

## 16. 为什么窗口拉不动（自由拉伸）

用户在 C4D 里发现窗口拖不大。原因不在 `Open()`，而在布局：

**C4D 的 GeDialog 尺寸 = 布局的最小尺寸 + 可伸缩元素分到的余量。**
当整棵布局树里没有任何一个控件带 `BFV_SCALEFIT`（纵向可伸缩）时，
纵向就没有「受力点」，窗口高度被钉死在最小尺寸；拖边缘时边框会跟着动，
松手立刻回弹，看起来就是「不支持自由拉伸」。

v9 把这个条件破坏了两处：

1. 删掉结果框（原来唯一带 `BFV_SCALEFIT` 的控件，它会把多余高度吃掉）；
2. 主容器 `GRP_MAIN` 的 flag 从 `BFH_SCALEFIT | BFV_SCALEFIT` 降级成只有 `BFH_SCALEFIT`。

横向其实一直是通的（链接框 `BFH_SCALEFIT`），但纵向被锁住后整体表现就是拽不动。

### 修法

```python
# 1. 主容器恢复双向伸缩
self.GroupBegin(self.GRP_MAIN, c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 1, 4, "")

# 2. 按钮行上方放一个空静态文本当「纵向吸收器」
self.AddStaticText(self.SPACER,
                   c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 0, 0, "", 0)
```

效果：拉宽 → 链接框变长（文字更完整）；拉高 → 空白区变高、按钮沉底。
初始尺寸仍是 224×108，C4D 只是不再锁死上限。

C4D Python 没有专门的 `AddSpacer()`，空 `AddStaticText` 是社区通行做法。

测试 64 → 65：新增 `test_layout_is_freely_resizable`，断言 `GRP_MAIN` 的 flag
同时含 `BFH_SCALEFIT` 与 `BFV_SCALEFIT`，且存在一个 `name == ""` 的静态文本占位。
桩件 `GroupBegin` 记录追加 `flags`，便于这类断言。

