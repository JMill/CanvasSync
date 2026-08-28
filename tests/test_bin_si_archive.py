"""Finding 4 (final review): `si_archive all` must not blindly re-run a
network stage and overwrite a good _build/*.json with whatever a bad
network day returns -- see NETWORK_STAGE_OUTPUT's docstring in
bin/si_archive.py for the failure mode this guards against.
"""
import bin.si_archive as si_archive_bin


def test_network_stage_output_names_elucidat_and_vimeo_only():
    assert si_archive_bin.NETWORK_STAGE_OUTPUT == {
        "elucidat": "elucidat.json", "vimeo": "vimeo.json"}


def test_all_skips_a_network_stage_whose_output_already_exists(tmp_path, monkeypatch):
    build = tmp_path / "_build"
    build.mkdir()
    (build / "elucidat.json").write_text("{}")
    (build / "course.json").write_text("{}")

    ran = []
    monkeypatch.setattr(si_archive_bin, "run_stage", lambda name, args: ran.append(name))

    si_archive_bin.main(["all", "--out", str(tmp_path)])

    assert "elucidat" not in ran
    assert "vimeo" in ran  # vimeo.json doesn't exist yet -- still runs
    assert "cartridge" in ran  # not a network stage -- always runs


def test_all_with_force_reruns_a_network_stage_that_already_has_output(tmp_path, monkeypatch):
    build = tmp_path / "_build"
    build.mkdir()
    (build / "elucidat.json").write_text("{}")

    ran = []
    monkeypatch.setattr(si_archive_bin, "run_stage", lambda name, args: ran.append(name))

    si_archive_bin.main(["all", "--out", str(tmp_path), "--force"])

    assert "elucidat" in ran
    assert "vimeo" in ran


def test_running_a_network_stage_by_name_always_runs_even_with_existing_output(tmp_path, monkeypatch):
    build = tmp_path / "_build"
    build.mkdir()
    (build / "elucidat.json").write_text("{}")

    ran = []
    monkeypatch.setattr(si_archive_bin, "run_stage", lambda name, args: ran.append(name))

    si_archive_bin.main(["elucidat", "--out", str(tmp_path)])

    # A direct, explicit invocation of one stage is a deliberate re-fetch,
    # not the `all` driver's blind loop -- the skip logic must not apply.
    assert ran == ["elucidat"]


def test_all_runs_every_stage_on_a_fresh_archive_with_no_build_dir_yet(tmp_path, monkeypatch):
    ran = []
    monkeypatch.setattr(si_archive_bin, "run_stage", lambda name, args: ran.append(name))

    si_archive_bin.main(["all", "--out", str(tmp_path)])

    assert ran == si_archive_bin.STAGES
