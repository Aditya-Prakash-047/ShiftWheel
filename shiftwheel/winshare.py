"""Windows' share sheet (Nearby sharing, Mail, Teams, WhatsApp…) for files, from a desktop app.

Explorer's own "Share" verb only works inside Explorer, so this uses the documented route for
Win32 apps: IDataTransferManagerInterop.GetForWindow + ShowShareUIForWindow, answering the
DataRequested event with the files. Everything is plain ctypes against combase, so it needs no
extra packages. Vtable slots follow the method order in Windows' own .winmd metadata."""
from __future__ import annotations

import ctypes
import hashlib
import sys
import time
import uuid
from ctypes import POINTER, WINFUNCTYPE, byref, c_int, c_uint, c_void_p, c_wchar_p
from pathlib import Path

HRESULT = ctypes.HRESULT
S_OK, E_NOINTERFACE, E_FAIL = 0, -2147467262, -2147467259


class GUID(ctypes.Structure):
    _fields_ = [("raw", ctypes.c_ubyte * 16)]

    @classmethod
    def of(cls, u: uuid.UUID | str) -> "GUID":
        g = cls()
        ctypes.memmove(g.raw, (u if isinstance(u, uuid.UUID) else uuid.UUID(u)).bytes_le, 16)
        return g

    def uuid(self) -> uuid.UUID:
        return uuid.UUID(bytes_le=bytes(self.raw))


def pinterface(signature: str) -> uuid.UUID:
    """IID of a parameterised WinRT interface (the algorithm MIDL and C++/WinRT use)."""
    ns = uuid.UUID("11f47ad5-7b73-42c0-abae-878b1e16adee").bytes
    h = bytearray(hashlib.sha1(ns + signature.encode("utf-8")).digest()[:16])
    h[6] = (h[6] & 0x0F) | 0x50
    h[8] = (h[8] & 0x3F) | 0x80
    return uuid.UUID(bytes=bytes(h))


IID_IUnknown = uuid.UUID("00000000-0000-0000-c000-000000000046")
IID_IInspectable = uuid.UUID("af86e2e0-b12d-4c6a-9c5a-d7aa65101e90")
IID_IAgileObject = uuid.UUID("94ea2b94-e9cc-49e0-c0ff-ee64ca8f5b90")
IID_IDataTransferManagerInterop = uuid.UUID("3a3dcd6c-3eab-43dc-bcde-45671ce800c8")
IID_IDataTransferManager = uuid.UUID("a5caee9b-8708-49d1-8d36-67d25a8da00c")
IID_IDataRequestedEventArgs = uuid.UUID("cb8ba807-6ac5-43c9-8ac5-9ba232163182")
IID_IStorageFileStatics = uuid.UUID("5984c710-daf2-43c8-8bb4-a4d3eacfd03f")
IID_IStorageItem = uuid.UUID("4207a996-ca2f-42f7-bde8-8b10457a7f30")
IID_IAsyncInfo = uuid.UUID("00000036-0000-0000-c000-000000000046")
IID_IIterable_IStorageItem = pinterface(f"pinterface({{faa585ea-6214-4217-afda-7f46de5869b3}};{{{IID_IStorageItem}}})")
IID_IIterator_IStorageItem = pinterface(f"pinterface({{6a79e863-4300-459a-9966-cbb660963ee1}};{{{IID_IStorageItem}}})")
IID_DataRequestedHandler = pinterface(
    "pinterface({9de1c534-6ae1-11e0-84e1-18a905bcc53f};"
    f"rc(Windows.ApplicationModel.DataTransfer.DataTransferManager;{{{IID_IDataTransferManager}}});"
    f"rc(Windows.ApplicationModel.DataTransfer.DataRequestedEventArgs;{{{IID_IDataRequestedEventArgs}}}))")

# vtable slots (IUnknown = 0-2, IInspectable adds 3-5)
QI, ADDREF, RELEASE = 0, 1, 2
INTEROP_GET_FOR_WINDOW, INTEROP_SHOW = 3, 4
DTM_ADD_DATA_REQUESTED = 6
ARGS_GET_REQUEST = 6
REQUEST_GET_DATA, REQUEST_FAIL = 6, 9
PACKAGE_GET_PROPERTIES, PACKAGE_SET_STORAGE_ITEMS_READONLY = 7, 22
PROPS_PUT_TITLE, PROPS_PUT_DESCRIPTION = 7, 9
FILE_STATICS_FROM_PATH = 6
ASYNC_STATUS, ASYNC_ERROR = 7, 8
ASYNC_OP_RESULTS = 8


def _call(ptr, slot: int, *args, argtypes=()):
    """Call vtable[slot] on a COM pointer; failed HRESULTs raise OSError."""
    vtbl = ctypes.cast(ptr, POINTER(POINTER(c_void_p))).contents
    fn = WINFUNCTYPE(HRESULT, c_void_p, *argtypes)(vtbl[slot])
    return fn(ptr, *args)


def _out(ptr, slot: int, *args, argtypes=()) -> c_void_p:
    res = c_void_p()
    _call(ptr, slot, *args, byref(res), argtypes=(*argtypes, POINTER(c_void_p)))
    return res


