from api.__main__ import load_env_file


def test_env_file_loads_without_overriding(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# comment\nEWS_T_A=one\nexport EWS_T_B="two words"\nEWS_T_C=\nEWS_T_D=from-file\nnot a setting\n',
                   encoding="utf-8")
    for key in ("EWS_T_A", "EWS_T_B", "EWS_T_C"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("EWS_T_D", "from-environment")
    loaded = load_env_file(env)
    import os
    assert os.environ["EWS_T_A"] == "one" and os.environ["EWS_T_B"] == "two words"
    assert "EWS_T_C" not in os.environ                      # empty values are skipped
    assert os.environ["EWS_T_D"] == "from-environment"      # real environment wins
    assert sorted(loaded) == ["EWS_T_A", "EWS_T_B"]
    for key in loaded:
        monkeypatch.delenv(key)


def test_missing_env_file_is_fine(tmp_path):
    assert load_env_file(tmp_path / "nope.env") == []
