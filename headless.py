"""Run the blenderwright server in headless Blender so the MCP can drive it.

    blender -b [scene.blend] --python headless.py [-- --port 9876]

Background mode has no event loop, so the addon's bpy.app.timers queue pump
never fires. This script pumps the queue itself on the main thread.
"""

import sys
import time

import addon_utils

MOD = "bl_ext.user_default.blenderwright"

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
port = int(argv[argv.index("--port") + 1]) if "--port" in argv else 9876

addon_utils.enable(MOD, default_set=False)  # already on from prefs; makes sure under --factory-startup
server = sys.modules[MOD + ".server"]
thread_safety = sys.modules[MOD + ".thread_safety"]

server.start_server(port=port)
print(f"blenderwright headless server on 127.0.0.1:{port} (Ctrl+C to quit)", flush=True)
try:
    while True:
        thread_safety._process_queue()
        time.sleep(0.01)
except KeyboardInterrupt:
    server.stop_server()
