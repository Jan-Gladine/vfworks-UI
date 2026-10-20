"""Overview graph: the frame's links as Mermaid flowchart source.

Ports -> properties -> specifications -> monitors, one column per element type, so an
element without edges (an unmapped port, an unobserved specification) stands out.
"""
from __future__ import annotations

from typing import Callable

from vfbuilder.frame import FrameSession


def node_id(guid: str) -> str:
    return "n" + guid.replace("-", "")


def element_id_of(node: str) -> str | None:
    """Inverse of ``node_id``; Mermaid may wrap the id as ``flowchart-<id>-<n>``."""
    for part in node.split("-"):
        if len(part) == 33 and part.startswith("n"):
            h = part[1:]
            return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"
    return None


def _label(text: str) -> str:
    text = (text or "").strip() or "(unnamed)"
    return text.replace("&", "#amp;").replace('"', "#quot;").replace("<", "#lt;").replace(">", "#gt;")


def mermaid_source(session: FrameSession, severity: Callable[[object], str | None]) -> str:
    """``severity(element)`` returns "error", "warning" or None and drives the highlighting."""
    lines = ["flowchart LR"]
    flagged: dict[str, list[str]] = {"error": [], "warning": []}

    def node(element, title: str, open_: str, close: str, subtitle: str = "") -> str:
        text = _label(title) + (f"<br/><small>{_label(subtitle)}</small>" if (subtitle or "").strip() else "")
        level = severity(element)
        if level in flagged:
            flagged[level].append(node_id(element.GUID))
        return f'    {node_id(element.GUID)}{open_}"{text}"{close}'

    def group(key: str, title: str, members: list[str]) -> None:
        if members:
            lines.extend([f"  subgraph {key}[{title}]", "    direction TB", *members, "  end"])

    ports = [node(p, f"{ms.name}: {p.name} ({d})", "([", "])")
             for ms in session.model_structures for d, ps in (("in", ms.inports), ("out", ms.outports)) for p in ps]
    group("ports", "Model structure ports", ports)
    group("properties", "Properties", [
        node(p, p.name, "[", "]", "influence factor" if session.is_influence_factor(p) else "PoI")
        for p in session.properties])
    group("specifications", "Specifications", [node(s, s.name, "{{", "}}", s.feature) for s in session.specifications])
    group("monitors", "Monitors", [node(m, m.name, "[[", "]]") for m in session.monitors])

    property_guids = {p.GUID for p in session.properties}
    spec_guids = {s.GUID for s in session.specifications}
    for ms in session.model_structures:
        for port in (*ms.inports, *ms.outports):
            if port.mapping in property_guids:
                lines.append(f"  {node_id(port.GUID)} --> {node_id(port.mapping)}")
    for prop in session.properties:
        for guid in prop.satisfies or []:
            if guid in spec_guids:
                lines.append(f"  {node_id(prop.GUID)} -->|satisfies| {node_id(guid)}")
    for mon in session.monitors:
        for spec in mon.observes or []:
            if spec.GUID in spec_guids:
                lines.append(f"  {node_id(spec.GUID)} -->|observed by| {node_id(mon.GUID)}")

    lines.append("  classDef error stroke:#c10015,stroke-width:3px,fill:#fde7e9,color:#000")
    lines.append("  classDef warning stroke:#e08a00,stroke-width:3px,fill:#fff4d6,color:#000")
    for level, nodes in flagged.items():
        if nodes:
            lines.append(f"  class {','.join(nodes)} {level}")
    return "\n".join(lines)
