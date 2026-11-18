"""Cinema 4D Python API 最小桩件（按官方文档语义，v2）。

关键修正（v1 的错误假设）：
- Description 迭代产出三元组 (BaseContainer, DescID, DescID)，不是 (id, value)
- 参数 id 是 c4d.DescID，不是 int
- GetParameter/SetParameter 接受 DescID，SetParameter 返回 bool
"""

import types

# ---------------------------------------------------------------- 常量
ID_BASELIST_NAME = 900

Ttexture = 5616
TEXTURETAG_MATERIAL = 1010

Mmaterial = 5703
Mredshift = 1030393
Ocube = 5159
Xcolor = 1011117

UNDOTYPE_CHANGE = 4
UNDOTYPE_NEW = 2

DESCFLAGS_DESC_0 = 0
DESCFLAGS_GET_0 = 0
DESCFLAGS_SET_0 = 0

DESC_NAME = 1
DESC_SHORT_NAME = 2
DESC_TYPE = 3
DESC_IDENT = 4

DESC_IDENT_ONLY = 3001

CUSTOMGUI_LINKBOX = 200000027

LINKBOX_HIDE_ICON = 1000
BMP_ALLOWALPHA = 1
BMP_NORMALSCALED = 2

DESCFLAGS_SET_FORCESET = 1024

DTYPE_GROUP = 1
DTYPE_BUTTON = 4
DTYPE_SEPARATOR = 5
DTYPE_STATICTEXT = 20
DTYPE_SUBCONTAINER = 26
DTYPE_REAL = 19
DTYPE_LONG = 15
DTYPE_BOOL = 12
DTYPE_VECTOR = 23
DTYPE_COLOR = 24
DTYPE_STRING = 130
DTYPE_FILENAME = 131
DTYPE_TIME = 22
DTYPE_BASELISTLINK = 133

DLG_TYPE_ASYNC = 1
BFH_SCALEFIT = 1
BFH_LEFT = 2
BFV_SCALEFIT = 8
BFV_TOP = 128
GEMB_YESNO = 4
GEMB_OK = 1
GEMB_R_YES = 6
GEMB_R_NO = 7

BFM_ACTION = 1012
BFM_ACTION_ID = 1013
CMD_ENABLED = 1

# 测试用参数 id
P_COLOR = 2000
P_ROUGH = 2001
P_NAME_PARAM = 2002
P_SHADER = 2003
P_GROUP = 2004
P_BUTTON = 2005
P_ONLY_SRC = 2006
P_GRADIENT = 2007


class DescID(object):
    def __init__(self, ids):
        self._ids = tuple(ids)

    def __hash__(self):
        return hash(self._ids)

    def __eq__(self, other):
        return isinstance(other, DescID) and self._ids == other._ids

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return "DescID%s" % (self._ids,)

    def __getitem__(self, index):
        return self._ids[index]

    def __len__(self):
        return len(self._ids)

    def GetDepth(self):
        return len(self._ids)


def DID(pid):
    """构造单层 DescID。"""
    return DescID((pid,))


class Vector(object):
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)

    def __eq__(self, other):
        return (isinstance(other, Vector)
                and abs(self.x - other.x) < 1e-9
                and abs(self.y - other.y) < 1e-9
                and abs(self.z - other.z) < 1e-9)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return "Vector(%g, %g, %g)" % (self.x, self.y, self.z)


def _copy_value(value):
    if isinstance(value, Vector):
        return Vector(value.x, value.y, value.z)
    return value


def _norm(did):
    if isinstance(did, DescID):
        return did
    if isinstance(did, int):
        return DID(did)
    raise TypeError("parameter id must be int or DescID: %r" % (did,))


class DescEntryBC(object):
    """description 迭代里给出的 (BaseContainer) 描述项。"""

    def __init__(self, name, dtype, ident=""):
        self._name = name
        self._dtype = dtype
        self._ident = ident

    def __getitem__(self, key):
        if key == DESC_NAME:
            return self._name
        if key == DESC_SHORT_NAME:
            return self._name
        if key == DESC_TYPE:
            return self._dtype
        if key == DESC_IDENT:
            return self._ident
        raise KeyError(key)


