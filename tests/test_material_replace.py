"""材质替换核心逻辑单元测试。

运行：python -m pytest tests -q
桩件 tests/fake_c4d.py 按官方文档语义实现：
- Description 迭代产出 (BaseContainer, DescID, DescID)
- 参数 id 是 DescID，不是 int
- SetParameter 返回 bool

历史回归：v1 按 (id, entry) 二元组 + isinstance(pid, int) 写，
在真实 C4D 里所有参数被过滤掉，结果 0 拷贝。见 test_description_* 用例。
"""

import io
import importlib.machinery
import importlib.util
import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fake_c4d as fc  # noqa: E402

sys.modules.setdefault("c4d", fc.as_module())

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN_FILE = ROOT / "MaterialReplace.pyp"


def _load_plugin():
    loader = importlib.machinery.SourceFileLoader("material_replace_ut", str(PLUGIN_FILE))
    spec = importlib.util.spec_from_loader("material_replace_ut", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


mr = _load_plugin()


# ---------------------------------------------------------------- API 语义回归
def test_description_iteration_yields_descid_not_int():
    mat = fc.make_material("M_A")
    desc = mat.GetDescription(fc.DESCFLAGS_DESC_0)
    seen = 0
    for bc, pid, groupid in desc:
        assert isinstance(pid, fc.DescID), "真实 API 给的是 DescID"
        assert not isinstance(pid, int)
        assert bc[fc.DESC_NAME]
        seen += 1
    assert seen > 0


def test_iter_description_reads_all_parameters():
    mat = fc.make_material("M_A")

    items = mr._iter_description(mat)

    assert len(items) == 7
    names = [name for _, name, _ in items]
    assert "颜色" in names
    assert all(pid is not None for pid, _, _ in items)


# ---------------------------------------------------------------- 引用统计
def test_collect_usage_counts_objects_and_tags_across_hierarchy():
    m1 = fc.make_material("M_Old")
    m2 = fc.make_material("M_Other")
    cube = fc.make_object("Cube", [fc.make_texture_tag(m1), fc.make_texture_tag(m2)])
    child = fc.make_object("Cube.1", [fc.make_texture_tag(m1)])
    fc.link_siblings(cube, [child])
    sphere = fc.make_object("Sphere", [fc.make_texture_tag(m1)])
    doc = fc.build_document([cube, sphere], [m1, m2])

    usage = mr.collect_material_usage(doc, m1)

    assert usage.tags == 3
    assert usage.objects == 3
    assert sorted(usage.names) == ["Cube", "Cube.1", "Sphere"]


def test_collect_usage_ignores_non_texture_tags():
    m1 = fc.make_material("M_Old")
    other_tag = fc.BaseTag("Phong", 5600, {})
    obj = fc.make_object("Cube", [other_tag])
    doc = fc.build_document([obj], [m1])

    usage = mr.collect_material_usage(doc, m1)

    assert usage.tags == 0
    assert usage.objects == 0


def test_collect_usage_on_empty_scene():
    m1 = fc.make_material("M_Old")
    doc = fc.build_document([], [m1])

    usage = mr.collect_material_usage(doc, m1)

    assert usage.tags == 0
    assert usage.objects == 0
    assert usage.names == []


# ---------------------------------------------------------------- 参数覆盖
def test_copy_overwrites_matching_parameters():
    new_mat = fc.make_material("M_New", params={
        fc.P_COLOR: (fc.DTYPE_COLOR, fc.Vector(1.0, 0.0, 0.0)),
        fc.P_ROUGH: (fc.DTYPE_REAL, 0.9),
        fc.P_NAME_PARAM: (fc.DTYPE_STRING, "from_new"),
    })
    old_mat = fc.make_material("M_Old")
    doc = fc.build_document([], [new_mat, old_mat])

    report = mr.copy_material_content(doc, old_mat, new_mat)

    assert fc.get_param(old_mat, fc.P_COLOR) == fc.Vector(1.0, 0.0, 0.0)
    assert fc.get_param(old_mat, fc.P_ROUGH) == pytest.approx(0.9)
    assert fc.get_param(old_mat, fc.P_NAME_PARAM) == "from_new"
    assert report.params_seen == 7
    assert report.params_copied >= 3
    assert report.params_failed == []


def test_copy_keeps_destination_material_name():
    new_mat = fc.make_material("M_New")
    old_mat = fc.make_material("M_Old")
    doc = fc.build_document([], [new_mat, old_mat])

    mr.copy_material_content(doc, old_mat, new_mat)

    assert old_mat.GetName() == "M_Old"


def test_copy_reports_parameters_missing_in_destination():
    new_mat = fc.make_material("M_New", params={
        fc.P_ONLY_SRC: (fc.DTYPE_REAL, 0.25),
    })
    old_mat = fc.make_material("M_Old")
    doc = fc.build_document([], [new_mat, old_mat])

    report = mr.copy_material_content(doc, old_mat, new_mat)

    assert "仅源材质独有" in report.params_skipped
    assert report.params_failed == []


def test_copy_skips_group_and_button_entries():
    new_mat = fc.make_material("M_New")
    old_mat = fc.make_material("M_Old")
    doc = fc.build_document([], [new_mat, old_mat])

    report = mr.copy_material_content(doc, old_mat, new_mat)

    assert report.params_failed == []
    assert "分组" not in report.params_failed
    assert "按钮" not in report.params_failed


def test_copy_clones_shader_without_stealing_from_source():
    noise = fc.BaseShader("噪波", 1011145, {3000: (fc.DTYPE_REAL, 0.7)})
    new_mat = fc.make_material("M_New")
    new_mat.InsertShader(noise)
    new_mat._params[fc.DID(fc.P_SHADER)] = (fc.DTYPE_BASELISTLINK, noise)

    old_mat = fc.make_material("M_Old")
    doc = fc.build_document([], [new_mat, old_mat])

    report = mr.copy_material_content(doc, old_mat, new_mat)

    copied = old_mat._params[fc.DID(fc.P_SHADER)][1]
    assert copied is not None
    assert copied is not noise
    assert copied.GetName() == "噪波"
    assert report.shaders_copied == 1
    assert new_mat._params[fc.DID(fc.P_SHADER)][1] is noise
    assert noise._parent is new_mat


def test_copy_clones_gradient_child():
    grad = fc.Gradient("渐变")
    new_mat = fc.make_material("M_New")
    new_mat.InsertShader(grad)
    new_mat._params[fc.DID(fc.P_GRADIENT)] = (fc.DTYPE_BASELISTLINK, grad)

    old_mat = fc.make_material("M_Old", params={
        fc.P_GRADIENT: (fc.DTYPE_BASELISTLINK, None),
    })
    doc = fc.build_document([], [new_mat, old_mat])

    report = mr.copy_material_content(doc, old_mat, new_mat)

    assert old_mat._params[fc.DID(fc.P_GRADIENT)][1] is not grad
    assert report.shaders_copied == 1


def test_copy_detects_type_mismatch():
    new_mat = fc.make_material("M_RS", type_id=fc.Mredshift)
    old_mat = fc.make_material("M_Std", type_id=fc.Mmaterial)
    doc = fc.build_document([], [new_mat, old_mat])

    report = mr.copy_material_content(doc, old_mat, new_mat)

    assert report.type_mismatch is True


def test_copy_same_type_has_no_mismatch_flag():
    new_mat = fc.make_material("M_A")
    old_mat = fc.make_material("M_B")
    doc = fc.build_document([], [new_mat, old_mat])

    report = mr.copy_material_content(doc, old_mat, new_mat)

    assert report.type_mismatch is False


def test_copy_rejects_same_material():
    mat = fc.make_material("M_A")
    doc = fc.build_document([], [mat])

    with pytest.raises(ValueError):
        mr.copy_material_content(doc, mat, mat)


def test_copy_rejects_missing_material():
    mat = fc.make_material("M_A")
    doc = fc.build_document([], [mat])

    with pytest.raises(ValueError):
        mr.copy_material_content(doc, None, mat)
    with pytest.raises(ValueError):
        mr.copy_material_content(doc, mat, None)


# ---------------------------------------------------------------- 撤销
def test_copy_wraps_changes_in_single_undo_step():
    new_mat = fc.make_material("M_New")
    old_mat = fc.make_material("M_Old")
    doc = fc.build_document([], [new_mat, old_mat])

    mr.copy_material_content(doc, old_mat, new_mat)

    assert doc.undo_log[0][0] == "start"
    assert doc.undo_log[-1][0] == "end"
    changes = [e for e in doc.undo_log if e[0] == "add"]
    assert any(e[1] == fc.UNDOTYPE_CHANGE and e[2] is old_mat for e in changes)


# ---------------------------------------------------------------- 端到端
def test_replace_material_returns_usage_and_report():
    new_mat = fc.make_material("M_New", params={
        fc.P_COLOR: (fc.DTYPE_COLOR, fc.Vector(0.0, 1.0, 1.0)),
    })
    old_mat = fc.make_material("M_Old")
    a = fc.make_object("A", [fc.make_texture_tag(old_mat)])
    b = fc.make_object("B", [fc.make_texture_tag(old_mat)])
    doc = fc.build_document([a, b], [new_mat, old_mat])

    result = mr.replace_material(doc, old_mat, new_mat)

    assert result.usage.tags == 2
    assert result.usage.objects == 2
    assert fc.get_param(old_mat, fc.P_COLOR) == fc.Vector(0.0, 1.0, 1.0)
    assert result.report.params_copied >= 1


def test_list_materials_returns_stable_int_ids():
    m1 = fc.make_material("M_1")
    m2 = fc.make_material("M_2")
    doc = fc.build_document([], [m1, m2])

    items = mr.list_materials(doc)

    assert len(items) == 2
    ids = [i for i, _ in items]
    assert len(set(ids)) == 2
    assert all(isinstance(i, int) for i in ids)
    labels = [label for _, label in items]
    assert "M_1" in labels[0]
    assert "M_2" in labels[1]


def test_plugin_mode_detection_uses_file_suffix():
    assert mr.is_plugin_mode(str(ROOT / "MaterialReplace.pyp")) is True
    assert mr.is_plugin_mode(str(ROOT / "材质替换.py")) is False


# ---------------------------------------------------------------- 结果文案
def test_format_report_contains_counts_and_usage():
    new_mat = fc.make_material("M_New")
    old_mat = fc.make_material("M_Old")
    a = fc.make_object("A", [fc.make_texture_tag(old_mat)])
    doc = fc.build_document([a], [new_mat, old_mat])

    text = mr.format_report(mr.replace_material(doc, old_mat, new_mat))

    assert "参数拷贝" in text
    assert "影响对象：1 个对象 / 1 个材质标签" in text


def test_format_report_warns_when_no_parameter_written():
    new_mat = fc.make_material("M_Node")
    old_mat = fc.BaseMaterial("M_Old", fc.Mmaterial, {})
    doc = fc.build_document([], [new_mat, old_mat])

    text = mr.format_report(mr.replace_material(doc, old_mat, new_mat))

    assert "一个都没写进目标材质" in text


def test_format_report_warns_when_description_unreadable():
    class NoDescMaterial(fc.BaseMaterial):
        def GetDescription(self, flags=0):
            return fc.FakeDescription([])

    new_mat = NoDescMaterial("M_Weird", fc.Mmaterial, {})
    old_mat = fc.make_material("M_Old")
    doc = fc.build_document([], [new_mat, old_mat])

    result = mr.replace_material(doc, old_mat, new_mat)
    text = mr.format_report(result)

    assert result.report.params_seen == 0
    assert "没能从源材质读到任何参数描述" in text


def test_format_report_hints_when_material_unused():
    new_mat = fc.make_material("M_New")
    old_mat = fc.make_material("M_Old")
    doc = fc.build_document([], [new_mat, old_mat])

    text = mr.format_report(mr.replace_material(doc, old_mat, new_mat))

    assert "没有对象引用源材质" in text


# ---------------------------------------------------------------- 诊断模式
def test_dry_run_does_not_modify_but_reports_plan():
    new_mat = fc.make_material("M_New", params={
        fc.P_COLOR: (fc.DTYPE_COLOR, fc.Vector(1.0, 0.0, 0.0)),
    })
    old_mat = fc.make_material("M_Old")
    a = fc.make_object("A", [fc.make_texture_tag(old_mat)])
    doc = fc.build_document([a], [new_mat, old_mat])

    result = mr.replace_material(doc, old_mat, new_mat, dry_run=True)

    assert fc.get_param(old_mat, fc.P_COLOR) == fc.Vector(1.0, 1.0, 1.0)
    assert result.report.dry_run is True
    assert result.report.params_copied >= 1
    assert result.report.verified_total == 0
    assert doc.undo_log == []
    assert "没有修改任何材质" in mr.format_report(result)


def test_forced_write_when_setparameter_rejects():
    new_mat = fc.make_material("M_New", params={
        fc.P_ROUGH: (fc.DTYPE_REAL, 0.85),
    })
    old_mat = fc.make_material("M_Old")
    old_mat.readonly_params = (fc.P_ROUGH,)
    doc = fc.build_document([], [new_mat, old_mat])

    report = mr.copy_material_content(doc, old_mat, new_mat)

    assert fc.get_param(old_mat, fc.P_ROUGH) == pytest.approx(0.85)
    assert any("强制写入成功" in line for line in report.details)


def test_verify_pass_detects_values_that_did_not_stick():
    class StuckMaterial(fc.BaseMaterial):
        """SetParameter 返回 True 但值没变，用来验证回读校验能发现。"""

        def SetParameter(self, did, value, flags=0):
            return True

    new_mat = fc.make_material("M_New", params={
        fc.P_COLOR: (fc.DTYPE_COLOR, fc.Vector(0.0, 0.0, 1.0)),
    })
    old_mat = StuckMaterial("M_Old", fc.Mmaterial, fc.make_material("tmp")._params)
    doc = fc.build_document([], [new_mat, old_mat])

    report = mr.copy_material_content(doc, old_mat, new_mat)

    assert report.verified_total > 0
    assert report.verified_ok < report.verified_total
    assert any("回读校验不一致" in line for line in report.details)


def test_details_include_parameter_id_and_result():
    new_mat = fc.make_material("M_New")
    old_mat = fc.make_material("M_Old")
    doc = fc.build_document([], [new_mat, old_mat])

    result = mr.replace_material(doc, old_mat, new_mat)
    text = mr.format_details(result)

    assert "C4D 材质替换诊断日志" in text
    assert "源材质：M_New" in text
    assert "目标材质：M_Old" in text
    assert "id=" in text
    assert "已写入" in text


def test_name_falls_back_to_desc_ident():
    class IdentMaterial(fc.BaseMaterial):
        def GetDescription(self, flags=0):
            return fc.DescIterator([(fc.DESC_IDENT_ONLY, fc.DTYPE_REAL, "MATERIAL_COLOR_COLOR")])

    mat = IdentMaterial("M_x", fc.Mmaterial, {})
    items = mr._iter_description(mat)

    assert items and items[0][1] == "MATERIAL_COLOR_COLOR"


def test_write_diagnostics_log_creates_file(tmp_path):
    text = "C4D 材质替换诊断日志\n测试内容"
    path = mr.write_diagnostics_log(text)

    assert path
    written = io.open(path, encoding="utf-8-sig").read()
    assert "测试内容" in written
    try:
        os.remove(path)
    except Exception:
        pass


# ---------------------------------------------------------------- 对话框流程
def _box(dlg, gid):
    return dlg.FindCustomGui(gid, fc.CUSTOMGUI_LINKBOX)


def _feedback(dlg):
    """界面没有结果框了，反馈在标题栏 / 状态栏 / 弹窗里，拼起来一起断言。"""
    status = fc.STATUS_TEXTS[-1] if fc.STATUS_TEXTS else ""
    dialogs = sys.modules["c4d"].gui.dialogs
    dialog = dialogs[-1] if dialogs else ""
    return "%s %s %s" % (getattr(dlg, "title", ""), status, dialog)


@pytest.fixture(autouse=True)
def _reset_status_text():
    fc.STATUS_TEXTS.clear()
    yield
    fc.STATUS_TEXTS.clear()


def test_dialog_layout_uses_linkboxes_not_comboboxes():
    dlg = mr.MaterialReplaceDialog()
    assert dlg.CreateLayout() is True

    created = [c for c in dlg.calls if c[0] == "AddCustomGui"]
    ids = [c[1] for c in created]
    assert dlg.LNK_SRC in ids and dlg.LNK_DST in ids
    assert all(c[2] == fc.CUSTOMGUI_LINKBOX for c in created)
    # 材质选择不再用下拉框（模式选择的下拉框不算）
    combos = [c[1] for c in dlg.calls if c[0] == "AddComboBox"]
    assert dlg.LNK_SRC not in combos and dlg.LNK_DST not in combos


def test_linkbox_accepts_dragged_material():
    """模拟拖放：直接把材质 SetLink 进链接框，应能读回并用于执行。"""
    new_mat = fc.make_material("M_New", params={
        fc.P_COLOR: (fc.DTYPE_COLOR, fc.Vector(0.0, 1.0, 0.0)),
    })
    old_mat = fc.make_material("M_Old")
    obj = fc.make_object("Cube", [fc.make_texture_tag(old_mat)])
    doc = fc.build_document([obj], [old_mat, new_mat])
    sys.modules["c4d"].documents.set_active(doc)

    dlg = mr.MaterialReplaceDialog()
    assert dlg.CreateLayout() is True
    dlg.InitValues()
    assert _box(dlg, dlg.LNK_SRC).SetLink(old_mat) is True
    assert _box(dlg, dlg.LNK_DST).SetLink(new_mat) is True
    dlg.Command(dlg.LNK_SRC, None)   # 真实拖放后 C4D 会回调 Command

    assert dlg._picked(dlg.LNK_SRC) is old_mat
    assert dlg._picked(dlg.LNK_DST) is new_mat

    # 链接框读回的就是模型里那两个材质，缩略图由链接框自己画
    assert _box(dlg, dlg.LNK_SRC).GetLink(None, None) is old_mat
    assert _box(dlg, dlg.LNK_DST).GetLink(None, None) is new_mat
    sys.modules["c4d"].documents.set_active(None)


def test_dialog_execute_flow_through_linkbox():
    """点「一键替换引用」→ 标签改指新材质，两个材质球参数都不变。"""
    new_mat = fc.make_material("M_New", params={
        fc.P_COLOR: (fc.DTYPE_COLOR, fc.Vector(0.0, 1.0, 0.0)),
    })
    old_mat = fc.make_material("M_Old", params={
        fc.P_COLOR: (fc.DTYPE_COLOR, fc.Vector(1.0, 1.0, 1.0)),
    })
    tag = fc.make_texture_tag(old_mat)
    obj = fc.make_object("Cube", [tag])
    doc = fc.build_document([obj], [old_mat, new_mat])
    sys.modules["c4d"].documents.set_active(doc)

    dlg = mr.MaterialReplaceDialog()
    assert dlg.CreateLayout() is True
    dlg.InitValues()
    _box(dlg, dlg.LNK_SRC).SetLink(old_mat)
    _box(dlg, dlg.LNK_DST).SetLink(new_mat)
    dlg.Command(dlg.BTN_RUN, None)

    assert tag[fc.TEXTURETAG_MATERIAL] is new_mat
    assert fc.get_param(old_mat, fc.P_COLOR) == fc.Vector(1.0, 1.0, 1.0)
    assert "替换 1 个标签" in _feedback(dlg)
    sys.modules["c4d"].documents.set_active(None)


def test_pick_button_takes_active_material_from_material_manager():
    mat = fc.make_material("M_Selected")
    doc = fc.build_document([], [mat])
    doc.set_active_materials([mat])
    sys.modules["c4d"].documents.set_active(doc)

    dlg = mr.MaterialReplaceDialog()
    dlg.CreateLayout()
    dlg.InitValues()
    dlg.Command(dlg.BTN_PICK_SRC, None)

    assert dlg._picked(dlg.LNK_SRC) is mat
    sys.modules["c4d"].documents.set_active(None)


def test_pick_button_warns_when_nothing_selected():
    doc = fc.build_document([], [])
    sys.modules["c4d"].documents.set_active(doc)

    dlg = mr.MaterialReplaceDialog()
    dlg.CreateLayout()
    dlg.InitValues()
    dlg.Command(dlg.BTN_PICK_DST, None)

    assert dlg._picked(dlg.LNK_DST) is None
    assert "没有选中的材质球" in _feedback(dlg)
    sys.modules["c4d"].documents.set_active(None)


def test_swap_and_clear_picks():
    a = fc.make_material("A")
    b = fc.make_material("B")
    doc = fc.build_document([], [a, b])
    sys.modules["c4d"].documents.set_active(doc)

    dlg = mr.MaterialReplaceDialog()
    dlg.CreateLayout()
    dlg.InitValues()
    _box(dlg, dlg.LNK_SRC).SetLink(a)
    _box(dlg, dlg.LNK_DST).SetLink(b)

    dlg.Command(dlg.BTN_SWAP, None)
    assert dlg._picked(dlg.LNK_SRC) is b
    assert dlg._picked(dlg.LNK_DST) is a

    dlg.Command(dlg.BTN_CLEAR, None)
    assert dlg._picked(dlg.LNK_SRC) is None
    assert dlg._picked(dlg.LNK_DST) is None
    sys.modules["c4d"].documents.set_active(None)


def test_dropped_object_is_rejected_with_clear_message():
    """拖进来的不是材质球时不能静默当材质用。"""
    obj = fc.make_object("Cube")
    doc = fc.build_document([obj], [])
    sys.modules["c4d"].documents.set_active(doc)

    dlg = mr.MaterialReplaceDialog()
    dlg.CreateLayout()
    dlg.InitValues()
    _box(dlg, dlg.LNK_SRC).SetLink(obj)
    dlg.Command(dlg.LNK_SRC, None)

    assert dlg._picked(dlg.LNK_SRC) is None
    assert "不是材质球" in _feedback(dlg)
    sys.modules["c4d"].documents.set_active(None)


def test_execute_without_both_picks_warns_and_changes_nothing():
    old_mat = fc.make_material("M_Old")
    doc = fc.build_document([], [old_mat])
    sys.modules["c4d"].documents.set_active(doc)

    dlg = mr.MaterialReplaceDialog()
    dlg.CreateLayout()
    dlg.InitValues()
    _box(dlg, dlg.LNK_SRC).SetLink(old_mat)
    dlg.Command(dlg.BTN_RUN, None)

    assert "还缺少" in _feedback(dlg)
    assert doc.undo_log == []
    sys.modules["c4d"].documents.set_active(None)


def test_link_get_supports_legacy_no_arg_signature():
    """老版本 / 部分文档示例的 GetLink() 无参形式也要能读到。"""
    mat = fc.make_material("M_Legacy")

    class LegacyBox(object):
        def GetLink(self):
            return mat

    class Host(object):
        def FindCustomGui(self, gid, pluginid):
            return LegacyBox()

    assert mr._link_get(Host(), 1) is mat


def test_link_set_falls_back_to_two_arg_signature():
    mat = fc.make_material("M_Sig")

    class TwoArgBox(object):
        def __init__(self):
            self.link = None

        def SetLink(self, doc, obj):
            self.link = obj
            return True

        def GetLink(self, doc=None, instance=None):
            return self.link

    class Host(object):
        def __init__(self):
            self.box = TwoArgBox()

        def FindCustomGui(self, gid, pluginid):
            return self.box

    host = Host()
    assert mr._link_set(host, 1, mat) is True
    assert host.box.link is mat


# ---------------------------------------------------------------- 节点材质与重定向
def test_node_material_detected_by_graph_signature():
    mat = fc.make_node_material("橙色", 3)

    sig = mr._graph_signature(mat)

    assert len(sig) == 3


def test_node_material_uses_full_copy_to_transplant_graph():
    src = fc.make_node_material("橙色", 3)
    dst = fc.make_node_material("白色1", 2)
    doc = fc.build_document([], [src, dst])

    report = mr.copy_material_content(doc, dst, src)

    assert report.src_graph_nodes == 3
    assert report.method == "copyto"
    assert report.graph_nodes == 3
    assert len(mr._graph_signature(dst)) == 3
    # 名字仍然是目标材质的
    assert dst.GetName() == "白色1"


def test_full_copy_failure_says_node_material_cannot_be_overwritten():
    src = fc.make_node_material("橙色", 3)
    src.copyto_ok = False
    dst = fc.make_node_material("白色1", 2)
    obj = fc.make_object("Cube", [fc.make_texture_tag(dst)])
    doc = fc.build_document([obj], [src, dst])

    result = mr.replace_material(doc, dst, src)
    text = mr.format_report(result)

    assert result.report.method == "params"
    assert "节点材质" in text
    assert "重定向引用" in text


def test_dry_run_on_node_material_reports_without_copying():
    src = fc.make_node_material("橙色", 3)
    dst = fc.make_node_material("白色1", 2)
    doc = fc.build_document([], [src, dst])

    result = mr.replace_material(doc, dst, src, dry_run=True)

    assert result.report.method == "params"
    assert len(mr._graph_signature(dst)) == 2
    assert any("节点材质" in line for line in result.report.details)
    assert doc.undo_log == []


def test_redirect_moves_every_tag_including_nested_levels():
    old = fc.make_material("M_Old")
    new = fc.make_material("M_New")
    a = fc.make_object("A", [fc.make_texture_tag(old)])
    b = fc.make_object("B", [fc.make_texture_tag(old)])
    child = fc.make_object("C", [fc.make_texture_tag(old)])
    fc.link_siblings(a, [child])
    doc = fc.build_document([a, b], [old, new])

    report = mr.redirect_references(doc, old, new)

    assert report.tags_total == 3
    assert report.tags_changed == 3
    assert report.failed == 0
    assert report.remaining == 0
    assert mr.collect_material_usage(doc, old).tags == 0
    assert mr.collect_material_usage(doc, new).tags == 3


def test_redirect_dry_run_changes_nothing():
    old = fc.make_material("M_Old")
    new = fc.make_material("M_New")
    obj = fc.make_object("A", [fc.make_texture_tag(old)])
    doc = fc.build_document([obj], [old, new])

    report = mr.redirect_references(doc, old, new, dry_run=True)

    assert report.dry_run is True
    assert mr.collect_material_usage(doc, old).tags == 1
    assert mr.collect_material_usage(doc, new).tags == 0
    assert doc.undo_log == []
    assert "没有改动任何标签" in mr.format_redirect_report(report, old, new)


def test_redirect_deletes_old_material_only_when_unused():
    old = fc.make_material("M_Old")
    new = fc.make_material("M_New")
    obj = fc.make_object("A", [fc.make_texture_tag(old)])
    doc = fc.build_document([obj], [old, new])

    report = mr.redirect_references(doc, old, new, delete_old=True)

    assert report.deleted is True
    assert old not in doc.materials


def test_redirect_without_delete_keeps_material():
    old = fc.make_material("M_Old")
    new = fc.make_material("M_New")
    obj = fc.make_object("A", [fc.make_texture_tag(old)])
    doc = fc.build_document([obj], [old, new])

    report = mr.redirect_references(doc, old, new, delete_old=False)

    assert report.deleted is False
    assert old in doc.materials


def test_redirect_rejects_same_material():
    mat = fc.make_material("M")
    doc = fc.build_document([], [mat])

    with pytest.raises(ValueError):
        mr.redirect_references(doc, mat, mat)


def test_dialog_redirect_mode_runs_redirect():
    old = fc.make_material("M_Old")
    new = fc.make_material("M_New")
    obj = fc.make_object("Cube", [fc.make_texture_tag(old)])
    doc = fc.build_document([obj], [old, new])
    sys.modules["c4d"].documents.set_active(doc)

    dlg = mr.MaterialReplaceDialog()
    dlg.CreateLayout()
    dlg.InitValues()
    # 默认就是重定向（等同 Alt 拖拽），不需要用户再切模式
    assert dlg._mode() == dlg.MODE_REDIRECT
    _box(dlg, dlg.LNK_SRC).SetLink(old)
    _box(dlg, dlg.LNK_DST).SetLink(new)
    dlg.Command(dlg.BTN_RUN, None)

    assert "替换" in _feedback(dlg)
    assert mr.collect_material_usage(doc, new).tags == 1
    sys.modules["c4d"].documents.set_active(None)


def test_dialog_default_run_does_not_touch_material_content():
    """默认模式执行完，两个材质球的参数与节点图都不能被改动。"""
    old = fc.make_material("M_Old", params={
        fc.P_COLOR: (fc.DTYPE_COLOR, fc.Vector(0.1, 0.2, 0.3)),
    })
    new = fc.make_material("M_New", params={
        fc.P_COLOR: (fc.DTYPE_COLOR, fc.Vector(0.9, 0.8, 0.7)),
    })
    obj = fc.make_object("Cube", [fc.make_texture_tag(old)])
    doc = fc.build_document([obj], [old, new])
    sys.modules["c4d"].documents.set_active(doc)

    dlg = mr.MaterialReplaceDialog()
    dlg.CreateLayout()
    dlg.InitValues()
    _box(dlg, dlg.LNK_SRC).SetLink(old)
    _box(dlg, dlg.LNK_DST).SetLink(new)
    dlg.Command(dlg.BTN_RUN, None)

    assert fc.get_param(old, fc.P_COLOR) == fc.Vector(0.1, 0.2, 0.3)
    assert fc.get_param(new, fc.P_COLOR) == fc.Vector(0.9, 0.8, 0.7)
    sys.modules["c4d"].documents.set_active(None)


def test_redirect_keeps_tag_own_settings():
    """Alt 拖拽只换材质引用，标签的 UV 偏移/平铺/投影设置必须原样保留。"""
    old = fc.make_material("M_Old")
    new = fc.make_material("M_New")
    tag = fc.make_texture_tag(old)
    tag._params[fc.DID(9001)] = (fc.DTYPE_REAL, 0.25)      # 例如偏移 U
    tag._params[fc.DID(9002)] = (fc.DTYPE_REAL, 3.0)       # 例如平铺次数
    obj = fc.make_object("Cube", [tag])
    doc = fc.build_document([obj], [old, new])

    mr.redirect_references(doc, old, new)

    assert tag[fc.TEXTURETAG_MATERIAL] is new
    assert tag[fc.DID(9001)] == 0.25
    assert tag[fc.DID(9002)] == 3.0


def test_redirect_report_says_it_matches_alt_drag():
    old = fc.make_material("M_Old")
    new = fc.make_material("M_New")
    obj = fc.make_object("A", [fc.make_texture_tag(old)])
    doc = fc.build_document([obj], [old, new])

    text = mr.format_redirect_report(mr.redirect_references(doc, old, new), old, new)

    assert "只换引用" in text or "参数与贴图" in text


def test_dialog_redirects_node_material_without_touching_graph():
    """Redshift 节点材质：走重定向，节点图一个都不动。"""
    node_mat = fc.make_node_material("橙色", 3)
    other = fc.make_material("白色1")
    tag = fc.make_texture_tag(node_mat)
    obj = fc.make_object("Cube", [tag])
    doc = fc.build_document([obj], [node_mat, other])
    sys.modules["c4d"].documents.set_active(doc)

    dlg = mr.MaterialReplaceDialog()
    dlg.CreateLayout()
    dlg.InitValues()
    _box(dlg, dlg.LNK_SRC).SetLink(node_mat)
    _box(dlg, dlg.LNK_DST).SetLink(other)
    dlg.Command(dlg.BTN_RUN, None)

    assert tag[fc.TEXTURETAG_MATERIAL] is other
    assert len(mr._graph_signature(node_mat)) == 3      # 源材质节点图原封不动
    assert "替换" in _feedback(dlg)
    sys.modules["c4d"].documents.set_active(None)


# ---------------------------------------------------------------- 精简界面与大预览
def _fresh_dialog(materials=None, objects=None):
    doc = fc.build_document(objects or [], materials or [])
    sys.modules["c4d"].documents.set_active(doc)
    dlg = mr.MaterialReplaceDialog()
    assert dlg.CreateLayout() is True
    dlg.InitValues()
    return dlg, doc


def test_layout_has_no_extra_descriptions_or_options():
    """窗口只有三行可见内容：两行「标签+链接框+拾取」、一排三个按钮。"""
    dlg, _ = _fresh_dialog()

    kinds = [c[0] for c in dlg.calls]
    assert "AddCheckbox" not in kinds        # 没有「只诊断」「删除旧材质」
    assert "AddComboBox" not in kinds        # 没有替换方式下拉

    # 空名字的静态文本是可伸缩占位，不算文字标签
    texts = [c[2] for c in dlg.calls if c[0] == "AddStaticText" and c[2]]
    assert texts == ["源", "目标"]            # 只剩两个极短标签

    buttons = [c[2] for c in dlg.calls if c[0] == "AddButton"]
    assert buttons == ["拾取", "拾取", "替换", "交换", "清空"]


def test_layout_is_freely_resizable():
    """主容器双向 SCALEFIT + 一个纵向占位，窗口才能自由拉伸。

    C4D 的布局引擎在没有任何纵向可伸缩元素时，会把窗口锁死成布局最小尺寸，
    拖边缘会立刻回弹 —— 这就是 v9 窗口拉不动的原因。
    """
    dlg, _ = _fresh_dialog()

    groups = {c[1]: c for c in dlg.calls if c[0] == "GroupBegin"}
    flags = groups[dlg.GRP_MAIN][4]
    assert flags & fc.BFH_SCALEFIT
    assert flags & fc.BFV_SCALEFIT

    spacers = [c for c in dlg.calls if c[0] == "AddStaticText" and c[2] == ""]
    assert spacers, "需要一个纵向可伸缩的空白占位，否则窗口锁死"
    assert spacers[0][1] == dlg.SPACER


def test_layout_has_no_result_box():
    """结果框取消：执行反馈走标题栏 + C4D 状态栏。"""
    dlg, _ = _fresh_dialog()

    kinds = [c[0] for c in dlg.calls]
    assert "AddMultiLineEditText" not in kinds
    assert not hasattr(dlg, "TXT_RESULT")


def test_layout_has_no_self_drawn_preview_area():
    """不再自绘预览：没有 UserArea，缩略图交给链接框的官方图标。"""
    dlg, _ = _fresh_dialog()

    kinds = [c[0] for c in dlg.calls]
    assert "AddUserArea" not in kinds
    assert "AttachUserArea" not in kinds
    assert not hasattr(mr, "MaterialPreview")
    assert not hasattr(dlg, "_pre_src")


def test_linkbox_keeps_its_official_icon():
    """必须让链接框自己画官方小图标（不设置 LINKBOX_HIDE_ICON）。"""
    dlg, _ = _fresh_dialog()

    for gid in (dlg.LNK_SRC, dlg.LNK_DST):
        data = dlg.customdata.get(gid)
        assert data is not None
        assert data.GetBool(fc.LINKBOX_HIDE_ICON) is False


def test_linkbox_uses_compact_height():
    """链接框高度按 LINK_HEIGHT 给，够放图标又不浪费竖向空间。"""
    dlg, _ = _fresh_dialog()

    heights = {c[1]: c[4] for c in dlg.calls if c[0] == "AddCustomGui"}
    assert heights[dlg.LNK_SRC] == mr.LINK_HEIGHT
    assert heights[dlg.LNK_DST] == mr.LINK_HEIGHT
    assert 16 <= mr.LINK_HEIGHT <= 24


def test_pick_button_sits_right_after_each_linkbox():
    """每行三格：标签 → 链接框 → 拾取；拾取紧跟在链接框吸管后面。"""
    dlg, _ = _fresh_dialog()

    groups = {c[1]: (c[2], c[3]) for c in dlg.calls if c[0] == "GroupBegin"}
    assert groups[dlg.GRP_ROW_SRC] == (3, 0)
    assert groups[dlg.GRP_ROW_DST] == (3, 0)

    seq = [(c[0], c[1]) for c in dlg.calls
           if c[0] in ("GroupBegin", "AddStaticText", "AddCustomGui", "AddButton")]
    for grp, txt, lnk, btn in (
            (dlg.GRP_ROW_SRC, dlg.TXT_SRC, dlg.LNK_SRC, dlg.BTN_PICK_SRC),
            (dlg.GRP_ROW_DST, dlg.TXT_DST, dlg.LNK_DST, dlg.BTN_PICK_DST)):
        start = seq.index(("GroupBegin", grp))
        assert seq[start + 1] == ("AddStaticText", txt)
        assert seq[start + 2] == ("AddCustomGui", lnk)
        assert seq[start + 3] == ("AddButton", btn)


def test_bottom_buttons_share_one_row_in_order():
    """替换、交换、清空 三个按钮同排一行（没有关闭按钮）。"""
    dlg, _ = _fresh_dialog()

    groups = {c[1]: (c[2], c[3]) for c in dlg.calls if c[0] == "GroupBegin"}
    assert groups[dlg.GRP_BTN] == (3, 0)

    seq = [(c[0], c[1] if len(c) > 1 else None) for c in dlg.calls
           if c[0] in ("GroupBegin", "AddButton", "GroupEnd")]
    start = seq.index(("GroupBegin", dlg.GRP_BTN))
    assert seq[start + 1:start + 4] == [
        ("AddButton", dlg.BTN_RUN), ("AddButton", dlg.BTN_SWAP),
        ("AddButton", dlg.BTN_CLEAR)]
    assert seq[start + 4] == ("GroupEnd", None)


def test_no_close_button():
    """关闭按钮取消，关窗靠标题栏的 ×。"""
    dlg, _ = _fresh_dialog()

    buttons = [c[2] for c in dlg.calls if c[0] == "AddButton"]
    assert "关闭" not in buttons
    assert not hasattr(dlg, "BTN_CLOSE")


def test_dialog_window_is_compact():
    """窗口从 430×330 收到 224×108，只剩三行。"""
    assert mr.DIALOG_WIDTH <= 240
    assert mr.DIALOG_HEIGHT <= 120
    assert mr.DIALOG_WIDTH >= 190          # 太窄会把链接框压到看不见名字


def test_successful_run_does_not_write_log_file(monkeypatch):
    """顺利时不往硬盘写东西（只在失败时落日志）。"""
    calls = []
    monkeypatch.setattr(mr, "write_diagnostics_log", lambda text: calls.append(text) or "")

    old = fc.make_material("M_Old")
    new = fc.make_material("M_New")
    obj = fc.make_object("Cube", [fc.make_texture_tag(old)])
    dlg, _ = _fresh_dialog([old, new], [obj])
    _box(dlg, dlg.LNK_SRC).SetLink(old)
    _box(dlg, dlg.LNK_DST).SetLink(new)

    dlg.Command(dlg.BTN_RUN, None)

    assert calls == []
    assert "替换 1 个标签" in _feedback(dlg)


def test_failed_switch_writes_log_file(monkeypatch):
    calls = []
    monkeypatch.setattr(mr, "write_diagnostics_log", lambda text: calls.append(text) or "C:/x.log")

    old = fc.make_material("M_Old")
    new = fc.make_material("M_New")
    tag = fc.make_texture_tag(old)

    class BadTag(fc.BaseTag):
        def SetParameter(self, did, value, flags=0):
            return False

        def __setitem__(self, key, value):
            raise RuntimeError("no")

    bad = BadTag("纹理标签", fc.Ttexture, {})
    bad._params[fc.DID(fc.TEXTURETAG_MATERIAL)] = (fc.DTYPE_BASELISTLINK, old)
    obj = fc.make_object("Cube", [bad])
    dlg, _ = _fresh_dialog([old, new], [obj])
    _box(dlg, dlg.LNK_SRC).SetLink(old)
    _box(dlg, dlg.LNK_DST).SetLink(new)

    dlg.Command(dlg.BTN_RUN, None)

    assert calls, "有失败时必须落日志"
    assert "日志：" in _feedback(dlg)
