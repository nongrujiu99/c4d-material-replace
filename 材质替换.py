# -*- coding: utf-8 -*-
"""C4D 2023 材质替换（覆盖内容）

需求：场景里多个对象共用同一个材质球，想把材质管理器里指定的材质球
一键变成另一个材质球的内容 —— 但保留材质球本身（引用链不断）。

用法（二选一）：
1. 插件模式：把本文件改名为 MaterialReplace.pyp，放到
   C:\\Program Files\\Maxon Cinema 4D 2023\\plugins\\MaterialReplace\\
   重启 C4D，在「扩展」菜单里找到它。
2. 脚本模式：把本文件改名为 材质替换.py，放到
   %APPDATA%\\Maxon\\Maxon Cinema 4D 2023_xxxx\\library\\scripts\\
   在 C4D「脚本」菜单里运行。

安全边界：只在内存里改「你选中的那一个材质球」的参数，不碰渲染设置、
不碰渲染器偏好、不保存文件、不改工程里的其它对象。

作者：WorkBuddy    目标版本：Cinema 4D 2023（Python 3）
"""

import io
import os

import c4d

PLUGIN_ID = 1056001
PLUGIN_NAME = "材质替换（覆盖内容）"

_DIALOG = None
_REGISTERED = False


# ============================================================================
# 数据结构
# ============================================================================
class UsageInfo(object):
    """材质被引用的情况。"""

    def __init__(self):
        self.objects = 0
        self.tags = 0
        self.names = []


class CopyReport(object):
    """一次内容覆盖的结果。"""

    def __init__(self):
        self.params_seen = 0
        self.params_copied = 0
        self.params_skipped = []
        self.params_failed = []
        self.shaders_copied = 0
        self.type_mismatch = False
        self.dry_run = False
        self.verified_ok = 0
        self.verified_total = 0
        self.details = []
        self.src_name = ""
        self.dst_name = ""
        self.src_type = None
        self.dst_type = None
        # 节点材质（Redshift / Node Material）相关信息
        self.method = "params"        # params = 逐参数拷贝，copyto = 整材质完整拷贝
        self.src_graph_nodes = 0      # 源材质节点图里的节点数
        self.graph_nodes = 0          # 拷贝后目标材质的节点数
        self.copyto_error = ""
        self.graph_mismatch = False


class RedirectReport(object):
    """一次引用重定向的结果。"""

    def __init__(self):
        self.tags_total = 0
        self.tags_changed = 0
        self.objects = 0
        self.failed = 0
        self.remaining = 0
        self.deleted = False
        self.delete_note = ""
        self.dry_run = False
        self.details = []


class ReplaceResult(object):
    def __init__(self, usage, report):
        self.usage = usage
        self.report = report


# ============================================================================
# 工具函数
# ============================================================================
def _const(name, default=0):
    return getattr(c4d, name, default)


def _same(a, b):
    if a is None or b is None:
        return False
    if a is b:
        return True
    try:
        return bool(a == b)
    except Exception:
        return False


def is_plugin_mode(path):
    """按文件后缀区分插件模式（.pyp）与脚本模式（.py）。"""
    try:
        return str(path).lower().endswith(".pyp")
    except Exception:
        return False


def get_materials(doc):
    if doc is None:
        return []
    try:
        mats = doc.GetMaterials()
    except Exception:
        return []
    return list(mats) if mats else []


def _mat_name(mat):
    try:
        name = mat.GetName()
    except Exception:
        name = ""
    return name or "(未命名)"


def _material_label(mat, index):
    try:
        name = mat.GetName()
    except Exception:
        name = ""
    if not name:
        name = "(未命名材质)"
    return "%d · %s" % (index + 1, name)


def list_materials(doc):
    """给下拉框用的 (控件ID, 显示文本) 列表，控件ID 从 1 开始。"""
    items = []
    for index, mat in enumerate(get_materials(doc)):
        items.append((index + 1, _material_label(mat, index)))
    return items


def _skip_dtypes():
    names = ("DTYPE_GROUP", "DTYPE_BUTTON", "DTYPE_SEPARATOR",
             "DTYPE_STATICTEXT", "DTYPE_SUBCONTAINER", "DTYPE_DYNAMIC")
    values = set()
    for name in names:
        value = getattr(c4d, name, None)
        if value is not None:
            values.add(value)
    return values


def _cloneable_types():
    """可以安全克隆并挂到目标材质下的子对象类型（着色器、渐变等）。"""
    types = []
    for name in ("BaseShader", "Gradient", "BaseShaderLayer", "BaseShaderNode"):
        cls = getattr(c4d, name, None)
        if isinstance(cls, type):
            types.append(cls)
    return tuple(types)


def _iter_description(mat):
    """读取材质描述，返回 [(参数ID, 显示名, 数据类型)]。

    官方语义：for bc, paramid, groupid in mat.GetDescription(flags)
    —— 参数 ID 是 c4d.DescID，不是 int。
    """
    items = []
    if mat is None:
        return items
    try:
        desc = mat.GetDescription(_const("DESCFLAGS_DESC_0"))
    except Exception:
        return items
    if desc is None:
        return items
    try:
        raw = list(desc)
    except Exception:
        return items

    name_key = getattr(c4d, "DESC_NAME", None)
    type_key = getattr(c4d, "DESC_TYPE", None)

    for item in raw:
        if not isinstance(item, (tuple, list)):
            continue
        if len(item) >= 3:
            entry_bc, pid = item[0], item[1]
        elif len(item) == 2:
            pid, entry_bc = item[0], item[1]
        else:
            continue
        if pid is None:
            continue

        name = ""
        dtype = None
        if entry_bc is not None:
            for key_name in ("DESC_NAME", "DESC_SHORT_NAME", "DESC_IDENT"):
                key = getattr(c4d, key_name, None)
                if key is None:
                    continue
                try:
                    name = entry_bc[key] or ""
                except Exception:
                    name = ""
                if name:
                    break
            if not name:
                try:
                    name = entry_bc.GetName() or ""
                except Exception:
                    name = ""
            if type_key is not None:
                try:
                    dtype = entry_bc[type_key]
                except Exception:
                    dtype = None
            if dtype is None:
                try:
                    dtype = entry_bc.GetType()
                except Exception:
                    dtype = None
        if not name:
            name = "参数%s" % _short_id(pid)
        items.append((pid, name, dtype))
    return items