class FakeDescription(object):
    def __init__(self, items):
        self._items = list(items)

    def __iter__(self):
        for pid, name, dtype in self._items:
            yield DescEntryBC(name, dtype), DID(pid), DID(0)

    def GetParameter(self, did, ar=None):
        did = _norm(did)
        for pid, name, dtype in self._items:
            if DID(pid) == did:
                return DescEntryBC(name, dtype)
        return None


class DescIterator(object):
    """可控 description：条目只有 DESC_IDENT，没有 DESC_NAME。"""

    def __init__(self, rows):
        self._rows = list(rows)

    def __iter__(self):
        for pid, dtype, ident in self._rows:
            yield DescEntryBC("", dtype, ident), DID(pid), DID(0)


class BaseList2D(object):
    def __init__(self, name="", type_id=0, params=None):
        self._type = type_id
        self._params = {}
        self._children = []
        self._doc = None
        self._parent = None
        self._updated = False
        self._params[DID(ID_BASELIST_NAME)] = (DTYPE_STRING, name)
        if params:
            for pid, pair in params.items():
                self._params[DID(pid)] = pair

    # -- 基本属性
    def GetName(self):
        pair = self._params.get(DID(ID_BASELIST_NAME))
        return pair[1] if pair else ""

    def SetName(self, name):
        self._params[DID(ID_BASELIST_NAME)] = (DTYPE_STRING, name)

    def GetType(self):
        return self._type

    def GetRealType(self):
        return self._type

    def GetDocument(self):
        return self._doc

    def GetUp(self):
        return self._parent

    # -- 参数读写（按真实 API：DescID 入参，SetParameter 返回 bool）
    def __getitem__(self, did):
        did = _norm(did)
        if did not in self._params:
            raise KeyError(did)
        return _copy_value(self._params[did][1])

    def __setitem__(self, did, value):
        did = _norm(did)
        if did not in self._params:
            raise KeyError(did)
        if did[0] in getattr(self, "readonly_params", ()):
            return  # 真实 C4D 里 op[id] = value 对只读参数就是静默失败
        self._params[did] = (self._params[did][0], _copy_value(value))

    def GetParameter(self, did, flags=0):
        did = _norm(did)
        if did not in self._params:
            return None
        return _copy_value(self._params[did][1])

    def SetParameter(self, did, value, flags=0):
        did = _norm(did)
        if did not in self._params:
            return False
        readonly = getattr(self, "readonly_params", ())
        if did[0] in readonly and not (flags & DESCFLAGS_SET_FORCESET):
            return False
        self._params[did] = (self._params[did][0], _copy_value(value))
        return True

    def GetDescription(self, flags=0):
        items = []
        for did, pair in sorted(self._params.items(), key=lambda kv: kv[0][0]):
            items.append((did[0], self._label(did[0]), pair[0]))
        return FakeDescription(items)

    def _label(self, pid):
        table = {
            P_COLOR: "颜色", P_ROUGH: "粗糙度", P_NAME_PARAM: "自定义名字",
            P_SHADER: "颜色着色器", P_GROUP: "分组", P_BUTTON: "按钮",
            P_ONLY_SRC: "仅源材质独有", P_GRADIENT: "渐变",
            ID_BASELIST_NAME: "名称",
        }
        return table.get(pid, "参数%s" % pid)

    # -- 子对象
    def InsertShader(self, shader):
        self._children.append(shader)
        shader._parent = self
        return True

    def InsertUnder(self, parent):
        if hasattr(parent, "InsertShader"):
            return parent.InsertShader(self)
        return False

    def Remove(self):
        parent = getattr(self, "_parent", None)
        if parent is not None and self in parent._children:
            parent._children.remove(self)
        self._parent = None
        return True

    def GetFirstShader(self):
        return self._children[0] if self._children else None

    def GetDown(self):
        return self._children[0] if self._children else None

    def ChildCount(self):
        return len(self._children)

    def GetClone(self):
        clone = self.__class__.__new__(self.__class__)
        BaseList2D.__init__(clone, self.GetName(), self._type, None)
        clone._params = {}
        for did, pair in self._params.items():
            clone._params[did] = (pair[0], _copy_value(pair[1]))
        clone._children = []
        for child in self._children:
            child_clone = child.GetClone()
            clone._children.append(child_clone)
            child_clone._parent = clone
        return clone

    def Update(self, flag):
        self._updated = True
        return True

    def CopyTo(self, dst, flags=0, trn=None):
        """模拟 C4DAtom.CopyTo：参数 + 子对象（节点图）一起搬过去。"""
        if not getattr(self, "copyto_ok", True):
            return False
        for did, pair in self._params.items():
            value = pair[1]
            if isinstance(value, BaseList2D):
                value = value.GetClone()   # 节点是独立副本，不与源材质共享
            else:
                value = _copy_value(value)
            dst._params[did] = (pair[0], value)
        dst._children = []
        for child in self._children:
            clone = child.GetClone()
            clone._parent = dst
            dst._children.append(clone)
        return True

    def GetActive(self):
        return False


