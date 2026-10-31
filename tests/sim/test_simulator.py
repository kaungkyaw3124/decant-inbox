"""docs/SPEC-v4.20-automation-goal.md A1/A3: the customer simulator, offline (recorded AI answers in
tests/sim/cassettes.json). One test per scenario file, so pytest-xdist runs files in parallel. Every file must
meet the goal on its own: automatic >= 90%, 0 wrong, 0 silent; the live bugs (01_live.yaml) pass 100%.
A missing recorded answer fails here: re-record with `python -m scripts.simulate --ai record` (prompt changed)."""
import pytest

from scripts import simulate

FILES = sorted(p.name for p in simulate.SCENARIOS.glob("*.yaml"))


@pytest.mark.parametrize("name", FILES)
def test_scenario_file(db, name):
    scenarios = [s for s in simulate.load_scenarios() if s["file"] == name]
    cassette = simulate.CassetteProvider()
    result = simulate.run(scenarios, cassette)
    failed = [f"{sid}#{t.index} got {t.got}: {'; '.join(t.problems)} | {' / '.join(t.replies)[:200]}"
              for sid, t in result.failed]
    assert cassette.misses == 0, f"{cassette.misses} AI answers not recorded: run scripts.simulate --ai record"
    assert result.wrong == 0 and result.silent == 0, "\n".join(failed)
    assert result.automatic >= simulate.GOAL_AUTOMATIC, "\n".join(failed)
    if name == "01_live.yaml":
        assert not failed, "\n".join(failed)  # live bugs: must pass forever


def test_scenario_count_and_ids():
    scenarios = simulate.load_scenarios()  # raises on a duplicate id
    assert len(scenarios) >= 200 and sum(s.get("hand", False) for s in scenarios) >= 80


def test_judge_catches_wrong_numbers_and_phones():
    """The strict judge (A4) on made-up replies, without a database."""
    assert simulate._amounts("• Eros 10ml – 25,000 ကျပ်\nစုစုပေါင်း 50,000") == {10, 25000, 50000}
    assert simulate._phones("09 420 009 999 / +959420001212 / ၀၉၄၂၀၀၀၁၃၁၃") == [
        "09420009999", "09420001212", "09420001313"]
    assert simulate.PROMISE.search("ငွေပြန်အမ်းပေးပါမယ်") and not simulate.PROMISE.search("စစ်ပြီး ပြန်ပြောပေးပါမယ်")