def _is_name_param(pid):
    """判断参数是不是「名称」——它永远拷得成功，会把「什么都没拷到」的统计掩盖掉。"""
    base = getattr(c4d, "ID_BASELIST_NAME", None)
    if base is None or pid is None:
        return False
    if isinstance(pid, int):
        return pid == base
    try:
        if pid.GetDepth() != 1:
            return False
        level = pid[0]
        return getattr(level, "id", level) == base
    except Exception:
        return False


def _get_param(mat, pid):
    try:
        value = mat.GetParameter(pid, _const("DESCFLAGS_GET_0"))
        if value is not None:
            return value
    except Exception:
        pass
    try:
        return mat[pid]
    except Exception:
        return None


def _set_param(mat, pid, value):
    """写参数并回读确认。

    SetParameter 在 C4D 里可能返回 True 但值没落下（例如被继承/只读拦截），
    `op[id] = value` 更是静默失败，所以统一靠回读判定成败。
    """
    ok = False
    try:
        ok = bool(mat.SetParameter(pid, value, _const("DESCFLAGS_SET_0")))
    except Exception:
        ok = False
    if not ok:
        try:
            mat[pid] = value
        except Exception:
            return False
    actual = _get_param(mat, pid)
    if actual is None:
        return ok
    return _values_equal(value, actual)


def _clone_child(child):
    try:
        return child.GetClone()
    except Exception:
        return None


def _short_id(pid):
    """把 DescID 压成短文本，便于日志阅读。"""
    try:
        if isinstance(pid, int):
            return str(pid)
        text = str(pid)
        return text.replace(" ", "")[:24]
    except Exception:
        return "?"


def _describe_value(value):
    """给日志用的值描述：类型 + 截断的字符串。"""
    try:
        if value is None:
            return "None"
        cls = type(value).__name__
        if isinstance(value, bool):
            return "bool(%s)" % value
        if isinstance(value, (int, float)):
            return "%s(%s)" % (cls, value)
        try:
            text = str(value)
        except Exception:
            text = ""
        text = text.replace("\n", " ")[:36]
        return "%s(%s)" % (cls, text)
    except Exception:
        return "?"


def _values_equal(a, b):
    try:
        if a is b:
            return True
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return abs(float(a) - float(b)) < 1e-6
        return bool(a == b)
    except Exception:
        return False


def _set_param_forced(mat, pid, value):
    """普通写入失败时的第二次尝试：FORCESET 可越过只读标记。"""
    flags = getattr(c4d, "DESCFLAGS_SET_FORCESET", 0)
    if not flags:
        return False
    try:
        return bool(mat.SetParameter(pid, value, flags))
    except Exception:
        return False


def _insert_child(mat, child):
    try:
        if mat.InsertShader(child):
            return True
    except Exception:
        pass
    try:
        if child.InsertUnder(mat):
            return True
    except Exception:
        pass
    return False


# ============================================================================
# 核心逻辑
# ============================================================================
def collect_material_usage(doc, material):
    """遍历整个场景（含所有层级），统计引用该材质的对象与标签数量。"""
    usage = UsageInfo()
    if doc is None or material is None:
        return usage

    seen = set()
    stack = []
    try:
        root = doc.GetFirstObject()
    except Exception:
        root = None
    if root is not None:
        stack.append(root)

    texture_type = getattr(c4d, "Ttexture", None)
    material_id = getattr(c4d, "TEXTURETAG_MATERIAL", None)

    while stack:
        node = stack.pop()
        while node is not None:
            try:
                tags = node.GetTags() or []
            except Exception:
                tags = []
            for tag in tags:
                try:
                    if texture_type is not None and tag.GetType() != texture_type:
                        continue
                    if material_id is None:
                        continue
                    if not _same(tag[material_id], material):
                        continue
                except Exception:
                    continue
                usage.tags += 1
                key = id(node)
                if key not in seen:
                    seen.add(key)
                    usage.objects += 1
                    try:
                        usage.names.append(node.GetName())
                    except Exception:
                        usage.names.append("")

            try:
                child = node.GetDown()
            except Exception:
                child = None
            if child is not None:
                stack.append(child)
            try:
                node = node.GetNext()
            except Exception:
                node = None

    return usage


def _is_node_value(value):
    """是不是节点图里的节点（GvNode）。

    只认 GvNode：普通材质里挂的颜色着色器（BaseShader）、渐变（Gradient）
    也是 BaseList2D，但那些不是节点材质，不能混进来。
    """
    if value is None:
        return False
    try:
        gv = c4d.modules.graphview
        for cls_name in ("GvNode", "GvNodeMaster"):
            cls = getattr(gv, cls_name, None)
            if cls is not None and isinstance(value, cls):
                return True
    except Exception:
        pass
    # 模块拿不到时按类名兜底（真实 API 里这类对象的类名就是 GvNode）
    try:
        return type(value).__name__ == "GvNode"
    except Exception:
        return False


