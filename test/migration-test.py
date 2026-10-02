#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import tempfile

script = Path(__file__).resolve().parents[1] / "bin/my-agents-migrate"
plugin_id = "io.github.villenull.opencode-go-watcher"
for source_id in ["villenull.agents", "omarchy.agents", None]:
    with tempfile.TemporaryDirectory() as temporary:
        home = Path(temporary)
        path = home / ".config/omarchy/shell.json"
        path.parent.mkdir(parents=True)
        entries = [{"id": "omarchy.tray"}]
        if source_id:
            entries.append({"id": source_id, "refreshIntervalSec": 60})
        entries.append({"id": "omarchy.power"})
        original = {"bar": {"layout": {"right": entries}}, "plugins": [{"id": plugin_id}, {"id": "other"}]}
        path.write_text(json.dumps(original))
        clone = home / ".config/omarchy/plugins/villenull.agents"
        clone.mkdir(parents=True)
        (clone / "custom.txt").write_text("keep me")
        env = {**os.environ, "HOME": str(home), "XDG_STATE_HOME": str(home / ".local/state")}
        subprocess.run([str(script)], env=env, check=True, capture_output=True)
        value = json.loads(path.read_text())
        right = value["bar"]["layout"]["right"]
        assert sum(e["id"] == plugin_id for e in right) == 1
        assert value["plugins"] == [{"id": "other"}]
        if source_id:
            assert right[1] == {"id": plugin_id, "refreshIntervalSec": 60}
        assert not clone.exists()
        backups = list((home / ".local/state/my-agents-backups").iterdir())
        assert len(backups) == 1
        assert (backups[0] / "villenull.agents/custom.txt").read_text() == "keep me"
        assert json.loads((backups[0] / "shell.json").read_text()) == original
        first = path.read_bytes()
        subprocess.run([str(script)], env=env, check=True, capture_output=True)
        assert path.read_bytes() == first
        assert len(list(backups[0].parent.iterdir())) == 1
print("Migration: custom clone, stock widget, fresh install, backups and repeat runs passed")
