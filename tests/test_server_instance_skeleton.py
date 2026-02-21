from pathlib import Path


def test_server_instance_init(tmp_path):
    from src.core.server_instance import ServerInstance

    inst = ServerInstance(id="s1", name="myserver", path=tmp_path)

    assert inst.id == "s1"
    assert inst.name == "myserver"
    assert inst.path == Path(tmp_path)
    assert hasattr(inst, "_lock")
    # 不直接依賴具體實作型別：使用 duck-typing 檢查鎖的行為
    assert hasattr(inst._lock, "acquire")
    assert hasattr(inst._lock, "release")
    assert inst.process is None


def test_server_instance_process_helpers(tmp_path):
    from src.core.server_instance import ServerInstance

    class DummyProcess:
        def poll(self):
            return None

    inst = ServerInstance(id="s3", name="srv3", path=tmp_path)
    process = DummyProcess()

    assert inst.attach_process(process) is process
    assert inst.get_process() is process
    assert inst.is_running() is True

    inst.clear_process()
    assert inst.get_process() is None
    assert inst.is_running() is False


def test_to_dict(tmp_path):
    from src.core.server_instance import ServerInstance

    inst = ServerInstance(id="s2", name="srv", path=tmp_path)
    d = inst.to_dict()
    assert d["id"] == "s2"
    assert d["path"] == str(tmp_path)