def _graph_signature(mat):
    """节点材质的「节点图指纹」：description 里暴露出来的 GvNode 列表。

    Redshift 节点材质 / 标准 Node Material 的外观在节点图里，不在普通参数里。
    这里按 (参数id, 节点类型) 收集，用于判断节点图是否真的拷过来了。
    """
    sig = []
    try:
        items = _iter_description(mat)
    except Exception:
        return sig
    for pid, pname, dtype in items:
        try:
            value = _get_param(mat, pid)
        except Exception:
            continue
        if _is_node_value(value):
            try:
                sig.append((_short_id(pid), value.GetType()))
            except Exception:
                continue
    sig.sort()
    return sig


def collect_material_tags(doc, material):
    """返回所有引用该材质的 (对象, 纹理标签) 对，供重定向使用。"""
    pairs = []
    if doc is None or material is None:
        return pairs

    texture_type = getattr(c4d, "Ttexture", None)
    material_id = getattr(c4d, "TEXTURETAG_MATERIAL", None)
    if material_id is None:
        return pairs

    stack = []
    try:
        root = doc.GetFirstObject()
    except Exception:
        root = None
    if root is not None:
        stack.append(root)

    while stack:
        node = stack.pop()
        while node is not None:
            try:
                tags = node.GetTags() or []
            except Exception:
                tags = []
            for tag in tags:
                try:
                    if texture_type is not None and tag.GetType() != texture_type:
                        continue
                    if _same(tag[material_id], material):
                        pairs.append((node, tag))
                except Exception:
                    continue
            try:
                child = node.GetDown()
            except Exception:
                child = None
            if child is not None:
                stack.append(child)
            try:
                node = node.GetNext()
            except Exception:
                node = None
    return pairs


def _full_copy(doc, dst_mat, src_mat, report, expected_sig):
    """整材质 CopyTo：把节点图在内的全部数据搬到目标材质上。

    逐参数拷贝对节点材质无效（外观不在 Description 里），CopyTo 是唯一可能
    把 Redshift 节点图一起搬过去的通用手段。
    """
    flags = _const("COPYFLAGS_NONE", 0)
    ok = False
    try:
        ok = bool(src_mat.CopyTo(dst_mat, flags, None))
    except TypeError:
        try:
            ok = bool(src_mat.CopyTo(dst_mat, flags))
        except Exception as err:
            report.copyto_error = str(err)
            ok = False
    except Exception as err:
        report.copyto_error = str(err)
        ok = False

    head = "整材质拷贝 CopyTo：%s" % ("返回成功" if ok else "返回失败")
    if report.copyto_error:
        head += "（%s）" % report.copyto_error
    report.details.append(head)

    if not ok:
        return False

    try:
        dst_mat.Update(True)
    except Exception:
        pass

    actual = _graph_signature(dst_mat)
    report.graph_nodes = len(actual)
    if actual == expected_sig:
        report.method = "copyto"
        report.details.append("节点图核对：源 %d 个节点 / 目标 %d 个节点，一致"
                              % (len(expected_sig), len(actual)))
        return True

    report.graph_mismatch = True
    report.details.append("节点图核对不一致：源 %d 个节点 / 目标 %d 个节点"
                          % (len(expected_sig), len(actual)))
    return False


