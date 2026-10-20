# vfbuilder

A GUI for authoring [vfWorks](https://vfworks.readthedocs.io) validity frames. It replaces the
hand-written `populatePackage.py`: you fill in forms and pick links from lists instead of typing
names. vfbuilder works directly on a live vfWorks `ValidityFrame`: creating, opening and saving a
frame are vfWorks calls, and the package on disk is a normal vfWorks package (directory or `.vf`
archive) with no vfbuilder files in it.

## Install

Python 3.11 or newer. vfWorks pulls in torch, ultralytics and pycaret, so the first install is
large.

With [uv](https://docs.astral.sh/uv/) (recommended; the repository pins the pycaret pre-release
that vfWorks depends on):

```bash
uv sync
```

With pip:

```bash
pip install .
```

## Run

```bash
uv run vfbuilder
```

This starts a local server on `http://localhost:8642` and opens it in your browser. Stop it with
Ctrl+C in the terminal. vfWorks is imported in the background when the app starts, which takes 10
to 25 seconds; New and Open become available when it is done.

```text
vfbuilder [package] [--port PORT] [--no-browser]
```

`package` is a package directory or `.vf` archive to open right away.

## Using it

- **New** asks for a directory and a package name and calls `ValidityFrame(...)`. vfWorks creates
  the package folder, its subfolders and templates immediately.
- **Open** picks a package directory or `.vf` archive and calls
  `ValidityFrame(..., loadExistingVF=True)`. An archive is unzipped by vfWorks into a temporary
  working copy.
- **Save** calls the frame's `export()`, which rewrites the package's JSON files (and re-zips an
  archive). Saving is allowed while there are validation errors; you get a warning.
- **Save as .vf archive** (Overview / Save page) calls `zip()`, which saves and writes `<package>.vf`
  next to the package folder.
- **Close** calls `close()`. Unsaved changes are discarded after a confirmation.

The left navigation has one section per element type. Each section shows a table of elements and
an edit form for the selected one. Elements are added with vfWorks' own methods (`addSpecification`,
`addProperty`, `addMonitor`, `addCondition`, `add_inport`, ...) and edited through their property
setters. Validation runs on every change: issues appear above the form, as icons in the tables and
navigation, and as a count in the header.

`Feature` on a specification is the data key it is evaluated against (not the property name). It
autocompletes from condition names, measurement names and features already in use.

### Links

Links are vfWorks' own: a property's `satisfies` (specification GUIDs), a port's mapping and a
measurement's `poi` (property GUIDs), and a monitor's `observes` (specification objects). Every link
is chosen from a picker that lists elements by name, so renaming never breaks a link. Each picker has
a "New ..." button that creates the other element in a dialog and links it without leaving the form.

- Property to specification can be edited from both ends ("Satisfies" on the property, "Satisfied
  by" on the specification); both edit the same `satisfies` list.
- Monitor to specification is edited on the monitor ("Observes"); the specification shows
  "Observed by" and can create a new monitor that observes it.
- Deleting an element asks for confirmation, lists what refers to it, and removes those links.

Some edits cannot be made through vfWorks' setters, because vfWorks fixes them when the object is
constructed: a specification's type, a property's kind (property of interest or influence factor),
and a monitor's observed specifications, monitor time and code file. vfbuilder rebuilds those
objects with the vfWorks constructor, keeps their GUID and timestamp, and swaps them in.

### Files inside the package

- **Monitor code**: "Create from template..." copies vfWorks' `custom_monitor_example.py` to a new
  file in `Resources/monitors/` and selects it. The file must define
  `validate(monitor=None, **kwargs)` returning `{feature: bool}`. A monitor that observes a custom
  specification requires one. vfWorks imports this file whenever the monitor is added or rebuilt,
  so its code runs inside vfbuilder.
- **Model type**: the built-in loaders (`pycaret`, `YOLO`, `torch`) plus every
  `Resources/loaders/<type>.py`. "New loader..." creates one from vfWorks' template.
- **Model reference**: "Browse..." picks a file or folder. Paths inside the package are stored
  relative to it; vfWorks resolves relative references inside the package, by default under
  `Sources/`.

**Write populatePackage.py** (Overview / Save page) writes an equivalent vfWorks script next to the
package, for when you want to continue by hand.

## What vfWorks does not keep

These are vfWorks limitations (bugs to be fixed in vfWorks), not vfbuilder settings. After saving
and reopening a package:

- every property is a property of interest again; the package does not record influence factors;
- the frame's own name and description are gone (the package name stands in for them);
- a model structure's description is reset to vfWorks' default `tbd`;
- a specification's internal value object gets a new GUID (nothing links to it).

Opening a package also has side effects that are vfWorks' doing: the loader appends to the
package's log file (`Resources/VF_BLDC.log`) and adds any missing skeleton files and templates.

vfbuilder works around three vfWorks bugs that would otherwise break editing; vfWorks itself is not
modified:

- `Operational` uses mutable default arguments, so every `ValidityFrame` in a process shares its
  model structures and monitors with the frames built before it. vfbuilder gives each frame its own
  lists right after constructing it.
- Reloading gives every experiment condition its experiment's GUID. vfbuilder restores the stored
  condition GUIDs from `Experiments.json`.
- Reloaded specifications have no evaluation type, so monitors built later miss custom
  specifications. vfbuilder rebuilds them with the vfWorks constructor after loading.

## What validation checks

Errors:

- missing names; names not unique across specifications, properties and monitors together, or
  within any other element type
- specification without a feature, a type unknown to the installed vfWorks, or non-numeric values;
  range with min >= max; granularity that is not a whole number >= 1
- monitor that observes no specification, or observes a custom specification without a code file
- links to elements that do not exist; enum values unknown to the installed vfWorks

Warnings:

- specification not satisfied by any property, or not observed by any monitor
- two specifications observed by one monitor share a feature (their status collides)
- port not mapped to a property; property or port with min > max
- measurements with the same name measuring different properties
- custom code file or model loader not found in the package; no model type or model reference

## Not covered yet

Processes/workflows, remote experiments, Neo4j export, running monitors, loading models and the
specification DSL.

## Development

```bash
uv run pytest    # about 30 s, most of it importing vfWorks once
```

| Module | Role |
| --- | --- |
| `vfw.py` | imports vfWorks in the background; constants catalog; frame construction (shared-list workaround) |
| `frame.py` | `FrameSession`: the live `ValidityFrame`, with lookup by GUID, add/edit/delete and rebuilds |
| `validator.py` | checks a live frame and returns issues keyed by GUID |
| `package_files.py` | monitor code files and model loaders in the package folder |
| `script.py` | renders the open frame as `populatePackage.py` |
| `graph.py` | Mermaid source for the overview graph |
| `ui/` | the NiceGUI app |