def _qi(ptr, iid: uuid.UUID) -> c_void_p:
    return _out(ptr, QI, byref(GUID.of(iid)), argtypes=(POINTER(GUID),))


def _release(ptr):
    if ptr:
        WINFUNCTYPE(c_uint, c_void_p)(ctypes.cast(ptr, POINTER(POINTER(c_void_p))).contents[RELEASE])(ptr)


def _addref(ptr):
    WINFUNCTYPE(c_uint, c_void_p)(ctypes.cast(ptr, POINTER(POINTER(c_void_p))).contents[ADDREF])(ptr)


class _HString:
    def __init__(self, text: str):
        self.h = c_void_p()
        _combase().WindowsCreateString(c_wchar_p(text), len(text), byref(self.h))

    def __del__(self):
        try:
            _combase().WindowsDeleteString(self.h)
        except Exception:
            pass


_COMBASE = None


def _combase():
    global _COMBASE
    if _COMBASE is None:
        cb = ctypes.windll.combase
        cb.WindowsCreateString.argtypes = [c_wchar_p, c_uint, POINTER(c_void_p)]
        cb.WindowsCreateString.restype = HRESULT
        cb.WindowsDeleteString.argtypes = [c_void_p]
        cb.WindowsDeleteString.restype = HRESULT
        cb.RoGetActivationFactory.argtypes = [c_void_p, POINTER(GUID), POINTER(c_void_p)]
        cb.RoGetActivationFactory.restype = HRESULT
        _COMBASE = cb
    return _COMBASE


def _factory(class_name: str, iid: uuid.UUID) -> c_void_p:
    out, name = c_void_p(), _HString(class_name)
    _combase().RoGetActivationFactory(name.h, byref(GUID.of(iid)), byref(out))
    return out


# ---------------------------------------------------------------- tiny COM objects in Python
_KEEP: list = []      # COM objects handed to Windows must outlive every call it makes on them


class _ComObject:
    """A COM object with a hand-built vtable. `methods` follow IUnknown's three."""

    def __init__(self, iids: set[uuid.UUID], methods: list):
        self.iids = iids | {IID_IUnknown, IID_IAgileObject}
        self.refs = 1
        proto_qi = WINFUNCTYPE(c_int, c_void_p, POINTER(GUID), POINTER(c_void_p))
        proto_ref = WINFUNCTYPE(c_uint, c_void_p)
        self._fns = [proto_qi(self._qi), proto_ref(self._addref), proto_ref(self._release), *methods]
        self._vtbl = (c_void_p * len(self._fns))(*[ctypes.cast(f, c_void_p) for f in self._fns])
        self._obj = ctypes.pointer(c_void_p(ctypes.addressof(self._vtbl)))
        self.ptr = ctypes.cast(self._obj, c_void_p)
        _KEEP.append(self)

    def _qi(self, this, riid, ppv):
        if riid.contents.uuid() in self.iids:
            ppv[0] = this
            self.refs += 1
            return S_OK
        ppv[0] = None
        return E_NOINTERFACE

    def _addref(self, this):
        self.refs += 1
        return self.refs

    def _release(self, this):
        self.refs -= 1
        return max(self.refs, 0)


def _inspectable_methods():
    """GetIids, GetRuntimeClassName, GetTrustLevel for objects that are IInspectable."""
    def get_iids(this, count, iids):
        count[0] = 0
        iids[0] = None
        return S_OK

    def get_name(this, name):
        name[0] = None
        return S_OK

    def get_trust(this, level):
        level[0] = 0
        return S_OK
    return [WINFUNCTYPE(c_int, c_void_p, POINTER(c_uint), POINTER(c_void_p))(get_iids),
            WINFUNCTYPE(c_int, c_void_p, POINTER(c_void_p))(get_name),
            WINFUNCTYPE(c_int, c_void_p, POINTER(c_int))(get_trust)]


class _Iterator(_ComObject):
    def __init__(self, items: list):
        self.items, self.i = items, 0

        def current(this, out):
            if self.i >= len(self.items):
                return E_FAIL
            _addref(self.items[self.i])
            out[0] = self.items[self.i]
            return S_OK

        def has_current(this, out):
            out[0] = self.i < len(self.items)
            return S_OK

        def move_next(this, out):
            self.i += 1
            out[0] = self.i < len(self.items)
            return S_OK

        def get_many(this, capacity, out, actual):
            n = 0
            while n < capacity and self.i < len(self.items):
                _addref(self.items[self.i])
                out[n] = self.items[self.i]
                n += 1
                self.i += 1
            actual[0] = n
            return S_OK
        super().__init__({IID_IInspectable, IID_IIterator_IStorageItem}, [
            *_inspectable_methods(),
            WINFUNCTYPE(c_int, c_void_p, POINTER(c_void_p))(current),
            WINFUNCTYPE(c_int, c_void_p, POINTER(ctypes.c_bool))(has_current),
            WINFUNCTYPE(c_int, c_void_p, POINTER(ctypes.c_bool))(move_next),
            WINFUNCTYPE(c_int, c_void_p, c_uint, POINTER(c_void_p), POINTER(c_uint))(get_many)])


