from __future__ import annotations

import random
from pathlib import Path

from config import (
    BROWSER_ARGS,
    BUSTER_EXTENSION_DIR,
    DEVICE_POOL,
    USE_CHROME_CHANNEL,
)
from core.log_bus import LOG_BUS
from core.profile_manager import launch_with_profile_guard


STEALTH_INIT_SCRIPT = """
(() => {
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

  const patchCanvas = (proto) => {
    const orig = proto.toDataURL;
    proto.toDataURL = function(type, ...args) {
      const ctx = this.getContext('2d');
      if (ctx) {
        const shift = Math.floor(Math.random() * 10) + 1;
        ctx.fillStyle = 'rgba(' + shift + ',' + shift + ',' + shift + ',0.01)';
        ctx.fillRect(0, 0, 1, 1);
      }
      return orig.apply(this, [type, ...args]);
    };
  };
  if (typeof HTMLCanvasElement !== 'undefined') {
    patchCanvas(HTMLCanvasElement.prototype);
  }

  const getParam = WebGLRenderingContext.prototype.getParameter;
  WebGLRenderingContext.prototype.getParameter = function(p) {
    if (p === 37445) return 'Intel Inc.';
    if (p === 37446) return 'Intel Iris OpenGL Engine';
    return getParam.call(this, p);
  };

  window.chrome = { runtime: {} };
  Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
  });
  Object.defineProperty(navigator, 'languages', {
    get: () => ['tr-TR', 'tr', 'en-US', 'en'],
  });
})();
"""


def pick_device(*, desktop_only: bool = False) -> dict:
    if desktop_only:
        return DEVICE_POOL[-1]
    return random.choice(DEVICE_POOL)


def buster_extension_loaded() -> bool:
    return (BUSTER_EXTENSION_DIR / "manifest.json").is_file()


def _extension_launch_args(*, enable: bool) -> list[str]:
    """Buster yalnizca gorunur modda (giris/kayit/soru); headless hitlerde yuklenmez."""
    if not enable or not buster_extension_loaded():
        return []
    ext = str(BUSTER_EXTENSION_DIR.resolve())
    return [
        f"--disable-extensions-except={ext}",
        f"--load-extension={ext}",
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
    ]


async def launch_persistent_context(
    playwright,
    profile_path: str,
    *,
    headless: bool,
    proxy: str = "",
    bot_id: int = 0,
    desktop_only: bool = False,
    enable_buster: bool | None = None,
):
    device = pick_device(desktop_only=desktop_only)
    proxy_cfg = None
    if proxy.strip():
        proxy_cfg = {"server": proxy.strip()}

    profile_dir = str(Path(profile_path).resolve())
    Path(profile_dir).mkdir(parents=True, exist_ok=True)

    if enable_buster is None:
        enable_buster = not headless
    ext_args = _extension_launch_args(enable=enable_buster)
    if ext_args and bot_id >= 0:
        LOG_BUS.emit("INFO", bot_id, "Buster extension yuklu (ucretsiz captcha)")

    launch_args = (
        BROWSER_ARGS
        + ext_args
        + [f"--window-size={device['viewport']['width']},{device['viewport']['height']}"]
    )

    async def _launch():
        kwargs = dict(
            user_data_dir=profile_dir,
            headless=headless,
            args=launch_args,
            user_agent=device["user_agent"],
            viewport=device["viewport"],
            locale="tr-TR",
            timezone_id="Europe/Istanbul",
            is_mobile=device.get("is_mobile", False),
            has_touch=device.get("is_mobile", False),
            ignore_default_args=["--enable-automation"],
            proxy=proxy_cfg,
        )
        if USE_CHROME_CHANNEL:
            try:
                ctx = await playwright.chromium.launch_persistent_context(
                    channel="chrome",
                    **kwargs,
                )
                await ctx.add_init_script(STEALTH_INIT_SCRIPT)
                return ctx
            except Exception:
                pass
        ctx = await playwright.chromium.launch_persistent_context(**kwargs)
        await ctx.add_init_script(STEALTH_INIT_SCRIPT)
        return ctx

    ctx = await launch_with_profile_guard(profile_dir, bot_id, _launch)
    return ctx, device
