try:
    import nuke, nukescripts
    nukescripts.panels.registerWidgetAsPanel(
        '__import__("CoffeeBoard.core.canvas", fromlist=["CoffeeBoard"]).CoffeeBoard',
        'Coffee Board', 'com.coffeeveinstudio.CoffeeBoard'
    )

    def _get_coffeeboard_canvas():
        """Return the live CoffeeBoard canvas widget, or None if not open."""
        try:
            try:
                from PySide2.QtWidgets import QApplication
            except ImportError:
                from PySide6.QtWidgets import QApplication
            from CoffeeBoard.core.canvas import CoffeeBoard as _CB
            for w in QApplication.instance().allWidgets():
                if isinstance(w, _CB):
                    return w
        except Exception:
            pass
        return None

    def _smart_undo():
        canvas = _get_coffeeboard_canvas()
        if canvas and canvas.viewport().underMouse():
            canvas.undo_stack.undo()
        else:
            nuke.undo()

    def _smart_redo():
        canvas = _get_coffeeboard_canvas()
        if canvas and canvas.viewport().underMouse():
            canvas.undo_stack.redo()
        else:
            nuke.redo()

    def _smart_save():
        canvas = _get_coffeeboard_canvas()
        if canvas and canvas.viewport().underMouse():
            canvas.save_board()
        else:
            nuke.scriptSave()

    def _smart_open():
        canvas = _get_coffeeboard_canvas()
        if canvas and canvas.viewport().underMouse():
            canvas.load_board()
        else:
            nuke.scriptOpen()

    nuke.menu('Nuke').addCommand('Edit/Undo', _smart_undo, 'ctrl+z')
    nuke.menu('Nuke').addCommand('Edit/Redo', _smart_redo, 'ctrl+y')
    nuke.menu('Nuke').addCommand('Edit/CoffeeBoard Redo', _smart_redo, 'ctrl+shift+z')
    nuke.menu('Nuke').addCommand('File/Save Script', _smart_save, 'ctrl+s')
    nuke.menu('Nuke').addCommand('File/Open Script', _smart_open, 'ctrl+o')
    print('[CoffeeBoard] Panel and smart undo/redo/save/open registered')

except ImportError:
    pass
