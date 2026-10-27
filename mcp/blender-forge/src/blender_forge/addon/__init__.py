"""blender-forge bridge extension: lets an MCP agent drive Blender through a signed local socket.

Enable it in Edit > Preferences > Get Extensions (installed by `blender-forge-install`).
It starts listening on 127.0.0.1 when Blender opens; the port and token live in
~/.config/blender-forge/bridge.json.
"""
try:
    import bpy
except ImportError:  # the MCP server imports .protocol outside Blender
    bpy = None

from . import protocol

_bridge = None


def _pump():
    if _bridge is not None:
        _bridge.pump()
    return 0.05


def start():
    global _bridge
    if _bridge is not None:
        return _bridge
    from .bridge import Bridge
    _bridge = Bridge(protocol.load_config(create=True)).start()
    if not bpy.app.timers.is_registered(_pump):
        bpy.app.timers.register(_pump, first_interval=0.1, persistent=True)
    print(f"blender-forge: bridge listening on 127.0.0.1:{_bridge.config['port']}")
    return _bridge


def stop():
    global _bridge
    if bpy.app.timers.is_registered(_pump):
        bpy.app.timers.unregister(_pump)
    if _bridge is not None:
        _bridge.stop()
        _bridge = None


if bpy is not None:
    class FORGE_OT_toggle(bpy.types.Operator):
        bl_idname = "blender_forge.toggle"
        bl_label = "Start or stop the blender-forge bridge"

        def execute(self, context):
            if _bridge is None:
                start()
                self.report({"INFO"}, "blender-forge bridge started")
            else:
                stop()
                self.report({"INFO"}, "blender-forge bridge stopped")
            return {"FINISHED"}


    class FORGE_PT_panel(bpy.types.Panel):
        bl_label = "blender-forge"
        bl_space_type = "VIEW_3D"
        bl_region_type = "UI"
        bl_category = "Forge"

        def draw(self, context):
            col = self.layout.column()
            if _bridge is None:
                col.label(text="Bridge stopped", icon="X")
                col.operator(FORGE_OT_toggle.bl_idname, text="Start bridge")
            else:
                col.label(text=f"Listening on 127.0.0.1:{_bridge.config['port']}", icon="CHECKMARK")
                col.label(text="Python: " + ("enabled" if "run_python" in _bridge.allowed else "disabled"))
                col.operator(FORGE_OT_toggle.bl_idname, text="Stop bridge")


    CLASSES = (FORGE_OT_toggle, FORGE_PT_panel)


    def register():
        for cls in CLASSES:
            bpy.utils.register_class(cls)
        if not bpy.app.background:
            try:
                start()
            except OSError as exc:  # port taken by another Blender: keep the panel, let the user retry
                print(f"blender-forge: bridge not started ({exc})")


    def unregister():
        stop()
        for cls in reversed(CLASSES):
            bpy.utils.unregister_class(cls)
