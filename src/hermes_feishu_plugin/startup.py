"""Hermes Feishu plugin startup hook."""
import sys

# Write trace directly to stderr (not buffered)
sys.__stderr__.write("[HERMES_FEISHU_STARTUP] v2 startup loading...\n")
sys.__stderr__.flush()

try:
    from .channel.patches import apply_runtime_patches
    from .core.sibling_bootstrap import sync_optional_plugins
    
    sys.__stderr__.write("[HERMES_FEISHU_STARTUP] applying patches...\n")
    sys.__stderr__.flush()
    result = apply_runtime_patches(plugin_name="hermes_feishu_plugin_startup")
    sys.__stderr__.write(f"[HERMES_FEISHU_STARTUP] patches applied: {list(result.get('patched', {}).keys())}\n")
    sys.__stderr__.flush()
    sync_optional_plugins()
    sys.__stderr__.write("[HERMES_FEISHU_STARTUP] startup complete\n")
    sys.__stderr__.flush()
except Exception as exc:
    import traceback
    sys.__stderr__.write(f"[HERMES_FEISHU_STARTUP] FAILED: {exc}\n{traceback.format_exc()}\n")
    sys.__stderr__.flush()
