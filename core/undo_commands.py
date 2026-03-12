from __future__ import annotations


class _Command:
    """Minimal base for undoable commands — no Qt undo machinery, fully isolated from Nuke."""
    def undo(self): pass
    def redo(self): pass
    def id(self): return -1          # -1 = never merge (Qt convention)
    def mergeWith(self, other): return False


class CoffeeBoardUndoStack:
    """Pure-Python undo stack. Completely isolated from Qt/Nuke undo integration."""

    def __init__(self):
        self._history = []   # list of _Command, oldest → newest
        self._future  = []   # list of _Command, most-recent-undone first
        self._limit   = 50
        self.changed_callback = None   # called after push / undo / redo

    def _notify(self):
        if self.changed_callback is not None:
            self.changed_callback()

    def setUndoLimit(self, n: int) -> None:
        self._limit = n

    def push(self, cmd: _Command) -> None:
        cmd.redo()
        # Try to merge into the top of history (same id, same item)
        if self._history:
            top = self._history[-1]
            if top.id() != -1 and top.id() == cmd.id():
                if top.mergeWith(cmd):
                    self._future.clear()
                    self._notify()
                    return
        self._history.append(cmd)
        self._future.clear()
        while len(self._history) > self._limit:
            self._history.pop(0)
        self._notify()

    def undo(self) -> None:
        if self._history:
            cmd = self._history.pop()
            cmd.undo()
            self._future.append(cmd)
            self._notify()

    def redo(self) -> None:
        if self._future:
            cmd = self._future.pop()
            cmd.redo()
            self._history.append(cmd)
            self._notify()


class MoveCommand(_Command):
    ID = 1

    def __init__(self, item, old_pos, new_pos):
        super().__init__()
        self._item, self._old, self._new = item, old_pos, new_pos

    def undo(self): self._item.setPos(self._old)
    def redo(self): self._item.setPos(self._new)
    def id(self): return self.ID

    def mergeWith(self, other):
        if isinstance(other, MoveCommand) and other._item is self._item:
            self._new = other._new
            return True
        return False


class ResizeCommand(_Command):
    def __init__(self, item, old_scale, new_scale, old_pos, new_pos):
        super().__init__()
        self._item = item
        self._old_scale, self._new_scale = old_scale, new_scale
        self._old_pos, self._new_pos = old_pos, new_pos

    def undo(self):
        self._item.resize_item(self._old_scale)
        self._item.setPos(self._old_pos)

    def redo(self):
        self._item.resize_item(self._new_scale)
        self._item.setPos(self._new_pos)


class RotateCommand(_Command):
    def __init__(self, item, old_rot, new_rot):
        super().__init__()
        self._item, self._old, self._new = item, old_rot, new_rot

    def undo(self): self._item.setRotation(self._old)
    def redo(self): self._item.setRotation(self._new)


class AddItemCommand(_Command):
    def __init__(self, canvas, item, item_list):
        super().__init__()
        self._canvas, self._item, self._list = canvas, item, item_list

    def undo(self):
        self._canvas.scene.removeItem(self._item)
        if self._item in self._list:
            self._list.remove(self._item)

    def redo(self):
        self._canvas.scene.addItem(self._item)
        if self._item not in self._list:
            self._list.append(self._item)


class DeleteItemCommand(_Command):
    def __init__(self, canvas, item, item_list):
        super().__init__()
        self._canvas, self._item, self._list = canvas, item, item_list

    def undo(self):
        self._canvas.scene.addItem(self._item)
        if self._item not in self._list:
            self._list.append(self._item)

    def redo(self):
        self._canvas.scene.removeItem(self._item)
        if self._item in self._list:
            self._list.remove(self._item)


class ZOrderCommand(_Command):
    def __init__(self, before: list, after: list) -> None:
        # before / after: list of (item, z_value) for ALL items on board
        self._before = list(before)
        self._after  = list(after)

    def undo(self) -> None:
        for item, z in self._before:
            item.setZValue(z)

    def redo(self) -> None:
        for item, z in self._after:
            item.setZValue(z)


class EditLineEndpointCommand(_Command):
    def __init__(self, item, old_pos, old_dx, old_dy, new_pos, new_dx, new_dy):
        super().__init__()
        self._item = item
        self._old = (old_pos, old_dx, old_dy)
        self._new = (new_pos, new_dx, new_dy)

    def _apply(self, state):
        pos, dx, dy = state
        self._item.setPos(pos)
        self._item._dx = dx
        self._item._dy = dy
        self._item.prepareGeometryChange()
        self._item.update_handles()
        self._item.update()

    def undo(self): self._apply(self._old)
    def redo(self): self._apply(self._new)


class ChangeSettingsCommand(_Command):
    def __init__(self, image_item, old_settings, new_settings):
        super().__init__()
        self._item, self._old, self._new = image_item, old_settings, new_settings

    def _apply(self, s):
        self._item.colorspace   = s['colorspace']
        self._item.exposure     = s['exposure']
        self._item.gamma        = s['gamma']
        self._item.tone_mapping = s['tone_mapping']
        self._item._update_display_transform()

    def undo(self): self._apply(self._old)
    def redo(self): self._apply(self._new)
