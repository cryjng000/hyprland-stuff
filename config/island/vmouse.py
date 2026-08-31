"""A virtual mouse on /dev/uinput -- real events through libinput, not synthetic
GDK ones, so the compositor path under test is the same one a hand exercises."""
import os, fcntl, struct, time

EV_SYN, EV_KEY, EV_REL = 0, 1, 2
SYN_REPORT, REL_X, REL_Y, BTN_LEFT = 0, 0, 1, 0x110
UI_DEV_CREATE, UI_DEV_DESTROY = 0x5501, 0x5502
UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_RELBIT = 0x40045564, 0x40045565, 0x40045566


class VMouse:
    def __init__(self, name=b"island-drag-probe"):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        for ev in (EV_KEY, EV_REL):
            fcntl.ioctl(self.fd, UI_SET_EVBIT, ev)
        fcntl.ioctl(self.fd, UI_SET_KEYBIT, BTN_LEFT)
        for r in (REL_X, REL_Y):
            fcntl.ioctl(self.fd, UI_SET_RELBIT, r)
        dev = name.ljust(80, b"\0") + struct.pack("HHHH", 3, 0x1234, 0x5678, 1) \
            + struct.pack("i", 0) + b"\0" * (4 * 64 * 4)
        os.write(self.fd, dev)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        time.sleep(0.6)          # let libinput/Hyprland notice the new device

    def _ev(self, typ, code, val):
        os.write(self.fd, struct.pack("llHHi", 0, 0, typ, code, val))

    def move(self, dx, dy):
        if dx:
            self._ev(EV_REL, REL_X, int(dx))
        if dy:
            self._ev(EV_REL, REL_Y, int(dy))
        self._ev(EV_SYN, SYN_REPORT, 0)

    def button(self, down):
        self._ev(EV_KEY, BTN_LEFT, 1 if down else 0)
        self._ev(EV_SYN, SYN_REPORT, 0)

    def close(self):
        fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        os.close(self.fd)
