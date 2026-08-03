from pathlib import Path

from src.core.server.server_instance import ServerInstance
from src.core.server.server_startup import ServerStartup


def test_server_instance_init(tmp_path):
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
    inst = ServerInstance(id="s2", name="srv", path=tmp_path)
    d = inst.to_dict()
    assert d["id"] == "s2"
    assert d["path"] == str(tmp_path)


def test_server_startup_reads_buffer_before_stopped_process_cleanup(tmp_path):
    class StoppedProcess:
        pid = 0

        def poll(self):
            return 0

    startup = ServerStartup(str(tmp_path))
    inst = ServerInstance(id="srv", name="srv", path=tmp_path)
    inst.attach_process(StoppedProcess())
    inst.attach_output_buffer(10)
    inst.append_output_line("last line")
    startup.running_servers["srv"] = inst

    assert startup.read_server_output("srv") == ["last line"]
    assert "srv" not in startup.running_servers