class BaseShader(BaseList2D):
    def __init__(self, name="", type_id=Xcolor, params=None):
        super(BaseShader, self).__init__(name, type_id, params)


class Gradient(BaseList2D):
    def __init__(self, name="", params=None):
        super(Gradient, self).__init__(name, 1019, params)


class BaseMaterial(BaseList2D):
    def __init__(self, name="", type_id=Mmaterial, params=None):
        super(BaseMaterial, self).__init__(name, type_id, params)

    def Remove(self):
        doc = getattr(self, "_doc", None)
        if doc is not None and self in doc.materials:
            doc.materials.remove(self)
        return True

    def GetPreview(self, flags=0):
        if not getattr(self, "has_preview", True):
            return None
        return Bitmap(64, 64)


class GvNode(BaseList2D):
    """Redshift / 节点材质里的图节点桩件。"""

    def __init__(self, name="node", params=None):
        super(GvNode, self).__init__(name, 400006001, params)


class BaseTag(BaseList2D):
    pass


class BaseObject(BaseList2D):
    def __init__(self, name="", params=None):
        super(BaseObject, self).__init__(name, 5100, params)
        self._tags = []
        self._children = []
        self._next = None
        self._parent = None

    def GetTags(self):
        return list(self._tags)

    def AddTag(self, tag):
        self._tags.append(tag)

    def GetNext(self):
        return self._next

    def GetDown(self):
        return self._children[0] if self._children else None

    def GetUp(self):
        return self._parent


class LinkBoxGui(object):
    """CUSTOMGUI_LINKBOX 桩件：SetLink(obj) / GetLink(doc, instance)。"""

    def __init__(self, cid):
        self.cid = cid
        self._link = None
        self.set_link_calls = 0
        self.get_link_calls = 0

    def SetLink(self, obj):
        self.set_link_calls += 1
        if obj is not None and not isinstance(obj, BaseList2D):
            return False
        self._link = obj
        return True

    def GetLink(self, doc=None, instance=None):
        self.get_link_calls += 1
        if self._link is None:
            return None
        if isinstance(instance, int) and not isinstance(instance, bool):
            # 用类型 id 过滤时，材质类对象视为通过
            if not isinstance(self._link, BaseMaterial):
                return None
        elif isinstance(instance, type):
            if not isinstance(self._link, instance):
                return None
        return self._link


class BaseDocument(object):
    def __init__(self):
        self._roots = []
        self.materials = []
        self.undo_log = []

    def AddRoot(self, obj):
        self._roots.append(obj)

    def GetFirstObject(self):
        return self._roots[0] if self._roots else None

    def GetMaterials(self):
        return list(self.materials)

    def set_active_materials(self, mats):
        self._active_materials = list(mats)

    def GetActiveMaterials(self):
        return list(getattr(self, "_active_materials", []))

    def GetActiveMaterial(self):
        mats = self.GetActiveMaterials()
        return mats[0] if mats else None

    def InsertMaterial(self, mat):
        self.materials.append(mat)
        mat._doc = self

    def StartUndo(self):
        self.undo_log.append(("start", None, None))

    def EndUndo(self):
        self.undo_log.append(("end", None, None))

    def AddUndo(self, undo_type, obj, *args):
        self.undo_log.append(("add", undo_type, obj))


# ---------------------------------------------------------------- 构造工具
def make_texture_tag(material):
    tag = BaseTag("纹理标签", Ttexture, {})
    tag._params[DID(TEXTURETAG_MATERIAL)] = (DTYPE_BASELISTLINK, material)
    return tag