def copy_material_content(doc, dst_mat, src_mat, keep_name=True, dry_run=False,
                          full_copy=True):
    """把 src_mat 的内容覆盖到 dst_mat（dst 对象本身保留）。

    dry_run=True 只读不写，用于诊断。
    """
    if dst_mat is None or src_mat is None:
        raise ValueError("必须同时指定源材质和目标材质")
    if _same(dst_mat, src_mat):
        raise ValueError("源材质与目标材质是同一个材质球，无需替换")

    report = CopyReport()
    report.dry_run = dry_run
    try:
        report.type_mismatch = src_mat.GetType() != dst_mat.GetType()
    except Exception:
        report.type_mismatch = False
    for attr, mat in (("src_name", src_mat), ("dst_name", dst_mat)):
        try:
            setattr(report, attr, mat.GetName())
        except Exception:
            pass
    for attr, mat in (("src_type", src_mat), ("dst_type", dst_mat)):
        try:
            setattr(report, attr, mat.GetType())
        except Exception:
            pass

    old_name = ""
    try:
        old_name = dst_mat.GetName()
    except Exception:
        pass

    desc_items = _iter_description(src_mat)
    report.params_seen = len(desc_items)
    graph_sig = _graph_signature(src_mat)
    report.src_graph_nodes = len(graph_sig)
    skip_types = _skip_dtypes()
    clone_types = _cloneable_types()
    undo_started = False
    verify_list = []

    try:
        if doc is not None and not dry_run:
            try:
                doc.StartUndo()
                undo_started = True
                doc.AddUndo(c4d.UNDOTYPE_CHANGE, dst_mat)
            except Exception:
                undo_started = False

        # 节点材质：外观在节点图里，逐参数拷贝改不动它。
        # 先试整材质 CopyTo（连节点图一起搬），核对节点图一致就收工。
        if graph_sig:
            if dry_run:
                report.details.append(
                    "检测到节点材质：%d 个节点。这类材质必须整材质拷贝，逐参数拷贝改不动外观。"
                    % len(graph_sig))
            elif (full_copy and not report.type_mismatch
                  and _full_copy(doc, dst_mat, src_mat, report, graph_sig)):
                if keep_name and old_name:
                    try:
                        dst_mat.SetName(old_name)
                    except Exception:
                        pass
                try:
                    dst_mat.Update(True)
                except Exception:
                    pass
                return report

        for index, (pid, pname, dtype) in enumerate(desc_items):
            head = "[%02d] %s | id=%s | dtype=%s" % (
                index, pname, _short_id(pid), dtype)

            if _is_name_param(pid):
                report.details.append("%s | 名称参数，跳过（保留目标材质名）" % head)
                continue

            if dtype is not None and dtype in skip_types:
                report.details.append("%s | 布局项，跳过" % head)
                continue

            value = _get_param(src_mat, pid)
            if value is None:
                report.details.append("%s | 值为空，跳过" % head)
                continue

            vdesc = _describe_value(value)

            # 着色器 / 渐变：克隆后挂到目标材质，源材质自己的子对象绝不能被移走
            if clone_types and isinstance(value, clone_types):
                if dry_run:
                    report.shaders_copied += 1
                    report.details.append("%s | %s | 可克隆" % (head, vdesc))
                    continue
                clone = _clone_child(value)
                if clone is None or not _insert_child(dst_mat, clone):
                    report.params_failed.append(pname)
                    report.details.append("%s | %s | 克隆/挂载失败" % (head, vdesc))
                    continue
                if not _set_param(dst_mat, pid, clone):
                    try:
                        clone.Remove()
                    except Exception:
                        pass
                    report.params_failed.append(pname)
                    report.details.append("%s | %s | 已克隆但赋值失败" % (head, vdesc))
                    continue
                report.shaders_copied += 1
                report.details.append("%s | %s | 已克隆" % (head, vdesc))
                if undo_started:
                    try:
                        doc.AddUndo(c4d.UNDOTYPE_NEW, clone)
                    except Exception:
                        pass
                continue

            # 其它对象链接（对象/材质引用）不复制，避免意外复制整棵树
            if isinstance(value, c4d.BaseList2D):
                report.params_skipped.append(pname)
                report.details.append("%s | %s | 对象链接，跳过" % (head, vdesc))
                continue

            if dry_run:
                report.params_copied += 1
                report.details.append("%s | %s | 可写入" % (head, vdesc))
                continue

            ok = _set_param(dst_mat, pid, value)
            if ok:
                report.details.append("%s | %s | 已写入" % (head, vdesc))
            else:
                if _set_param_forced(dst_mat, pid, value):
                    ok = True
                    report.details.append("%s | %s | 强制写入成功" % (head, vdesc))
                else:
                    report.details.append("%s | %s | 写入失败" % (head, vdesc))

            if ok:
                report.params_copied += 1
                if len(verify_list) < 5:
                    verify_list.append((pid, pname, value))
            else:
                report.params_skipped.append(pname)
    finally:
        if undo_started:
            try:
                doc.EndUndo()
            except Exception:
                pass

    if not dry_run:
        if keep_name and old_name:
            try:
                dst_mat.SetName(old_name)
            except Exception:
                pass
        try:
            dst_mat.Update(True)
        except Exception:
            pass

        # 回读校验：确认值真的落下去了（防止 SetParameter 返回 True 但没生效）
        for pid, pname, expected in verify_list:
            actual = _get_param(dst_mat, pid)
            report.verified_total += 1
            if _values_equal(expected, actual):
                report.verified_ok += 1
            else:
                report.details.append("回读校验不一致：%s（期望 %s，实际 %s）"
                                      % (pname, _describe_value(expected),
                                         _describe_value(actual)))

    return report


def replace_material(doc, old_mat, new_mat, dry_run=False):
    """对外入口：统计影响范围 + 执行内容覆盖。"""
    if doc is None:
        raise ValueError("没有可用的文档")
    if old_mat is None or new_mat is None:
        raise ValueError("必须同时指定源材质和目标材质")
    if _same(old_mat, new_mat):
        raise ValueError("源材质与目标材质是同一个材质球，无需替换")

    usage = collect_material_usage(doc, old_mat)
    report = copy_material_content(doc, old_mat, new_mat, dry_run=dry_run)
    return ReplaceResult(usage, report)