class _Iterable(_ComObject):
    def __init__(self, items: list):
        def first(this, out):
            out[0] = _Iterator(items).ptr
            return S_OK
        super().__init__({IID_IInspectable, IID_IIterable_IStorageItem},
                         [*_inspectable_methods(), WINFUNCTYPE(c_int, c_void_p, POINTER(c_void_p))(first)])


# ---------------------------------------------------------------- share
def _storage_item(path: str) -> c_void_p:
    statics = _factory("Windows.Storage.StorageFile", IID_IStorageFileStatics)
    hpath = _HString(path)
    try:
        op = _out(statics, FILE_STATICS_FROM_PATH, hpath.h, argtypes=(c_void_p,))
    finally:
        _release(statics)
    try:
        info = _qi(op, IID_IAsyncInfo)
        status = c_int(0)
        end = time.time() + 15
        while True:
            _call(info, ASYNC_STATUS, byref(status), argtypes=(POINTER(c_int),))
            if status.value != 0 or time.time() > end:        # 0 = Started
                break
            time.sleep(0.01)
        if status.value != 1:                                 # 1 = Completed
            code = c_int(0)
            _call(info, ASYNC_ERROR, byref(code), argtypes=(POINTER(c_int),))
            _release(info)
            raise OSError(code.value, f"Windows couldn't open {Path(path).name} for sharing")
        _release(info)
        file = _out(op, ASYNC_OP_RESULTS)
    finally:
        _release(op)
    item = _qi(file, IID_IStorageItem)
    _release(file)
    return item


class Sharer:
    """One per window. share() opens the share sheet for that window with the given files."""

    def __init__(self, hwnd: int):
        self.hwnd = hwnd
        self.files: list[str] = []
        self.error = ""
        self.requests = 0
        interop = _factory("Windows.ApplicationModel.DataTransfer.DataTransferManager",
                           IID_IDataTransferManagerInterop)
        self.interop = interop
        self.dtm = _out(interop, INTEROP_GET_FOR_WINDOW, c_void_p(hwnd), byref(GUID.of(IID_IDataTransferManager)),
                        argtypes=(c_void_p, POINTER(GUID)))
        self.handler = _ComObject({IID_DataRequestedHandler},
                                  [WINFUNCTYPE(c_int, c_void_p, c_void_p, c_void_p)(self._on_data_requested)])
        token = ctypes.c_int64()
        _call(self.dtm, DTM_ADD_DATA_REQUESTED, self.handler.ptr, byref(token),
              argtypes=(c_void_p, POINTER(ctypes.c_int64)))

    def share(self, paths: list[str]):
        self.files = [str(Path(p)) for p in paths]
        self.error = ""
        bring_to_front(self.hwnd)        # the sheet only opens for the window the user is in
        _call(self.interop, INTEROP_SHOW, c_void_p(self.hwnd), argtypes=(c_void_p,))


    def _on_data_requested(self, this, sender, args):
        self.requests += 1
        request = None
        try:
            ea = _qi(args, IID_IDataRequestedEventArgs)
            request = _out(ea, ARGS_GET_REQUEST)
            _release(ea)
            data = _out(request, REQUEST_GET_DATA)
            props = _out(data, PACKAGE_GET_PROPERTIES)
            names = [Path(p).name for p in self.files]
            title = names[0] if len(names) == 1 else f"{len(names)} files"
            htitle = _HString(title)
            _call(props, PROPS_PUT_TITLE, htitle.h, argtypes=(c_void_p,))
            if len(names) > 1:
                hdesc = _HString(", ".join(names)[:200])
                _call(props, PROPS_PUT_DESCRIPTION, hdesc.h, argtypes=(c_void_p,))
            _release(props)
            items = [_storage_item(p) for p in self.files]
            _call(data, PACKAGE_SET_STORAGE_ITEMS_READONLY, _Iterable(items).ptr, argtypes=(c_void_p,))
            _release(data)
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
            print(f"share: {e!r}", file=sys.stderr, flush=True)
            if request:
                try:
                    msg = _HString(f"Couldn't share: {e}")
                    _call(request, REQUEST_FAIL, msg.h, argtypes=(c_void_p,))
                except Exception:
                    pass
        finally:
            _release(request)
        return S_OK


def bring_to_front(hwnd: int):
    """SetForegroundWindow from a background app: borrow the foreground thread's input state."""
    u = ctypes.windll.user32
    fg = u.GetForegroundWindow()
    fg_thread = u.GetWindowThreadProcessId(fg, None) if fg else 0
    me = ctypes.windll.kernel32.GetCurrentThreadId()
    attached = bool(fg_thread and fg_thread != me and u.AttachThreadInput(fg_thread, me, True))
    try:
        u.ShowWindow(hwnd, 5)                 # SW_SHOW
        u.BringWindowToTop(hwnd)
        u.SetForegroundWindow(hwnd)
    finally:
        if attached:
            u.AttachThreadInput(fg_thread, me, False)