def make_material(name, type_id=Mmaterial, params=None):
    base = {
        P_COLOR: (DTYPE_COLOR, Vector(1.0, 1.0, 1.0)),
        P_ROUGH: (DTYPE_REAL, 0.5),
        P_NAME_PARAM: (DTYPE_STRING, name + "_label"),
        P_SHADER: (DTYPE_BASELISTLINK, None),
        P_GROUP: (DTYPE_GROUP, None),
        P_BUTTON: (DTYPE_BUTTON, None),
    }
    if params:
        base.update(params)
    return BaseMaterial(name, type_id, base)


def make_node_material(name, node_count=3):
    """造一个「节点材质」：外观参数是挂在材质下的 GvNode，而不是普通数值参数。"""
    mat = make_material(name)
    for i in range(node_count):
        node = GvNode("%s_node%d" % (name, i))
        node._parent = mat
        mat._children.append(node)
        mat._params[DID(20000 + i)] = (DTYPE_BASELISTLINK, node)
    return mat


def make_object(name, tags=None):
    obj = BaseObject(name)
    for tag in tags or []:
        obj.AddTag(tag)
    return obj


def link_siblings(parent, children):
    for i, child in enumerate(children):
        child._parent = parent
        child._next = children[i + 1] if i + 1 < len(children) else None
    parent._children = list(children)
    return parent


def build_document(roots=None, materials=None):
    doc = BaseDocument()
    roots = roots or []
    for i, root in enumerate(roots):
        root._next = roots[i + 1] if i + 1 < len(roots) else None
        root._parent = None
    doc._roots = list(roots)
    for mat in materials or []:
        doc.InsertMaterial(mat)
    return doc


def get_param(mat, pid):
    return mat.GetParameter(DID(pid))


def set_param(mat, pid, value):
    return mat.SetParameter(DID(pid), value)


# ---------------------------------------------------------------- gui / plugins
class BaseContainer(object):
    """c4d.BaseContainer 桩件：轻量 dict 语义。"""

    def __init__(self):
        self._data = {}

    def __setitem__(self, key, value):
        self._data[key] = value

    def __getitem__(self, key):
        if key not in self._data:
            raise KeyError(key)
        return self._data[key]

    def SetData(self, key, value):
        self._data[key] = value
        return True

    def GetData(self, key, default=None):
        return self._data.get(key, default)

    def GetBool(self, key):
        return bool(self._data.get(key, False))

    def __contains__(self, key):
        return key in self._data


class Bitmap(object):
    """BaseBitmap 桩件。"""

    def __init__(self, w=64, h=64):
        self._w = w
        self._h = h

    def GetWidth(self):
        return self._w

    def GetHeight(self):
        return self._h


class GeUserArea(object):
    """GeUserArea 桩件：记录所有绘制调用，供测试断言。"""

    def __init__(self):
        self.drawn = []
        self.redraws = 0

    def OffScreenOn(self, x=-1, y=0, w=0, h=0):
        return True

    def Redraw(self, thread=False):
        self.redraws += 1
        return True

    def GetMinSize(self):
        return 0, 0

    def DrawSetPen(self, col):
        self.drawn.append(("pen",))
        return True

    def DrawRectangle(self, x1, y1, x2, y2):
        self.drawn.append(("rect", x1, y1, x2, y2))
        return True

    def DrawSetTextCol(self, fg, bg):
        self.drawn.append(("textcol",))
        return True

    def DrawText(self, txt, x, y):
        self.drawn.append(("text", txt))
        return True

    def DrawBitmap(self, bmp, wx, wy, ww, wh, x, y, w, h, mode):
        self.drawn.append(("bitmap", bmp, wx, wy, ww, wh))
        return True