def redirect_references(doc, old_mat, new_mat, delete_old=False, dry_run=False):
    """把所有引用 old_mat 的材质标签改指 new_mat（不动两个材质球本身）。

    这是唯一对所有材质类型都成立的做法：无论标准材质还是 Redshift 节点材质，
    换引用一定生效，因为它根本不需要读材质内容。
    """
    if doc is None:
        raise ValueError("没有可用的文档")
    if old_mat is None or new_mat is None:
        raise ValueError("必须同时指定源材质和目标材质")
    if _same(old_mat, new_mat):
        raise ValueError("源材质与目标材质是同一个材质球，无需替换")

    report = RedirectReport()
    report.dry_run = dry_run
    material_id = getattr(c4d, "TEXTURETAG_MATERIAL", None)
    pairs = collect_material_tags(doc, old_mat)
    report.tags_total = len(pairs)
    report.objects = len(set(id(obj) for obj, tag in pairs))

    undo_started = False
    try:
        if not dry_run:
            try:
                doc.StartUndo()
                undo_started = True
            except Exception:
                undo_started = False

        for obj, tag in pairs:
            name = ""
            try:
                name = obj.GetName()
            except Exception:
                name = ""
            if dry_run:
                report.tags_changed += 1
                report.details.append("预览：%s 的材质标签 → %s" % (name, _mat_name(new_mat)))
                continue

            if undo_started:
                try:
                    doc.AddUndo(c4d.UNDOTYPE_CHANGE, tag)
                except Exception:
                    pass

            ok = False
            if material_id is not None:
                try:
                    ok = bool(tag.SetParameter(material_id, new_mat,
                                               _const("DESCFLAGS_SET_0", 0)))
                except Exception:
                    ok = False
                if not ok:
                    try:
                        tag[material_id] = new_mat
                        ok = _same(tag[material_id], new_mat)
                    except Exception:
                        ok = False

            if ok:
                report.tags_changed += 1
                report.details.append("已切换：%s 的材质标签 → %s" % (name, _mat_name(new_mat)))
            else:
                report.failed += 1
                report.details.append("切换失败：%s 的材质标签" % name)
    finally:
        if undo_started:
            try:
                doc.EndUndo()
            except Exception:
                pass

    if not dry_run:
        report.remaining = collect_material_usage(doc, old_mat).tags
        if delete_old:
            if report.remaining:
                report.delete_note = ("旧材质还有 %d 个标签在引用，未删除" % report.remaining)
            elif report.failed:
                report.delete_note = ("有 %d 个标签切换失败，为安全起见未删除旧材质" % report.failed)
            else:
                try:
                    doc.StartUndo()
                    try:
                        doc.AddUndo(c4d.UNDOTYPE_DELETEOBJ, old_mat)
                    except Exception:
                        pass
                    ok = bool(old_mat.Remove())
                    doc.EndUndo()
                    report.deleted = ok
                    if not ok:
                        report.delete_note = "删除旧材质失败"
                except Exception as err:
                    report.delete_note = "删除旧材质失败：%s" % err

    return report


def format_redirect_report(report, old_mat, new_mat):
    """重定向结果给人看的文本。"""
    lines = []
    if report.dry_run:
        lines.append("【只诊断模式：没有改动任何标签】")
    lines.append("引用重定向：%d / %d 个材质标签已改指「%s」"
                 % (report.tags_changed, report.tags_total, _mat_name(new_mat)))
    lines.append("影响对象：%d 个" % report.objects)
    lines.append("只换引用：两个材质球的参数、贴图、节点全部原样未动")
    if not report.dry_run:
        if report.remaining == 0:
            lines.append("旧材质「%s」剩余引用：0（已经没有任何对象在用它）"
                         % _mat_name(old_mat))
        else:
            lines.append("旧材质「%s」剩余引用：%d 个标签（没有全部切换）"
                         % (_mat_name(old_mat), report.remaining))
    if report.failed:
        lines.append("切换失败：%d 个标签，请手动检查" % report.failed)
    if report.deleted:
        lines.append("已从材质管理器删除旧材质")
    elif report.delete_note:
        lines.append(report.delete_note)
    return "\n".join(lines)


def format_redirect_brief(report, old_mat, new_mat):
    """单行摘要（界面已经没有结果框，只能显示在标题栏和状态栏）。"""
    if report.failed:
        return "替换 %d/%d，失败 %d" % (report.tags_changed, report.tags_total,
                                        report.failed)
    if report.tags_total and report.tags_changed < report.tags_total:
        return "替换 %d/%d，部分未换" % (report.tags_changed, report.tags_total)
    return "替换 %d 个标签 → %s" % (report.tags_changed, _mat_name(new_mat))


def format_redirect_details(report, old_mat, new_mat):
    lines = [
        "C4D 材质替换诊断日志（引用重定向）",
        "模式：%s" % ("只诊断，未改动" if report.dry_run else "已执行重定向"),
        "旧材质：%s" % _mat_name(old_mat),
        "新材质：%s" % _mat_name(new_mat),
        "标签：%d 个 | 已切换：%d | 失败：%d | 剩余引用：%d"
        % (report.tags_total, report.tags_changed, report.failed, report.remaining),
        "删除旧材质：%s" % ("是" if report.deleted else "否"),
        "-" * 52,
    ]
    lines.extend(report.details)
    return "\n".join(lines)


def format_report(result):
    """把结果整理成给人看的多行文本。"""
    report = result.report
    usage = result.usage
    lines = []
    if report.dry_run:
        lines.append("【只诊断模式：没有修改任何材质】")
    if report.method == "copyto":
        lines.append("拷贝方式：整材质完整拷贝（含节点图）")
        lines.append("节点图：%d 个节点，源与目标一致" % report.graph_nodes)
    else:
        lines.append("参数拷贝：%d 项（源材质共读到 %d 项）"
                     % (report.params_copied, report.params_seen))
        lines.append("着色器/渐变克隆：%d 个" % report.shaders_copied)
    lines.append("影响对象：%d 个对象 / %d 个材质标签" % (usage.objects, usage.tags))
    if report.verified_total:
        lines.append("回读校验：%d/%d 一致" % (report.verified_ok, report.verified_total))

    if report.params_skipped:
        preview = "、".join(report.params_skipped[:5])
        more = "" if len(report.params_skipped) <= 5 else " 等 %d 项" % len(report.params_skipped)
        lines.append("跳过参数：%s%s" % (preview, more))
    if report.params_failed:
        preview = "、".join(report.params_failed[:5])
        lines.append("失败参数：%s" % preview)

    if report.params_seen == 0:
        lines.append("警告：没能从源材质读到任何参数描述。可能是节点材质（Node Material），"
                     "或该材质没有可读的描述，请手动处理。")
    elif report.params_copied == 0 and report.shaders_copied == 0:
        lines.append("警告：读到了 %d 个参数，但一个都没写进目标材质。"
                     "多数是两边材质类型不同、没有同名参数，请手动检查。"
                     % report.params_seen)

    if report.src_graph_nodes and report.method != "copyto" and not report.dry_run:
        lines.append("重要：这是节点材质（%d 个节点）。外观在节点图里，逐参数拷贝改不动它——"
                     "上面那几项只是图标、预览尺寸之类的外壳属性。请改用「重定向引用」模式，"
                     "或手动在节点编辑器里复制节点。" % report.src_graph_nodes)
    elif report.src_graph_nodes and report.method == "copyto":
        pass
    if report.type_mismatch:
        lines.append("提示：源材质与目标材质类型不同，只拷贝了同名参数，请在材质编辑器里核对效果。")
    if usage.tags == 0 and not report.dry_run:
        lines.append("提示：当前场景没有对象引用源材质，内容已覆盖但暂时看不到变化。")
    return "\n".join(lines)


