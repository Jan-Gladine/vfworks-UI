"""Record docs/walkthrough.gif: a Playwright walkthrough that adds one forklift requirement to a new frame.

It rebuilds REQ_13 (ShadowRecall) of the SAIfety forklift validity frame (VF_FORKLIFT) step by
step: the specification, the property it is measured on, the shadow ODD condition as an influence
factor, a validation experiment, a monitor with its own code file, the model structure, and the
overview.

Start vfbuilder first (``uv run vfbuilder --no-browser``), then run:

    uv run --with playwright python scripts/record_walkthrough.py [--url http://localhost:8642]

The script drives the GUI the way a user would (a drawn cursor shows each click), creates the
package ``VF_FORKLIFT_REQ13`` in the server's working directory (``--workdir``), saves it, closes it
and deletes it again. It uses the installed Microsoft Edge (``--channel chrome`` for Chrome), so no Playwright
browser download is needed.
"""
from __future__ import annotations

import argparse
import io
import shutil
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import Locator, Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "VF_FORKLIFT_REQ13"
VIEWPORT = {"width": 1280, "height": 820}
GIF_WIDTH = 960
CAPTION_HEIGHT = 46


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("segoeuib.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


FONT = _font(19)

OVERLAY_JS = """
() => {
  if (document.getElementById('wt-cursor')) return;
  const cursor = document.createElement('div');
  cursor.id = 'wt-cursor';
  cursor.innerHTML = `<svg width="26" height="26" viewBox="0 0 24 24"><path d="M4 2 L4 20 L9 15 L12.5 22 L15.5 20.5 L12 13.5 L19 13.5 Z"
     fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
  Object.assign(cursor.style, {position: 'fixed', left: '640px', top: '380px', zIndex: 100000,
    pointerEvents: 'none', transform: 'translate(-4px,-2px)'});
  const ring = document.createElement('div');
  ring.id = 'wt-ring';
  Object.assign(ring.style, {position: 'fixed', width: '34px', height: '34px', borderRadius: '50%',
    border: '3px solid #f59e0b', background: 'rgba(245,158,11,.25)', zIndex: 99999,
    pointerEvents: 'none', transform: 'translate(-50%,-50%)', display: 'none'});
  document.body.append(ring, cursor);
}
"""


class Recorder:
    """Drives the page with a visible cursor and collects GIF frames."""

    def __init__(self, page: Page) -> None:
        self.page = page
        self.frames: list[tuple[Image.Image, int]] = []
        self.x, self.y = 640.0, 380.0
        self.text = ""

    # ------------------------------------------------------------- frames
    def snap(self, ms: int = 120) -> None:
        self.page.evaluate(OVERLAY_JS)
        image = Image.open(io.BytesIO(self.page.screenshot())).convert("RGB")
        height = round(image.height * GIF_WIDTH / image.width)
        frame = Image.new("RGB", (GIF_WIDTH, height + CAPTION_HEIGHT), (17, 24, 39))
        frame.paste(image.resize((GIF_WIDTH, height), Image.LANCZOS), (0, 0))
        if self.text:
            ImageDraw.Draw(frame).text((GIF_WIDTH / 2, height + CAPTION_HEIGHT / 2), self.text, font=FONT,
                                       fill="white", anchor="mm")
        self.frames.append((frame, ms))

    def hold(self, ms: int) -> None:
        """Let the page settle, then show the current state for ``ms``."""
        self.page.wait_for_timeout(250)
        self.snap(ms)

    def caption(self, text: str, ms: int = 1600) -> None:
        self.text = text
        if ms:
            self.hold(ms)

    # -------------------------------------------------------------- input
    def _place(self, x: float, y: float, ring: bool = False) -> None:
        self.page.evaluate(
            """([x, y, ring]) => {
                 const c = document.getElementById('wt-cursor'); c.style.left = x + 'px'; c.style.top = y + 'px';
                 const r = document.getElementById('wt-ring'); r.style.left = x + 'px'; r.style.top = y + 'px';
                 r.style.display = ring ? 'block' : 'none'; }""", [x, y, ring])

    def move_to(self, target: Locator) -> tuple[float, float]:
        target.scroll_into_view_if_needed()
        box = target.bounding_box()
        assert box is not None, f"not visible: {target}"
        x, y = box["x"] + min(box["width"] / 2, 60), box["y"] + box["height"] / 2
        self.page.evaluate(OVERLAY_JS)
        steps = 7
        for i in range(1, steps + 1):
            t = i / steps
            t = t * t * (3 - 2 * t)  # ease in/out
            self._place(self.x + (x - self.x) * t, self.y + (y - self.y) * t)
            self.snap(40)
        self.x, self.y = x, y
        return x, y

    def click(self, target: Locator, settle_ms: int = 500) -> None:
        x, y = self.move_to(target)
        self._place(x, y, ring=True)
        self.snap(180)
        self.page.mouse.click(x, y)
        self.page.wait_for_timeout(settle_ms)
        self._place(x, y, ring=False)
        self.snap(250)

    def type(self, target: Locator, text: str, replace: bool = False, chunk: int = 2) -> None:
        self.click(target, settle_ms=150)
        if replace:
            self.page.keyboard.press("Control+A")
        for i in range(0, len(text), chunk):
            target.press_sequentially(text[i:i + chunk])
            self.snap(70)
        self.page.wait_for_timeout(300)
        self.snap(300)

    def section(self, title: str) -> None:
        """Switch to a section in the navigation drawer and scroll the page back to the top."""
        self.click(self.page.locator(".q-drawer .q-item").filter(has_text=title), settle_ms=700)
        self.page.evaluate("window.scrollTo(0, 0)")
        self.page.wait_for_timeout(300)

    def choose(self, select: Locator, option: str) -> None:
        """Open a Quasar select and pick the option whose label contains ``option``."""
        self.click(select, settle_ms=400)
        self.click(self.page.locator(".q-menu .q-item").filter(has_text=option).first, settle_ms=400)


def card(page: Page, title: str) -> Locator:
    return page.locator(".q-card").filter(has=page.get_by_text(title, exact=True)).last


def field(scope: Locator, label: str) -> Locator:
    return scope.get_by_label(label, exact=True).first


def dialog(page: Page) -> Locator:
    return page.locator(".q-dialog .q-card").last


REQ_13 = "REQ_13: Pedestrian recall shall be >= 95% under the WarehouseODD.shadow condition"
MONITOR_CODE = [
    '"""REQ_13: pedestrian recall under the WarehouseODD.shadow condition."""\n',
    "\n",
    "\n",
    "def validate(monitor=None, **kwargs):\n",
    '    data_vector = kwargs.get("data_vector", kwargs)\n',
    "    # only results measured with shadow present count for REQ_13\n",
    '    if data_vector.get("Shadow") != "Present":\n',
    "        return {}  # features left out fall back to the built-in check\n",
    '    recall = data_vector.get("pedestrian_recall", 0.0)\n',
    '    return {"pedestrian_recall": recall >= 0.95}\n',
]


# [text, replace]: append text to the code editor (or replace its content); text None returns the content
CM_JS = """([text, replace]) => {
  const view = document.querySelector('.cm-content').cmView.view;
  if (text === null) return view.state.doc.toString();
  const from = replace ? 0 : view.state.doc.length;
  view.dispatch({changes: {from, to: view.state.doc.length, insert: text},
                 selection: {anchor: from + text.length}, scrollIntoView: true});
  view.focus();
}"""


def walkthrough(r: Recorder, page: Page) -> None:
    """Rebuild requirement REQ_13 (ShadowRecall) of the SAIfety forklift validity frame."""
    expect(page.get_by_text("loaded in")).to_be_visible(timeout=90_000)
    r.caption("Rebuilding REQ_13 (ShadowRecall) of the forklift validity frame in vfbuilder", 2800)

    # a new frame
    r.caption("1 · New validity frame: vfWorks creates the package on disk right away", 900)
    r.click(page.get_by_role("button", name="New validity frame"))
    d = dialog(page)
    r.type(field(d, "Package name (folder)"), PACKAGE)
    r.type(field(d, "Frame name (optional; vfworks does not save it)"), "Forklift pedestrian detection", chunk=4)
    r.click(d.get_by_role("button", name="Create"), settle_ms=600)
    expect(page.get_by_text("Validity frame", exact=True)).to_be_visible(timeout=60_000)
    r.hold(1200)

    # the specification
    r.caption("2 · Specification ShadowRecall: recall >= 0.95 on the feature pedestrian_recall", 900)
    r.section("Specifications")
    r.click(page.get_by_role("button", name="Add specification"), settle_ms=700)
    r.hold(1400)
    form = card(page, "Edit specification")
    r.type(field(form, "Name"), "ShadowRecall")
    r.type(field(form, "Description"), REQ_13, chunk=6)
    r.type(field(form, "Feature (data key the specification is evaluated against)"), "pedestrian_recall", chunk=3)
    r.choose(field(form, "Type"), "property_min")
    form = card(page, "Edit specification")
    r.type(field(form, "Minimum (valueMin)"), "0.95", replace=True)
    r.caption("Live validation: no errors left; the warnings say what REQ_13 still needs", 2400)

    # the property it is measured on, created and linked from the specification
    r.caption("3 · Property PedestrianRecall satisfies it, created without leaving the form", 900)
    r.click(form.get_by_role("button", name="New property..."))
    d = dialog(page)
    r.type(field(d, "Name"), "PedestrianRecall")
    r.type(field(d, "Description"), "Pedestrian detection recall", chunk=4)
    r.click(d.get_by_role("button", name="Create and link"), settle_ms=700)
    r.hold(1600)

    r.caption("3 · Recall is a fraction: give the property the range 0..1", 900)
    r.section("Properties")
    form = card(page, "Edit property")
    expect(field(form, "Name")).to_have_value("PedestrianRecall")
    r.type(field(form, "Max"), "1", replace=True)
    r.hold(1600)

    # the ODD condition as an influence factor
    r.caption("4 · The ODD condition 'shadow' becomes the influence factor Shadow", 900)
    r.click(page.get_by_role("button", name="Add property"), settle_ms=700)
    form = card(page, "Edit property")
    r.type(field(form, "Name"), "Shadow")
    r.type(field(form, "Description"), "Shadow state: Absent or Present", chunk=4)
    r.click(form.get_by_role("button", name="Influence factor"), settle_ms=700)
    r.hold(1800)

    # the experiment that provides the evidence
    r.caption("5 · Experiment: validation recordings with Shadow = Present measure the recall", 900)
    r.section("Experiments")
    r.click(page.get_by_role("button", name="Add experiment"), settle_ms=700)
    form = card(page, "Edit experiment")
    r.type(field(form, "Name"), "ShadowValidation")
    r.type(field(form, "Description"), "Validation recordings with shadows on the warehouse floor", chunk=5)
    r.type(field(form, "Label"), "shadow", replace=True)
    r.click(form.get_by_role("button", name="Add condition"), settle_ms=700)
    form = card(page, "Edit experiment")
    r.type(form.get_by_label("Name", exact=True).nth(1), "Shadow")
    r.type(form.get_by_label("Value", exact=True).first, "Present")
    r.click(form.get_by_role("button", name="Add measurement"), settle_ms=700)
    meas = card(page, "Edit experiment").locator(".q-card").last
    r.type(field(meas, "Name"), "pedestrian_recall", chunk=3)
    r.type(field(meas, "Reference (data file)"), "shadow_validation.yaml", chunk=3)
    r.choose(field(meas, "Measures property"), "PedestrianRecall")
    r.hold(1800)

    # the monitor that checks it, with its own code
    r.caption("6 · Monitor ShadowRecallMonitor checks REQ_13 at model validation time", 900)
    r.section("Monitors")
    r.click(page.get_by_role("button", name="Add monitor"), settle_ms=700)
    form = card(page, "Edit monitor")
    r.type(field(form, "Name"), "ShadowRecallMonitor", chunk=3)
    r.choose(field(form, "Monitor time"), "ModelValidationTime")
    form = card(page, "Edit monitor")
    r.choose(field(form, "Observes (specifications, at least one)"), "ShadowRecall")
    page.keyboard.press("Escape")
    r.hold(1200)
    r.caption("6 · Its code file odd_condition_monitor.py starts from vfWorks' template", 900)
    form = card(page, "Edit monitor")
    r.click(form.get_by_role("button", name="Create from template..."))
    d = dialog(page)
    r.type(field(d, "File name"), "odd_condition_monitor.py", replace=True, chunk=3)
    r.click(d.get_by_role("button", name="OK"), settle_ms=900)
    r.hold(1400)

    r.caption("7 · Write validate() in the built-in Python editor; it is checked as you type", 900)
    r.click(card(page, "Edit monitor").get_by_role("button", name="Edit"), settle_ms=900)
    page.evaluate("window.scrollTo(0, 0)")
    r.hold(2200)
    # Text goes in line by line through CodeMirror's own API: typed keys would trigger its
    # auto-indent and auto-closed quotes, and edits faster than the server round trip are
    # overwritten, so each line is followed by a frame (and the pause that gives).
    r.click(page.locator(".cm-content .cm-line").nth(4), settle_ms=200)
    page.evaluate(CM_JS, ["", True])
    r.snap(300)
    for line in MONITOR_CODE:
        page.evaluate(CM_JS, [line, False])
        page.wait_for_timeout(120)
        r.snap(160)
    page.wait_for_timeout(600)
    assert page.evaluate(CM_JS, [None, False]) == "".join(MONITOR_CODE), "editor text was not entered correctly"
    r.hold(1600)
    r.click(page.get_by_role("button", name="Save").last, settle_ms=800)
    r.hold(1800)

    # the model the requirement is about
    r.caption("8 · The model: YOLO weights, with its detections output mapped to a property", 900)
    r.section("Model structure")
    r.click(page.get_by_role("button", name="Add model structure"), settle_ms=700)
    form = card(page, "Edit model structure")
    r.type(field(form, "Name"), "ForkliftDetectionModel", chunk=3)
    r.choose(field(form, "Model type (loader)"), "YOLO")
    r.type(field(form, "Model reference (file or folder)"), "yolo.pt")
    r.click(form.get_by_role("button", name="Add outport"), settle_ms=700)
    port = card(page, "Edit model structure").locator(".q-card").last
    r.type(field(port, "Name"), "detections")
    r.click(port.get_by_role("button", name="New property..."))
    d = dialog(page)
    r.type(field(d, "Name"), "Detections")
    r.click(d.get_by_role("button", name="Create and link"), settle_ms=700)
    r.hold(1600)

    # overview and save
    r.caption("9 · Overview: Shadow, PedestrianRecall, ShadowRecall and its monitor, all linked", 900)
    r.section("Overview / Save")
    page.wait_for_timeout(1500)
    r.hold(3200)
    r.caption("10 · Save writes the package with vfWorks' export()", 900)
    r.click(page.locator(".q-header").get_by_role("button", name="Save"), settle_ms=900)
    r.caption("REQ_13 is in the package, ready for ValidityFrame(..., loadExistingVF=True)", 3400)


def save_gif(frames: list[tuple[Image.Image, int]], target: Path) -> None:
    # one shared palette keeps the file small and stops colours flickering between frames
    palette = frames[len(frames) // 2][0].quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    images = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f, _ in frames]
    target.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(target, save_all=True, append_images=images[1:], duration=[ms for _, ms in frames],
                   loop=0, optimize=True, disposal=1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:8642")
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "walkthrough.gif")
    parser.add_argument("--channel", default="msedge")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--workdir", type=Path, default=ROOT,
                        help="the server's working directory, where New creates the demo package")
    args = parser.parse_args()

    package = args.workdir / PACKAGE
    if package.exists():
        raise SystemExit(f"{package} exists; remove it first")
    started = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=args.channel, headless=not args.headed)
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
        page.goto(args.url)
        recorder = Recorder(page)
        ok = False
        try:
            walkthrough(recorder, page)
            ok = True
        finally:
            # close the frame so vfworks releases its log file, then remove the demo package
            close = page.locator(".q-header").get_by_role("button", name="Close")
            if close.is_enabled():
                close.click()
                discard = page.get_by_role("button", name="Discard")
                if discard.is_visible(timeout=1500):
                    discard.click()
                page.wait_for_timeout(800)
            browser.close()
    for _ in range(20):  # vfworks releases its log file once the server has closed the frame
        shutil.rmtree(package, ignore_errors=True)
        if not package.exists():
            break
        time.sleep(0.5)
    else:
        print(f"could not remove {package}; delete it by hand")
    if not ok:
        raise SystemExit("walkthrough failed; no GIF written")
    save_gif(recorder.frames, args.out)
    print(f"{len(recorder.frames)} frames -> {args.out} ({args.out.stat().st_size / 1e6:.1f} MB) "
          f"in {time.time() - started:.0f} s")


if __name__ == "__main__":
    main()