class GeDialog(object):
    def __init__(self):
        self.calls = []
        self.values = {}
        self.customguis = {}
        self.customdata = {}
        self.userareas = {}
        self.attached = {}

    def Open(self, dlgtype=0, pluginid=0, defaultw=0, defaulth=0, xpos=-1, ypos=-1):
        self.calls.append(("Open", dlgtype, pluginid))
        self.open_size = (defaultw, defaulth)
        return True

    def Close(self):
        self.calls.append(("Close",))
        return True

    def SetTitle(self, title):
        self.calls.append(("SetTitle", title))
        self.title = title
        return True

    def CreateLayout(self):
        return True

    def InitValues(self):
        return True

    def Command(self, cid, msg):
        return True

    def Message(self, msg, result):
        return True

    def LayoutChanged(self):
        return True

    def GroupBegin(self, cid, flags, cols=0, rows=0, title="", groupflags=0):
        self.calls.append(("GroupBegin", cid, cols, rows, flags))
        return True

    def GroupEnd(self):
        self.calls.append(("GroupEnd",))
        return True

    def AddCustomGui(self, cid, pluginid, name, flags, initw=0, inith=0, customdata=None):
        self.calls.append(("AddCustomGui", cid, pluginid, initw, inith))
        self.customdata[cid] = customdata
        gui = None
        if pluginid == CUSTOMGUI_LINKBOX:
            gui = LinkBoxGui(cid)
        self.customguis[cid] = gui
        return gui

    def AddUserArea(self, cid, flags, initw=0, inith=0):
        self.calls.append(("AddUserArea", cid, initw, inith))
        area = GeUserArea()
        self.userareas[cid] = area
        return True

    def AttachUserArea(self, ua, cid):
        self.attached[cid] = ua
        return True

    def FindCustomGui(self, cid, pluginid):
        gui = self.customguis.get(cid)
        if gui is None:
            return None
        if pluginid == CUSTOMGUI_LINKBOX and not isinstance(gui, LinkBoxGui):
            return None
        return gui

    def AddComboBox(self, cid, width, height, specialalign=False, allowfiltering=False):
        self.calls.append(("AddComboBox", cid, width))
        return True

    def AddChild(self, cid, subid, name):
        self.calls.append(("AddChild", cid, subid, name))
        return True

    def FreeChildren(self, cid):
        self.calls.append(("FreeChildren", cid))
        return True

    def AddStaticText(self, cid, flags, initw=0, inith=0, name="", borderstyle=0):
        self.calls.append(("AddStaticText", cid, name))
        return True

    def AddButton(self, cid, flags, initw=0, inith=0, name=""):
        self.calls.append(("AddButton", cid, name))
        return True

    def AddCheckbox(self, cid, flags, initw=0, inith=0, name=""):
        self.calls.append(("AddCheckbox", cid, name))
        return True

    def SetBool(self, cid, value):
        self.values[cid] = bool(value)
        return True

    def GetBool(self, cid):
        return bool(self.values.get(cid, False))

    def AddMultiLineEditText(self, cid, flags, initw=0, inith=0, style=0):
        self.calls.append(("AddMultiLineEditText", cid, inith))
        return True

    def SetString(self, cid, value, flags=0):
        self.values[cid] = value
        return True

    def GetString(self, cid):
        return self.values.get(cid, "")

    def SetInt32(self, cid, value, flags=0):
        self.values[cid] = value
        return True

    def GetInt32(self, cid):
        return self.values.get(cid, 0)


class CommandData(object):
    def Execute(self, doc):
        return True

    def GetState(self, doc):
        return CMD_ENABLED

    def RestoreLayout(self, secret):
        return True


class _PluginsModule(object):
    def __init__(self):
        self.registered = []
        self.CommandData = CommandData

    def RegisterCommandPlugin(self, plugin_id, name, info, icon, help, dat):
        self.registered.append((plugin_id, name, dat))
        return True


class _GuiModule(object):
    def __init__(self):
        self.GeDialog = GeDialog
        self.GeUserArea = GeUserArea
        self.dialogs = []

    def MessageDialog(self, text, type=0):
        self.dialogs.append(text)
        return GEMB_R_YES


class _GraphViewModule(object):
    def __init__(self):
        self.GvNode = GvNode


class _ModulesModule(object):
    def __init__(self):
        self.graphview = _GraphViewModule()


class _DocumentsModule(object):
    def __init__(self):
        self._active = None

    def set_active(self, doc):
        self._active = doc

    def GetActiveDocument(self):
        return self._active


STATUS_TEXTS = []


def StatusSetText(text):
    STATUS_TEXTS.append(text)
    return True


def StatusClear():
    return True


def as_module(name="c4d"):
    mod = types.ModuleType(name)
    for key, value in list(globals().items()):
        if key.startswith("_") or key in ("types", "as_module"):
            continue
        if isinstance(value, types.ModuleType):
            continue
        setattr(mod, key, value)
    mod.gui = _GuiModule()
    mod.plugins = _PluginsModule()
    mod.documents = _DocumentsModule()
    mod.modules = _ModulesModule()
    mod.BaseContainer = BaseContainer
    mod.Bitmap = Bitmap
    return mod