def format_details(result):
    """逐参数诊断日志（写文件用）。"""
    report = result.report
    usage = result.usage
    lines = [
        "C4D 材质替换诊断日志",
        "模式：%s" % ("只诊断，未修改任何材质" if report.dry_run else "已执行覆盖"),
        "拷贝方式：%s" % ("整材质 CopyTo" if report.method == "copyto" else "逐参数"),
        "节点图：源 %d 个节点 / 目标 %d 个节点" % (report.src_graph_nodes, report.graph_nodes),
        "源材质：%s | type=%s" % (report.src_name, report.src_type),
        "目标材质：%s | type=%s" % (report.dst_name, report.dst_type),
        "类型一致：%s" % ("否" if report.type_mismatch else "是"),
        "读到参数：%d | 写入：%d | 克隆：%d | 跳过：%d | 失败：%d"
        % (report.params_seen, report.params_copied, report.shaders_copied,
           len(report.params_skipped), len(report.params_failed)),
        "引用：%d 个对象 / %d 个材质标签" % (usage.objects, usage.tags),
        "回读校验：%d/%d 一致" % (report.verified_ok, report.verified_total),
        "-" * 52,
    ]
    lines.extend(report.details)
    return "\n".join(lines)


def write_diagnostics_log(text):
    """把日志写到磁盘，返回路径；全失败则返回空串。"""
    candidates = []
    try:
        base = os.path.dirname(os.path.abspath(globals().get("__file__", "") or ""))
        if base:
            candidates.append(base)
    except Exception:
        pass
    for env in ("TEMP", "TMP"):
        folder = os.environ.get(env)
        if folder:
            candidates.append(folder)
    try:
        candidates.append(os.getcwd())
    except Exception:
        pass

    for folder in candidates:
        target = os.path.join(folder, "材质替换_诊断.log")
        try:
            handle = io.open(target, "w", encoding="utf-8-sig")
            try:
                handle.write(text)
            finally:
                handle.close()
            return target
        except Exception:
            continue
    return ""


# ============================================================================
# 对话框
# ============================================================================
# ---------------------------------------------------------------- 链接框工具
def _is_material(obj):
    """判断链接框里的东西是不是材质球。"""
    if obj is None:
        return False
    try:
        if isinstance(obj, c4d.BaseMaterial):
            return True
    except Exception:
        pass
    try:
        return obj.GetType() == c4d.Mmaterial
    except Exception:
        return False


def _link_gui(dialog, gid):
    try:
        return dialog.FindCustomGui(gid, c4d.CUSTOMGUI_LINKBOX)
    except Exception:
        return None


def _link_get(dialog, gid):
    """读链接框里的对象。

    官方签名是 ``GetLink(doc, instance)``，但旧版和部分文档示例用无参形式，
    两种都试一次，避免版本差异导致读不到。
    """
    gui = _link_gui(dialog, gid)
    if gui is None:
        return None
    try:
        doc = c4d.documents.GetActiveDocument()
    except Exception:
        doc = None

    attempts = []
    if doc is not None:
        for instance in (getattr(c4d, "Mmaterial", None), getattr(c4d, "BaseMaterial", None)):
            if instance is not None:
                attempts.append((doc, instance))
    attempts.append(())

    for args in attempts:
        try:
            link = gui.GetLink(*args)
        except TypeError:
            continue
        except Exception:
            continue
        if link is not None:
            return link
    return None


def _link_set(dialog, gid, mat):
    """把材质放进链接框；兼容 SetLink(obj) 与 SetLink(doc, obj) 两种签名。"""
    gui = _link_gui(dialog, gid)
    if gui is None:
        return False
    try:
        doc = c4d.documents.GetActiveDocument()
    except Exception:
        doc = None

    for args in ((mat,), (doc, mat)):
        try:
            if gui.SetLink(*args):
                return True
        except TypeError:
            continue
        except Exception:
            continue
    return False


# ============================================================================
# 对话框
# ============================================================================
# 缩略图交给链接框自带的官方小图标，不自绘预览区。
# 界面只有三行：两行「标签 + 链接框 + 拾取」，一行四个按钮，没有结果框。
LINK_HEIGHT = 18      # 链接框高度（容得下官方图标）
LABEL_WIDTH = 36      # 左侧标签宽度（「源」「目标」）
PICK_WIDTH = 46       # 行内「拾取」按钮宽度
DIALOG_WIDTH = 224    # 初始窗口宽
DIALOG_HEIGHT = 108   # 初始窗口高


