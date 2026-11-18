# 实施计划（TDD）

## 任务切分

| # | 任务 | 文件 | 验证 |
| --- | --- | --- | --- |
| 1 | 写 C4D API 桩件（无 C4D 也能跑的单测基础） | `tests/fake_c4d.py` | 桩件自身可导入，`as_module()` 返回带 `gui`/`plugins` 子模块的对象 |
| 2 | 先写失败测试：引用统计、参数覆盖、着色器克隆、类型警告、撤销、参数校验 | `tests/test_material_replace.py` | `python -m pytest` → 全红（模块不存在） |
| 3 | 实现核心逻辑（`collect_material_usage` / `copy_material_content` / `replace_material`） | `MaterialReplace.pyp` | 测试转绿 |
| 4 | 实现对话框 UI（双下拉 + 统计 + 执行 + 结果区） | 同上 | 代码审查：控件 ID 唯一、Command 分支全覆盖、异常不弹出到用户面前 |
| 5 | 双入口：`.pyp` 插件模式 / `.py` 脚本模式 | 同上 | `__file__` 后缀分支正确，脚本模式不注册插件 |
| 6 | 安装到用户脚本目录（无需管理员） | `install.bat` + 手动复制 | 目录内文件存在 |
| 7 | 写使用说明（含快捷键绑定步骤） | `README.md` | — |

## TDD 顺序

1. **RED**：写完测试跑一遍，确认全部失败且失败原因是「模块/函数缺失」，不是测试写错。
2. **GREEN**：一次性写最小实现让测试通过，不提前加未测试的功能。
3. **REFACTOR**：抽公共辅助函数（`_get_param` / `_set_param` / `_insert_shader`），保持测试全绿。

## 关键约束

- 核心函数不依赖 `c4d.gui`，UI 与逻辑分离，逻辑可测。
- 所有 `c4d` API 调用包 `try/except`，宁可少拷一个参数也不能抛异常中断。
- 参数拷贝顺序：先克隆着色器 → 再写参数，避免「参数指向已被移走的对象」。
