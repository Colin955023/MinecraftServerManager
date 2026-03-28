from pathlib import Path
import threading


def test_server_instance_init(tmp_path):
    from src.core.server_instance import ServerInstance

    inst = ServerInstance(id="s1", name="myserver", path=tmp_path)

    assert inst.id == "s1"
    assert inst.name == "myserver"
    assert inst.path == Path(tmp_path)
    assert hasattr(inst, "_lock")
    assert isinstance(inst._lock, threading.RLock)
    assert inst.process is None


def test_to_dict(tmp_path):
    from src.core.server_instance import ServerInstance

    inst = ServerInstance(id="s2", name="srv", path=tmp_path)
    d = inst.to_dict()
    assert d["id"] == "s2"
    assert d["path"] == str(tmp_path)