class MaterialReplaceDialog(c4d.gui.GeDialog):
    """只做一件事：把所有引用源材质的材质标签改指目标材质。"""

    GRP_MAIN = 1000
    GRP_ROW_SRC = 1002
    GRP_ROW_DST = 1003
    TXT_SRC = 1010
    TXT_DST = 1011
    SPACER = 1015
    LNK_SRC = 1020
    LNK_DST = 1021
    BTN_CLEAR = 1030
    BTN_PICK_SRC = 1031
    BTN_PICK_DST = 1032
    BTN_SWAP = 1033
    GRP_BTN = 1060
    BTN_RUN = 1061

    MODE_REDIRECT = 1
    MODE_OVERWRITE = 0

    def __init__(self):
        c4d.gui.GeDialog.__init__(self)
        self._materials = []
        self._use_combo = getattr(c4d, "CUSTOMGUI_LINKBOX", None) is None

    # -- 数据
    def refresh_from_document(self, doc=None):
        if doc is None:
            try:
                doc = c4d.documents.GetActiveDocument()
            except Exception:
                doc = None
        self._materials = get_materials(doc)
        return self._materials

    def _reload(self):
        self.refresh_from_document()
        if self._use_combo:
            for gid in (self.LNK_SRC, self.LNK_DST):
                try:
                    self.FreeChildren(gid)
                except Exception:
                    pass
                for index, mat in enumerate(self._materials):
                    try:
                        self.AddChild(gid, index + 1, _material_label(mat, index))
                    except Exception:
                        pass
        self._sync_previews()

    # -- 链接框读写
    def _picked(self, gid):
        if self._use_combo:
            try:
                index = self.GetInt32(gid) - 1
            except Exception:
                index = -1
            if 0 <= index < len(self._materials):
                return self._materials[index]
            return None
        obj = _link_get(self, gid)
        if obj is None or not _is_material(obj):
            return None
        return obj

    def _raw_link(self, gid):
        if self._use_combo:
            return None
        return _link_get(self, gid)

    def _set_pick(self, gid, mat):
        if self._use_combo:
            for index, existing in enumerate(self._materials):
                if _same(existing, mat):
                    try:
                        self.SetInt32(gid, index + 1)
                        return True
                    except Exception:
                        return False
            return False
        return _link_set(self, gid, mat)

    def _clear_all(self):
        for gid in (self.LNK_SRC, self.LNK_DST):
            self._set_pick(gid, None)
        self._sync_previews()

    def _pick_active(self, gid):
        """把材质管理器里当前选中的材质填进链接框。"""
        try:
            doc = c4d.documents.GetActiveDocument()
        except Exception:
            doc = None

        mat = None
        if doc is not None:
            try:
                mats = doc.GetActiveMaterials()
            except Exception:
                mats = None
            if mats:
                mat = mats[0]
            if mat is None:
                try:
                    mat = doc.GetActiveMaterial()
                except Exception:
                    mat = None

        if mat is None or not _is_material(mat):
            self._warn("材质管理器里没有选中的材质球。\n"
                       "请先在材质管理器里点选一个材质，或者直接把材质球拖进链接框。")
            return

        if not self._set_pick(gid, mat):
            self._warn("无法把材质放进链接框：%s" % _mat_name(mat))
            return
        self._sync_previews()

    def _swap_picks(self):
        src = self._raw_link(self.LNK_SRC)
        dst = self._raw_link(self.LNK_DST)
        self._set_pick(self.LNK_SRC, dst)
        self._set_pick(self.LNK_DST, src)
        self._sync_previews()

    def _sync_previews(self):
        """链接框内容变化时校验一次；拖进非材质对象要说清楚。"""
        src = self._picked(self.LNK_SRC)
        raw = self._raw_link(self.LNK_SRC) if src is None else None
        if raw is not None:
            self._set_result("源框不是材质球：%s" % _mat_name(raw))

    # -- 界面
    def _add_link(self, gid):
        """官方链接框，图标用系统自带的材质缩略图。"""
        if self._use_combo:
            self.AddComboBox(gid, 0, LINK_HEIGHT)
            return
        data = c4d.BaseContainer()
        self.AddCustomGui(gid, c4d.CUSTOMGUI_LINKBOX, "", c4d.BFH_SCALEFIT, 0,
                          LINK_HEIGHT, data)

    def _add_slot(self, grp_id, txt_id, lnk_id, btn_id, label):
        """一行三格：标签 | 链接框 | 拾取（紧跟在链接框吸管后面）。"""
        self.GroupBegin(grp_id, c4d.BFH_SCALEFIT, 3, 0, "")
        self.AddStaticText(txt_id, c4d.BFH_LEFT, LABEL_WIDTH, 0, label, 0)
        self._add_link(lnk_id)
        self.AddButton(btn_id, c4d.BFH_LEFT, PICK_WIDTH, LINK_HEIGHT, "拾取")
        self.GroupEnd()

    def CreateLayout(self):
        self.SetTitle("材质替换")

        # 主容器必须双向 SCALEFIT，否则窗口会被锁死在布局最小尺寸、拖不动
        self.GroupBegin(self.GRP_MAIN, c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 1, 4, "")

        self._add_slot(self.GRP_ROW_SRC, self.TXT_SRC, self.LNK_SRC,
                       self.BTN_PICK_SRC, "源")
        self._add_slot(self.GRP_ROW_DST, self.TXT_DST, self.LNK_DST,
                       self.BTN_PICK_DST, "目标")

        # 空白占位吸收多余高度：窗口拉高时按钮沉底，拉宽时链接框变长
        self.AddStaticText(self.SPACER,
                           c4d.BFH_SCALEFIT | c4d.BFV_SCALEFIT, 0, 0, "", 0)

        # 底部三个按钮并排一行（关窗走标题栏的 × 或 Esc）
        self.GroupBegin(self.GRP_BTN, c4d.BFH_SCALEFIT, 3, 0, "")
        self.AddButton(self.BTN_RUN, c4d.BFH_SCALEFIT, 0, 0, "替换")
        self.AddButton(self.BTN_SWAP, c4d.BFH_SCALEFIT, 0, 0, "交换")
        self.AddButton(self.BTN_CLEAR, c4d.BFH_SCALEFIT, 0, 0, "清空")
        self.GroupEnd()

        self.GroupEnd()
        return True

    def InitValues(self):
        self._reload()
        return True

    def _mode(self):
        """界面只保留「重定向引用」（等同 Alt 拖拽），保留入口便于日后恢复双模式。"""
        return self.MODE_REDIRECT

    def Command(self, cid, msg):
        try:
            if cid == self.BTN_CLEAR:
                self._clear_all()
                return True
            if cid == self.BTN_PICK_SRC:
                self._pick_active(self.LNK_SRC)
                return True
            if cid == self.BTN_PICK_DST:
                self._pick_active(self.LNK_DST)
                return True
            if cid == self.BTN_SWAP:
                self._swap_picks()
                return True
            if cid == self.BTN_RUN:
                self._execute()
                return True
            if cid in (self.LNK_SRC, self.LNK_DST):
                self._sync_previews()
                return True
        except Exception as err:
            self._warn("操作失败：%s" % err)
        return True

    def Message(self, msg, result):
        try:
            if msg.GetId() == c4d.BFM_ACTION:
                if msg[c4d.BFM_ACTION_ID] in (self.LNK_SRC, self.LNK_DST):
                    self._sync_previews()
        except Exception:
            pass
        return c4d.gui.GeDialog.Message(self, msg, result)

    # -- 执行
    def _execute(self):
        try:
            doc = c4d.documents.GetActiveDocument()
        except Exception:
            doc = None
        if doc is None:
            self._warn("没有打开的工程文件")
            return

        self.refresh_from_document(doc)
        src = self._picked(self.LNK_SRC)
        dst = self._picked(self.LNK_DST)
        if src is None or dst is None:
            missing = []
            if src is None:
                missing.append("源材质")
            if dst is None:
                missing.append("目标材质")
            self._warn("还缺少：%s\n\n把材质球从材质管理器拖进链接框，"
                       "或选中材质后点「拾取」。" % "、".join(missing))
            return
        if _same(src, dst):
            self._warn("源材质和目标材质是同一个材质球，请重新选择")
            return

        try:
            report = redirect_references(doc, src, dst, delete_old=False, dry_run=False)
        except Exception as err:
            self._warn("替换失败：%s" % err)
            return

        brief = format_redirect_brief(report, src, dst)
        detail = brief
        # 只有出问题才落日志，正常成功不往硬盘写东西
        if report.failed or (0 < report.tags_total and report.tags_changed < report.tags_total):
            log_path = write_diagnostics_log(format_redirect_details(report, src, dst))
            if log_path:
                detail = "%s（诊断日志：%s）" % (brief, log_path)

        self._set_result(brief, detail)
        self._sync_previews()
        try:
            c4d.EventAdd()
        except Exception:
            pass

    def _set_result(self, brief, detail=None):
        """没有结果框了：摘要放标题栏，细节放 C4D 状态栏。"""
        try:
            self.SetTitle("材质替换 · %s" % brief if brief else "材质替换")
        except Exception:
            pass
        try:
            c4d.StatusSetText(detail if detail is not None else (brief or ""))
        except Exception:
            pass

    def _warn(self, text):
        try:
            c4d.gui.MessageDialog(text, c4d.GEMB_OK)
        except Exception:
            pass


