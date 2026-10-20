"""Application state shared by the UI: the open vfworks frame and its validation issues."""
from __future__ import annotations

from pathlib import Path

from vfbuilder import vfw
from vfbuilder.frame import FrameSession
from vfbuilder.validator import Issue, validate

# section key -> FrameSession attribute holding that section's elements
SECTION_LISTS = {
    "experiments": "experiments",
    "specifications": "specifications",
    "properties": "properties",
    "structures": "model_structures",
    "monitors": "monitors",
}


def nested_elements(element) -> list:
    """Elements edited inside their parent's form."""
    return [*getattr(element, "conditions", ()), *getattr(element, "measurements", ()),
            *getattr(element, "inports", ()), *getattr(element, "outports", ())]


class AppState:
    def __init__(self) -> None:
        vfw.LOADER.start()  # import vfworks in the background while the UI comes up
        self.session: FrameSession | None = None
        self.issues: list[Issue] = []
        self.enums = vfw.enums()
        self.builtin_model_types = vfw.builtin_model_types()

    # -------------------------------------------------------------- frame
    @property
    def dirty(self) -> bool:
        return self.session is not None and self.session.dirty

    def new(self, directory: str | Path, package_name: str, name: str = "") -> None:
        self._replace(FrameSession.new(directory, package_name, name=name))

    def open(self, path: str | Path) -> None:
        self._replace(FrameSession.open(path))

    def close(self) -> None:
        self._replace(None)

    def _replace(self, session: FrameSession | None) -> None:
        if self.session is not None:
            self.session.close()  # an archive's unsaved working copy is discarded here
        self.session = session
        self.revalidate()

    # --------------------------------------------------------- validation
    def revalidate(self) -> None:
        self.issues = validate(self.session) if self.session is not None else []

    def touch(self) -> None:
        """After an edit: the session marks itself dirty; refresh the issues."""
        self.revalidate()

    def issues_for(self, element) -> list[Issue]:
        guids = {element.GUID, *(e.GUID for e in nested_elements(element))}
        return [i for i in self.issues if i.element_id in guids]

    def severity(self, element) -> str | None:
        severities = {i.severity for i in self.issues_for(element)}
        return "error" if "error" in severities else "warning" if severities else None

    def locate(self, guid: str) -> tuple[str, str] | None:
        """``(section key, GUID of the top-level element to select)`` for any element GUID."""
        if self.session is None:
            return None
        for section, attr in SECTION_LISTS.items():
            for element in getattr(self.session, attr):
                if element.GUID == guid or any(e.GUID == guid for e in nested_elements(element)):
                    return section, element.GUID
        return None

    def feature_suggestions(self, exclude=None) -> list[str]:
        """What a specification's feature is likely to be: conditions, measurements, used features."""
        s = self.session
        names = {c.name for e in s.experiments for c in e.conditions}
        names |= {m.name for e in s.experiments for m in e.measurements}
        names |= {sp.feature for sp in s.specifications if sp is not exclude}
        return sorted(n for n in names if n and str(n).strip())
