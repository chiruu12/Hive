"""Tests for world economy system."""

from hive.world.state import WorldState


def test_starting_balance(tmp_dir):
    w = WorldState(tmp_dir)
    fin = w.get_finances("agent-1")
    assert fin.balance == 100.0


def test_apply_job(tmp_dir):
    w = WorldState(tmp_dir)
    result = w.apply_job("agent-1", "analyst")
    assert "Hired" in result
    assert w.agent_job("agent-1") is not None


def test_apply_job_already_employed(tmp_dir):
    w = WorldState(tmp_dir)
    w.apply_job("agent-1", "analyst")
    result = w.apply_job("agent-1", "researcher")
    assert "Already employed" in result


def test_apply_job_requires_skill(tmp_dir):
    w = WorldState(tmp_dir)
    result = w.apply_job("agent-1", "reviewer")
    assert "Missing required skill" in result


def test_work_earns_salary(tmp_dir):
    w = WorldState(tmp_dir)
    w.apply_job("agent-1", "analyst")
    result = w.work("agent-1")
    assert "Earned" in result
    fin = w.get_finances("agent-1")
    assert fin.balance == 150.0  # 100 start + 50 salary


def test_work_unemployed(tmp_dir):
    w = WorldState(tmp_dir)
    result = w.work("agent-1")
    assert "Not employed" in result


def test_quit_job(tmp_dir):
    w = WorldState(tmp_dir)
    w.apply_job("agent-1", "analyst")
    result = w.quit_job("agent-1")
    assert "Quit" in result
    assert w.agent_job("agent-1") is None


def test_learn_skill(tmp_dir):
    w = WorldState(tmp_dir)
    w.get_finances("agent-1").balance = 200.0
    result = w.learn("agent-1", "code_review")
    assert "Studied" in result
    skills = w.get_skills("agent-1")
    assert len(skills) == 1
    assert skills[0].skill_name == "code_review"


def test_learn_insufficient_funds(tmp_dir):
    w = WorldState(tmp_dir)
    w.get_finances("agent-1").balance = 10.0
    result = w.learn("agent-1", "code_review")
    assert "Not enough money" in result


def test_learn_unknown_skill(tmp_dir):
    w = WorldState(tmp_dir)
    result = w.learn("agent-1", "telepathy")
    assert "Unknown skill" in result


def test_gamble_blackjack(tmp_dir):
    w = WorldState(tmp_dir)
    result = w.gamble("agent-1", "blackjack", 10.0)
    assert result.wager == 10.0
    assert result.game == "blackjack"
    fin = w.get_finances("agent-1")
    if result.won:
        assert fin.balance == 110.0  # 100 - 10 + 20
    else:
        assert fin.balance == 90.0  # 100 - 10


def test_gamble_no_money(tmp_dir):
    w = WorldState(tmp_dir)
    w.get_finances("agent-1").balance = 0.0
    result = w.gamble("agent-1", "blackjack", 10.0)
    assert not result.won
    assert result.wager == 0


def test_available_jobs(tmp_dir):
    w = WorldState(tmp_dir)
    jobs = w.available_jobs()
    assert len(jobs) >= 3
    w.apply_job("agent-1", "analyst")
    jobs_after = w.available_jobs()
    assert len(jobs_after) == len(jobs) - 1


def test_get_status(tmp_dir):
    w = WorldState(tmp_dir)
    w.apply_job("agent-1", "analyst")
    status = w.get_status("agent-1")
    assert "Data Analyst" in status
    assert "$" in status


def test_state_persists(tmp_dir):
    w1 = WorldState(tmp_dir)
    w1.apply_job("agent-1", "analyst")
    w1.work("agent-1")

    w2 = WorldState(tmp_dir)
    assert w2.agent_job("agent-1") is not None
    assert w2.get_finances("agent-1").balance == 150.0