# ============================================================================
# 插件命令
# ============================================================================
class MaterialReplaceCommand(c4d.plugins.CommandData):

    def Execute(self, doc):
        global _DIALOG
        try:
            if _DIALOG is None:
                _DIALOG = MaterialReplaceDialog()
            _DIALOG.refresh_from_document(doc)
            return _DIALOG.Open(c4d.DLG_TYPE_ASYNC, PLUGIN_ID,
                                defaultw=DIALOG_WIDTH, defaulth=DIALOG_HEIGHT)
        except Exception:
            return False

    def GetState(self, doc):
        return c4d.CMD_ENABLED if hasattr(c4d, "CMD_ENABLED") else True

    def RestoreLayout(self, secret):
        return True


def register_command():
    global _REGISTERED
    if _REGISTERED:
        return True
    try:
        ok = c4d.plugins.RegisterCommandPlugin(
            PLUGIN_ID, PLUGIN_NAME, 0, None,
            "把所有引用指定材质球的材质标签一键改指另一个材质球（等同 Alt 拖拽）",
            MaterialReplaceCommand())
        _REGISTERED = bool(ok)
    except Exception:
        return False
    return _REGISTERED


def run_as_script():
    """脚本模式：注册命令（让对话框 id 合法）后打开窗口，并保住引用防止被回收。"""
    global _DIALOG
    register_command()
    if _DIALOG is not None:
        try:
            if _DIALOG.IsOpen():
                _DIALOG.Close()
        except Exception:
            pass
    if _DIALOG is None:
        _DIALOG = MaterialReplaceDialog()
    _DIALOG.refresh_from_document()
    return _DIALOG.Open(c4d.DLG_TYPE_ASYNC, PLUGIN_ID,
                        defaultw=DIALOG_WIDTH, defaulth=DIALOG_HEIGHT)


def _bootstrap():
    path = globals().get("__file__", "")
    if is_plugin_mode(path):
        return register_command()
    return run_as_script()


try:
    _bootstrap()
except Exception:
    pass
