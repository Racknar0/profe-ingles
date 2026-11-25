import ctypes
from ctypes import wintypes
import threading
from pathlib import Path
from typing import Callable

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32

WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_USER = 0x0400
WM_TRAYICON = WM_USER + 20
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205

NIM_ADD = 0x00000000
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
LR_DEFAULTSIZE = 0x00000040
TPM_RETURNCMD = 0x0100
TPM_NONOTIFY = 0x0080
MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
MF_CHECKED = 0x00000008

ID_PRACTICAR = 1001
ID_15M = 1015
ID_30M = 1030
ID_45M = 1045
ID_60M = 1060
ID_SALIR = 1099

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_longlong


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeoutOrVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


class TrayIcon:
    """Ícono nativo en la bandeja del sistema de Windows sin dependencias externas."""

    def __init__(
        self,
        icon_path: Path,
        on_practicar: Callable[[], None],
        on_intervalo: Callable[[int], None],
        get_intervalo: Callable[[], int],
        on_salir: Callable[[], None],
    ) -> None:
        self.icon_path = icon_path
        self.on_practicar = on_practicar
        self.on_intervalo = on_intervalo
        self.get_intervalo = get_intervalo
        self.on_salir = on_salir
        self.hwnd = None
        self.nid = None

    def _mostrar_menu(self, hwnd: int) -> None:
        menu = user32.CreatePopupMenu()
        actual = self.get_intervalo()

        user32.AppendMenuW(menu, MF_STRING, ID_PRACTICAR, "▶ Practicar ahora")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        for mins, cmd_id in [(15, ID_15M), (30, ID_30M), (45, ID_45M), (60, ID_60M)]:
            flags = MF_STRING | (MF_CHECKED if actual == mins else 0)
            user32.AppendMenuW(menu, flags, cmd_id, f"Cada {mins} min")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, ID_SALIR, "Salir")

        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(hwnd)
        cmd = user32.TrackPopupMenu(menu, TPM_RETURNCMD | TPM_NONOTIFY, pt.x, pt.y, 0, hwnd, None)
        user32.DestroyMenu(menu)

        if cmd == ID_PRACTICAR:
            self.on_practicar()
        elif cmd == ID_15M:
            self.on_intervalo(15)
        elif cmd == ID_30M:
            self.on_intervalo(30)
        elif cmd == ID_45M:
            self.on_intervalo(45)
        elif cmd == ID_60M:
            self.on_intervalo(60)
        elif cmd == ID_SALIR:
            self.remover()
            self.on_salir()

    def remover(self) -> None:
        """Elimina el ícono de la bandeja del sistema."""
        if self.nid:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self.nid))
            self.nid = None

    def iniciar(self) -> None:
        """Inicia el bucle de mensajes de la bandeja en un hilo daemon."""

        def _loop() -> None:
            hinst = kernel32.GetModuleHandleW(None)
            cls_name = "ProfeInglesTrayClass"

            def _wnd_proc(hwnd, msg, wparam, lparam):
                if msg == WM_TRAYICON:
                    if lparam == WM_LBUTTONUP:
                        self.on_practicar()
                    elif lparam == WM_RBUTTONUP:
                        self._mostrar_menu(hwnd)
                    return 0
                if msg == WM_DESTROY:
                    self.remover()
                    user32.PostQuitMessage(0)
                    return 0
                return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

            self._cb = WNDPROC(_wnd_proc)
            wc = WNDCLASS()
            wc.lpfnWndProc = self._cb
            wc.hInstance = hinst
            wc.lpszClassName = cls_name
            user32.RegisterClassW(ctypes.byref(wc))

            self.hwnd = user32.CreateWindowExW(
                0, cls_name, "Profe Inglés Tray", 0, 0, 0, 0, 0, None, None, hinst, None
            )

            hicon = user32.LoadImageW(
                None, str(self.icon_path), IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE
            )

            nid = NOTIFYICONDATA()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
            nid.hWnd = self.hwnd
            nid.uID = 1
            nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            nid.uCallbackMessage = WM_TRAYICON
            nid.hIcon = hicon
            nid.szTip = "Profe Inglés — Clic para practicar"
            self.nid = nid
            shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

        threading.Thread(target=_loop, daemon=True).start()
