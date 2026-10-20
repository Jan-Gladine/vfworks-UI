"""Headless run of the NiceGUI app on a live vfworks frame."""
import pytest
from conftest import build_screw_frame, by_name
from nicegui import ui
from nicegui.testing import user_simulation

from vfbuilder.ui.builder import Builder
from vfbuilder.ui.state import AppState


def make_app(tmp_path, with_frame: bool = True):
    state = AppState()
    if with_frame:
        state._replace(build_screw_frame(tmp_path))
    builders: list[Builder] = []

    def root() -> None:
        builders.append(Builder(state))
        builders[-1].build()

    return state, builders, root


def select_labelled(user, label: str) -> ui.select:
    return next(e for e in user.find(kind=ui.select).elements if e.props.get("label") == label)


async def go(user, builder: Builder, section: str, expect: str) -> None:
    """Switch section and wait until the page shows ``expect`` (the rebuild is asynchronous)."""
    with user.client, builder.page_root:
        builder.go(section)
    await user.should_see(expect)


@pytest.mark.asyncio
async def test_start_page_without_a_frame(tmp_path):
    state, builders, root = make_app(tmp_path, with_frame=False)
    async with user_simulation(root) as user:
        await user.open("/")
        await user.should_see("no validity frame open")
        await user.should_see("New validity frame")
        await user.should_see("loaded in")


@pytest.mark.asyncio
async def test_every_section_renders(tmp_path):
    state, builders, root = make_app(tmp_path)
    async with user_simulation(root) as user:
        await user.open("/")
        builder = builders[0]
        await user.should_see("VF_SCREW")
        expected = {
            "experiments": ["Edit experiment", "Add condition", "Measures property"],
            "specifications": ["Edit specification", "Minimum (valueMin)", "Satisfied by (properties)", "Observed by:"],
            "properties": ["Edit property", "Satisfies (specifications)", "Used by:"],
            "structures": ["Edit model structure", "Model type (loader)", "Mapped to property", "Add outport"],
            "monitors": ["Edit monitor", "Observes (specifications, at least one)", "Create from template..."],
            "overview": ["Validation (1)", "Save as .vf archive", "Write populatePackage.py", "vfworks log"],
            "frame": ["Validity frame", "Not kept by vfworks"],
        }
        for section, texts in expected.items():
            await go(user, builder, section, texts[0])
            for text in texts:
                await user.should_see(text)


@pytest.mark.asyncio
async def test_link_pickers_edit_the_vfworks_objects(tmp_path):
    state, builders, root = make_app(tmp_path)
    s = state.session
    image = by_name(s.properties, "Image")
    trust = by_name(s.properties, "Trust")
    spec = by_name(s.specifications, "ModelTrust")
    async with user_simulation(root) as user:
        await user.open("/")
        builder = builders[0]

        builder.selected["properties"] = image.GUID
        await go(user, builder, "properties", "Edit property")
        picker = select_labelled(user, "Satisfies (specifications)")
        assert picker.options == {sp.GUID: sp.name for sp in s.specifications}
        with user.client:
            picker.set_value([spec.GUID])
        assert image.satisfies == [spec.GUID] and s.dirty

        builder.selected["specifications"] = spec.GUID
        await go(user, builder, "specifications", "Edit specification")
        picker = select_labelled(user, "Satisfied by (properties)")
        assert sorted(picker.value) == sorted([image.GUID, trust.GUID])
        with user.client:
            picker.set_value([image.GUID])
        assert trust.satisfies == [] and image.satisfies == [spec.GUID]

        monitor = by_name(s.monitors, "TrustMonitor")
        builder.selected["monitors"] = monitor.GUID
        await go(user, builder, "monitors", "Edit monitor")
        with user.client:
            select_labelled(user, "Observes (specifications, at least one)").set_value([])
        assert by_name(s.monitors, "TrustMonitor").observes == []  # rebuilt monitor, same GUID
        await user.should_see("A monitor must observe at least one specification")


@pytest.mark.asyncio
async def test_spec_type_switch_rebuilds_and_rerenders(tmp_path):
    state, builders, root = make_app(tmp_path)
    s = state.session
    spec = by_name(s.specifications, "ScrewCount")
    async with user_simulation(root) as user:
        await user.open("/")
        builders[0].selected["specifications"] = spec.GUID
        await go(user, builders[0], "specifications", "Edit specification")
        await user.should_not_see("Granularity (number of bins)")
        with user.client:
            select_labelled(user, "Type").set_value("property_range")
        new = by_name(s.specifications, "ScrewCount")
        assert new.GUID == spec.GUID and new.type == "property_range" and new.evaluationType == "property_range"
        await user.should_see("Granularity (number of bins)")
        with user.client:
            select_labelled(user, "Type").set_value("property_custom")
        await user.should_see("A custom specification has no values")


@pytest.mark.asyncio
async def test_file_browser_caps_large_folders_and_filters(tmp_path):
    from nicegui import background_tasks

    from vfbuilder.ui.filebrowser import MAX_ENTRIES, browse

    big = tmp_path / "big"
    big.mkdir()
    for i in range(MAX_ENTRIES + 50):
        (big / f"file_{i:04d}.vf").write_text("")
    (big / "wanted_package").mkdir()
    state, builders, root = make_app(tmp_path, with_frame=False)
    async with user_simulation(root) as user:
        await user.open("/")
        async def open_browser() -> None:
            with builders[0].page_root:  # NiceGUI's element context is per task
                await browse("Pick", big, mode="any", extensions=(".vf",))

        with user.client:
            background_tasks.create(open_browser())
        await user.should_see("51 more entries not shown")
        await user.should_see("wanted_package")  # folders come first
        user.find(kind=ui.input, marker=None, content="Filter by name").type("0349")
        await user.should_see("file_0349.vf")
        await user.should_not_see("more entries not shown")
